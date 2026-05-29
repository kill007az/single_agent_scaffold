# Single-Agent Scaffold — agent6

A single-agent system built on the **agent6** architecture: four typed cognitive roles (Memory → Perception → Decision → Action) wired in a loop over an MCP tool server and the LLM Gateway V3.

---

## Architecture

| Role | File | Responsibility |
|------|------|----------------|
| Memory | `agent/memory.py` | Typed store for facts, preferences, tool outcomes, scratchpad |
| Perception | `agent/perception.py` | Decompose query → goals, track done-flags, attach artifacts |
| Decision | `agent/decision.py` | Pick next action (answer or tool call) via native tool calling |
| Action | `agent/action.py` | Dispatch MCP tool calls; store large payloads as artifacts |

Every role boundary is typed with Pydantic v2. No free-form dict passing between roles. No regex on LLM output.

---

## Setup

**Prerequisites:** Python ≥ 3.13, [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/kill007az/single_agent_scaffold.git
cd single_agent_scaffold
uv sync

cp .env.example .env
# Fill in your API keys — at minimum one LLM provider key and TAVILY_API_KEY for web search
```

---

## Running

Three terminals are required. Start them in order.

**Terminal 1 — LLM Gateway**
```bash
cd llm_gatewayV3
uv run uvicorn main:app --port 8101
```

**Terminal 2 — MCP Tool Server**
```bash
uv run mcp_server/server.py --http 8200
```

The MCP server must run as a separate process (SSE transport on port 8200). The agent connects to it via the `MCP_SERVER_URL` already set in `.env`. Running it embedded in the agent process causes crawl4ai's headless browser to inherit the agent's stdio pipe and deadlock.

**Terminal 3 — Agent CLI**
```bash
uv run agent.py "your query here"
```

**Terminal 3 (alternative) — Web UI**
```bash
uv run ui/server.py --port 7100
# Open http://localhost:7100
```

**Reset state between runs**
```powershell
Remove-Item state\memory.json -ErrorAction SilentlyContinue
Remove-Item state\artifacts\* -ErrorAction SilentlyContinue
```

---

## Queries

### Query A — Claude Shannon Wikipedia
> *Artifact attach test: fetches a ~250 KB Wikipedia page, stores it as an artifact, Perception auto-attaches it to the extraction goal so Decision answers without re-fetching.*

```
Fetch https://en.wikipedia.org/wiki/Claude_Shannon and tell me his birth date, death date, and three key contributions to information theory.
```

```bash
uv run agent.py "Fetch https://en.wikipedia.org/wiki/Claude_Shannon and tell me his birth date, death date, and three key contributions to information theory."
```

**Expected iterations:** 3

```

```

---

### Query B — Tokyo activities with weather constraint
> *Multi-goal with fetch + memory carryover: search for activities → fetch full details from top result → check weather → recommend. The weather fact written by Action is read by Decision through the memory keyword search.*

```
Find 3 family-friendly things to do in Tokyo this weekend — search for options and fetch the details from the top result. Then check Saturday's weather forecast and tell me which activity is most appropriate.
```

```bash
uv run agent.py "Find 3 family-friendly things to do in Tokyo this weekend — search for options and fetch the details from the top result. Then check Saturday's weather forecast and tell me which activity is most appropriate."
```

**Expected iterations:** 4

```
06:41:50  RUN START  query="Find 3 family-friendly things to do in Tokyo this weekend. Check Saturday's weather forecast there and tell me which one is most appropriate."
06:41:57    iter 1  start
06:41:57    iter 1  memory   1 hits
06:42:18    iter 1  goal     [o] Identify 3 family-friendly activities in Tokyo.
06:42:18    iter 1  goal     [o] Get the weather forecast for Tokyo for this coming Saturday.
06:42:18    iter 1  goal     [o] Recommend the most appropriate activity based on the weather forecast.
06:42:22    iter 1  decision TOOL_CALL web_search({'max_results': 5, 'query': 'family-friendly activities in T)
06:42:26    iter 1  action  [ok]  [artifact art:b791ffdfd34c9246, 11994 bytes] preview: {   "title": "The best Tokyo Family-friendly a
06:42:26    iter 2  start
06:42:26    iter 2  memory   2 hits
06:42:44    iter 2  goal     [+] Identify 3 family-friendly activities in Tokyo.
06:42:44    iter 2  goal     [o] Get the weather forecast for Tokyo for this coming Saturday.
06:42:44    iter 2  goal     [o] Recommend the most appropriate activity based on the weather forecast.
06:42:58    iter 2  decision TOOL_CALL web_search({'query': 'weather forecast Tokyo this coming Saturday'})
06:43:01    iter 2  action  [ok]  [artifact art:aa08dbc23b2073f8, 9432 bytes] preview: {   "title": "Tokyo Weather in May 2026: Temper
06:43:01    iter 3  start
06:43:01    iter 3  memory   3 hits
06:43:08    iter 3  goal     [+] Identify 3 family-friendly activities in Tokyo.
06:43:08    iter 3  goal     [+] Get the weather forecast for Tokyo for this coming Saturday.
06:43:08    iter 3  goal     [o] Recommend the most appropriate activity based on the weather forecast.
06:43:08    iter 3  attach   art:aa08dbc23b2073f8 (9432 bytes)
06:43:15    iter 3  decision ANSWER    Based on the weather forecast for this coming Saturday, May 30th, 2026, Tokyo is
06:43:15    iter 4  start
06:43:15    iter 4  memory   3 hits
06:43:19    iter 4  goal     [+] Identify 3 family-friendly activities in Tokyo.
06:43:19    iter 4  goal     [+] Get the weather forecast for Tokyo for this coming Saturday.
06:43:19    iter 4  goal     [+] Recommend the most appropriate activity based on the weather forecast.
06:43:19    iter 4  all goals satisfied — synthesising
06:43:25    synthesis  Based on the weather forecast for this coming Saturday, May 30th, 2026, Tokyo is expected to have "p
06:43:25  RUN END    exit=0  94.1s  run=cd1b45c7
06:43:25    FINAL: Based on the weather forecast for this coming Saturday, May 30th, 2026, Tokyo is expected to have "partly cloudy" skies...
```

---

### Query C — Mom's birthday (durable memory across runs)
> *Tests persistent memory: Run 1 classifies the fact and writes reminder files; Run 2 reads `state/memory.json` and answers directly in 2 iterations with no tool calls.*

**Run 1**
```bash
uv run agent.py "My mom's birthday is 15 May 2026. Remember that and give me a calendar reminder for two weeks before and on the day."
```

**Run 2** *(do not delete `state/` between runs)*
```bash
uv run agent.py "When is mom's birthday?"
```

**Expected iterations:** 4 (Run 1), 2 (Run 2)

**Run 1:**
```
06:45:20  RUN START  query="My mom's birthday is 15 May 2026. Remember that and give me a calendar reminder for two weeks before and on the day."
06:45:39    iter 1  start
06:45:39    iter 1  memory   1 hits
06:45:46    iter 1  goal     [o] Create a calendar reminder for 1 May 2026
06:45:46    iter 1  goal     [o] Create a calendar reminder for 15 May 2026
06:45:50    iter 1  decision TOOL_CALL create_file({'content': 'Calendar Reminder:\nDate: 1 May 2026\n\nThis is)
06:45:50    iter 1  action  [ok]  ok: True  ·  path: reminders/may_01_2026.txt  ·  size_bytes: 74
06:45:50    iter 2  start
06:45:50    iter 2  memory   2 hits
06:46:04    iter 2  goal     [+] Create a calendar reminder for 1 May 2026
06:46:04    iter 2  goal     [o] Create a calendar reminder for 15 May 2026
06:46:08    iter 2  decision TOOL_CALL create_file({'content': 'Calendar Reminder:\nDate: 15 May 2026\n\nThis i)
06:46:08    iter 2  action  [ok]  ok: True  ·  path: reminders/may_15_2026.txt  ·  size_bytes: 76
06:46:08    iter 3  start
06:46:08    iter 3  memory   3 hits
06:46:12    iter 3  goal     [+] Create a calendar reminder for 1 May 2026
06:46:12    iter 3  goal     [+] Create a calendar reminder for 15 May 2026
06:46:12    iter 3  all goals satisfied — synthesising
06:46:27    synthesis  I have successfully saved the reminders for your mother's birthday. The following files have been cr
06:46:27  RUN END    exit=0  67.1s  run=3f6d3d89
06:46:27    FINAL: I have successfully saved the reminders for your mother's birthday. The following files have been created:\n\n1.  **remi...
```

**Run 2:**
```
06:46:39  RUN START  query="When is mom's birthday?"
06:46:47    iter 1  start
06:46:47    iter 1  memory   2 hits
06:46:51    iter 1  goal     [+] Identify the date of mom's birthday from the memory hits.
06:46:51    iter 1  goal     [o] Inform the user of the identified birthday date.
06:46:55    iter 1  decision ANSWER    Your mother’s birthday is on **May 15, 2026**....
06:46:55    iter 2  start
06:46:55    iter 2  memory   2 hits
06:46:59    iter 2  goal     [+] Identify the date of mom's birthday from the memory hits.
06:46:59    iter 2  goal     [+] Inform the user of the identified birthday date.
06:46:59    iter 2  all goals satisfied — synthesising
06:47:08    synthesis  Your mother’s birthday is on **May 15, 2026**.
06:47:08  RUN END    exit=0  28.9s  run=4759611b
06:47:08    FINAL: Your mother’s birthday is on **May 15, 2026**.
```

---

### Query D — Python asyncio best practices (multi-source synthesis)
> *Multi-artifact attachment: search → fetch 3 pages (3 artifacts) → synthesise. Perception's synthesis guard auto-attaches the most recent relevant artifact to the synthesis goal.*

```
Search for 'Python asyncio best practices', read the top 3 results, and give me a short numbered list of the advice they agree on.
```

```bash
uv run agent.py "Search for 'Python asyncio best practices', read the top 3 results, and give me a short numbered list of the advice they agree on."
```

**Expected iterations:** 6

```
06:47:22  RUN START  query="Search for 'Python asyncio best practices', read the top 3 results, and give me a short numbered list of the advice they agree on."
06:47:29    iter 1  start
06:47:29    iter 1  memory   1 hits
06:47:33    iter 1  goal     [o] Search for 'Python asyncio best practices'
06:47:33    iter 1  goal     [o] Fetch the content of the top 3 search results
06:47:33    iter 1  goal     [o] Summarize the advice from the fetched results into a numbered list of common bes
06:47:37    iter 1  decision TOOL_CALL web_search({'max_results': 5, 'query': 'Python asyncio best practices'})
06:47:38    iter 1  action  [ok]  [artifact art:f06fd04113d336ca, 9584 bytes] preview: {   "title": "Asyncio Best Practices and Common
06:47:38    iter 2  start
06:47:38    iter 2  memory   2 hits
06:47:45    iter 2  goal     [+] Search for 'Python asyncio best practices'
06:47:45    iter 2  goal     [o] Fetch the content of the top 3 search results
06:47:45    iter 2  goal     [o] Summarize the advice from the fetched results into a numbered list of common bes
06:47:45    iter 2  attach   art:f06fd04113d336ca (9584 bytes)
06:47:52    iter 2  decision TOOL_CALL fetch_url({'url': 'https://www.shanechang.com/p/python-asyncio-best-pr)
06:48:05    iter 2  action  [ok]  [artifact art:4b12344d2c8b0e5c, 8594 bytes] preview: {   "status": 301,   "content_type": "text/mark
06:48:05    iter 3  start
06:48:05    iter 3  memory   3 hits
06:48:22    iter 3  goal     [+] Search for 'Python asyncio best practices'
06:48:22    iter 3  goal     [o] Fetch the content of the top 3 search results
06:48:22    iter 3  goal     [o] Summarize the advice from the fetched results into a numbered list of common bes
06:48:22    iter 3  attach   art:f06fd04113d336ca (9584 bytes)
06:48:27    iter 3  decision TOOL_CALL fetch_url({'url': 'https://discuss.python.org/t/asyncio-best-practices)
06:48:31    iter 3  action  [ok]  [artifact art:ea64b8a79061aae3, 6745 bytes] preview: {   "status": 200,   "content_type": "text/mark
06:48:31    iter 4  start
06:48:31    iter 4  memory   4 hits
06:48:35    iter 4  goal     [+] Search for 'Python asyncio best practices'
06:48:35    iter 4  goal     [o] Fetch the content of the top 3 search results
06:48:35    iter 4  goal     [o] Summarize the advice from the fetched results into a numbered list of common bes
06:48:35    iter 4  attach   art:f06fd04113d336ca (9584 bytes)
06:48:44    iter 4  decision TOOL_CALL fetch_url({'url': 'https://oneuptime.com/blog/post/2026-01-24-asyncio-)
06:48:46    iter 4  action  [ok]  [artifact art:e797f2e1b54bca74, 34509 bytes] preview: {   "status": 200,   "content_type": "text/mar
06:48:46    iter 5  start
06:48:46    iter 5  memory   5 hits
06:48:53    iter 5  goal     [+] Search for 'Python asyncio best practices'   
06:48:53    iter 5  goal     [+] Fetch the content of the top 3 search results
06:48:53    iter 5  goal     [o] Summarize the advice from the fetched results into a numbered list of common bes
06:48:53    iter 5  attach   art:4b12344d2c8b0e5c (8594 bytes)
06:48:59    iter 5  decision ANSWER    Based on the gathered resources, here are the common best practices for working
06:48:59    iter 6  start
06:48:59    iter 6  memory   5 hits
06:49:19    iter 6  goal     [+] Search for 'Python asyncio best practices'   
06:49:19    iter 6  goal     [+] Fetch the content of the top 3 search results
06:49:19    iter 6  goal     [+] Summarize the advice from the fetched results into a numbered list of common bes
06:49:19    iter 6  all goals satisfied — synthesising
06:49:25    synthesis  Based on the three sources analyzed, here is a numbered list of the core best practices for Python's
06:49:25  RUN END    exit=0  122.7s  run=209e6ca0
06:49:25    FINAL: Based on the three sources analyzed, here is a numbered list of the core best practices for Python's `asyncio` that they...
```

---

## Prompts

System prompts live in `prompts/` and are hot-reloadable via `prompt_store.reload()`:

| File | Role |
|------|------|
| `prompts/perception.txt` | Goal decomposition, done-flag logic, artifact attach rules |
| `prompts/decision.txt` | Action selection, tool call argument population, answer rules |
| `prompts/memory.txt` | Fact classification, keyword extraction |

---

## Web UI

```bash
uv run ui/server.py --port 7100
```

Opens at `http://localhost:7100`. The pipeline view shows Memory → Perception → Decision → Action columns lighting up in real time per iteration. The left panel keeps a chat-style history of all queries and answers in the session.

---

## Project Structure

```
single_agent_scaffold/
├── agent/
│   ├── memory.py        # MemoryService — read, remember, record_outcome
│   ├── perception.py    # Perception.observe — goals, done-flags, attachments
│   ├── decision.py      # Decision.next_step — native tool calling
│   ├── action.py        # Action.execute — MCP dispatch, artifact storage
│   ├── artifacts.py     # Content-addressable blob store (state/artifacts/)
│   ├── gateway.py       # LLM Gateway V3 client wrapper
│   ├── prompt_store.py  # Load/cache prompts from prompts/*.txt
│   └── schemas.py       # Pydantic contracts between roles (source of truth)
├── mcp_server/
│   └── server.py        # MCP tools: web_search, fetch_url, get_time, currency_convert, file ops
├── llm_gatewayV3/       # LLM Gateway V3 (router + worker pool, multi-provider)
├── prompts/             # System prompts for each role
├── ui/
│   ├── server.py        # FastAPI SSE server — streams agent stdout to browser
│   └── static/
│       └── index.html   # Pipeline UI with real-time glow animations + chat history
├── state/               # Runtime state (gitignored)
│   ├── memory.json      # Persisted memory items
│   └── artifacts/       # Content-addressable artifact blobs
├── sandbox/             # Agent file I/O sandbox
├── agent.py             # Main loop entry point
└── pyproject.toml
```
