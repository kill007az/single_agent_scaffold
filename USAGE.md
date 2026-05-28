# Using the Single-Agent Scaffold

This document covers everything from first run to building your own domain-specific agent.

---

## Quick start

**Prerequisites:** Python 3.13+, [uv](https://docs.astral.sh/uv/getting-started/installation/), API keys for at least one provider (Gemini recommended).

```bash
# 1. Copy and fill in your API keys
cp .env.example .env
# Edit .env — at minimum set GEMINI_API_KEY

# 2. Install dependencies
uv sync

# 3. Terminal A — start the LLM gateway
cd llm_gatewayV3
uv run uvicorn main:app --port 8101

# 4. Terminal B — start the UI (from project root)
uv run ui/server.py

# 5. Open http://localhost:7100
```

The gateway must be running before the agent. If you see `502` errors in the UI, the gateway is not up.

---

## The UI

Open `http://localhost:7100` after starting `ui/server.py`.

### Query input

Type any question and press **Run** (or `Ctrl+Enter` / `Cmd+Enter`). Use the example chips to try pre-built queries.

### Goals panel (left sidebar)

Every run starts with Perception decomposing your query into discrete goals. Each goal shows its live status:

- **○ amber** — open, not yet completed
- **✓ green** — done, the agent has gathered what it needs

Goals update in real time as iterations complete. A goal never goes from done back to open.

### Agent loop (main area)

Each iteration appears as a card:

| Row | What it shows |
|-----|---------------|
| `◈ N memory hits` | How many stored facts were relevant to this iteration |
| `⚙ tool_name` | The tool Decision chose to call, with its arguments |
| `→ result` | The tool's output (key fields shown; artifacts stored separately) |
| `💬 answer` | If Decision answered directly instead of calling a tool |
| `⛔ blocked` | A tool call that failed argument validation before dispatch |
| `📎 artifact` | A large result stored as a blob (not shown inline) |

Between iterations you'll see a pulsing "thinking" indicator showing which stage the agent is in.

### Final answer

When all goals are satisfied, a synthesis step produces the final answer. It appears in the sidebar below the goals and can be copied with the **Copy** button.

### Header controls

| Control | What it does |
|---------|--------------|
| Memory / Artifacts count | Live count of persisted facts and blobs from this session |
| Status dot | Idle (grey) · Running (pulsing indigo) · Done (green) · Error (red) |
| Elapsed timer | Wall-clock time for the current run |
| **Clear** | Resets the visual display only — memory is preserved |
| **Wipe Session** | Deletes all memory items and artifact blobs. Two-step confirm. Use this between unrelated experiments to avoid stale facts bleeding in. |

---

## CLI usage

The agent also runs headlessly from the terminal:

```bash
# Single query
uv run agent.py "What time is it in Tokyo and New York?"

# Interactive REPL
uv run agent.py
```

Log format reference:

```
[run:abc123] query: ...       — new run, run ID
─── iter N ───               — iteration boundary
[memory.read]   N hits        — memory lookup result
[perception]    [open] text   — goal not yet complete
[perception]    [done] text   — goal satisfied
[decision]      TOOL_CALL: name({args})   — tool chosen
[action]        → result      — tool output (truncated to 120 chars)
[validate]      BLOCKED: ...  — invalid tool arguments, not dispatched
[done] all goals satisfied    — loop complete
[synthesis]     ...           — final answer (first 200 chars)
FINAL: ...                    — complete final answer
```

---

## Building your first agent

Follow these steps to adapt the scaffold to a new problem. The only files you ever touch are `mcp_server/server.py` and optionally `prompts/`.

### Step 1 — Define your use case and identify tools

Write out what your agent needs to *do*, not what it should *know*. Each distinct external operation becomes one tool.

**Example problem statement:**

> "I want an agent that can look up a stock price, convert it to another currency, and write a one-line summary to a file."

Tools needed:
- `get_stock_price(ticker)` → fetch from a free API
- `currency_convert(amount, from_currency, to_currency)` → already built in
- `create_file(path, content)` → already built in

### Step 2 — Add tools to `mcp_server/server.py`

Open `mcp_server/server.py`. Add decorated functions in the "Add your domain-specific tools here" section:

```python
@mcp.tool()
def get_stock_price(ticker: str) -> dict:
    """Fetch the latest stock price for a ticker symbol. Example: get_stock_price("AAPL")."""
    import httpx
    ticker = ticker.upper()
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    with httpx.Client(timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as c:
        r = c.get(url)
        r.raise_for_status()
        data = r.json()
    price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
    currency = data["chart"]["result"][0]["meta"]["currency"]
    return {"ticker": ticker, "price": price, "currency": currency}
```

Three rules for tool functions:
1. **The docstring is the tool description.** Include an example call — Decision uses it to understand when and how to call the tool.
2. **All parameters need type annotations.** MCP uses these to build the input schema that Decision validates against.
3. **Return a dict or list.** Avoid returning plain strings — structured data is easier for the agent to use across iterations.

No restart needed — the MCP server is launched fresh each run.

### Step 3 — Run a query and watch the loop

```bash
uv run agent.py "Get Apple's stock price, convert it to GBP, and save the result to portfolio.txt"
```

Or use the UI. Watch the Goals panel — you should see Perception decompose this into three goals, one per tool. If the goals don't match what you expected, that's a prompt tuning problem (Step 4).

### Step 4 — Tune prompts (optional)

If Perception is decomposing goals incorrectly, or Decision is calling the wrong tools, edit the system prompts in `prompts/`:

| File | Controls |
|------|----------|
| `prompts/perception.txt` | How the query is decomposed into goals, what "done" means per goal |
| `prompts/decision.txt` | How Decision chooses tools vs answering directly |
| `prompts/memory.txt` | How facts are classified and stored |

Changes take effect on the next run. You can hot-reload without restarting:

```python
from agent import prompt_store
prompt_store.reload()
```

### Step 5 — Use memory across runs

After the first run, the agent stores facts in `state/memory.json`. On subsequent runs those facts are retrieved and injected into every iteration. This means:

- A second query about the same stock ticker will recall the previous price from memory, potentially skipping the API call.
- Preferences ("always show prices in GBP") can be stated once and remembered.

To see what's stored: `cat state/memory.json`

To reset between experiments: use **Wipe Session** in the UI or delete the file manually.

---

## Extension reference

### Adding a tool

```python
# mcp_server/server.py
@mcp.tool()
def my_tool(param: str, count: int = 5) -> dict:
    """What this tool does. Example: my_tool("value", 3)."""
    return {"result": "..."}
```

The tool appears in the next run automatically. No other file needs to change.

### Editing a system prompt

Edit any file in `prompts/`. The change takes effect on the next run. If you want to test mid-session without restarting, run `prompt_store.reload()` in a Python shell.

### Adding an LLM provider

1. Add your API key to `.env`
2. Open `llm_gatewayV3/providers.py`
3. Add a class that extends `OpenAICompatProvider` (or `BaseProvider` for non-OpenAI APIs)
4. Register it in `build_providers()` at the bottom of the file
5. Add it to `TIER_TO_ORDER` in `llm_gatewayV3/main.py` for auto-routing

### Changing which model handles which role

By default:
- **Perception** — pinned to Gemini (`provider="g"` in `agent/perception.py`)
- **Decision** — auto-routed (TINY → Groq, LARGE → Gemini)
- **Memory classification** — pinned to Gemini

To change Perception to use Groq: edit `agent/perception.py`, change `provider="g"` to `provider="gr"`.

To change the tier routing order, edit `TIER_TO_ORDER` in `llm_gatewayV3/main.py`.

### Swapping the memory backend

The `MemoryService` interface is stable:
- `read(query, history)` → `list[MemoryItem]`
- `filter(kinds, goal_id, recent)` → `list[MemoryItem]`
- `remember(text, source, run_id)` → `MemoryItem`
- `record_outcome(tool_call, result_text, artifact_id, run_id)` → `MemoryItem`

You can swap the JSON file backend for a vector DB or SQL store without touching any role file. Replace the `_load` / `_save` / `read` implementations in `agent/memory.py`.

---

## Troubleshooting

**Gateway not running**
The UI shows a `502` or connection error. Start the gateway first:
```bash
cd llm_gatewayV3 && uv run uvicorn main:app --port 8101
```

**`[memory.remember] warning: ...`**
Transient gateway error during the memory classification call. The agent continues — memory just won't have the new fact. Check gateway logs.

**Goals never marked done**
Perception isn't recognising the goal as satisfied. Either the tool result doesn't contain what the prompt expects, or the prompt's done-condition language is too strict. Edit `prompts/perception.txt` and look at the STEP 3 — DONE EVALUATION section.

**`FINAL: (no answer produced)`**
The synthesis step returned nothing. Usually means Decision responded to the synthesis goal with a tool call instead of an answer. Add "answer directly" emphasis to the synthesis goal text in `agent.py` or lower the temperature.

**Artifact not found**
`state/memory.json` references an artifact handle that no longer exists in `state/artifacts/`. This can happen if you manually delete files. Use **Wipe Session** to clear both together.

**Windows box-drawing characters garbled in terminal**
The agent already calls `sys.stdout.reconfigure(encoding="utf-8")`. If your terminal still shows `???` instead of `─`, set `PYTHONIOENCODING=utf-8` in your shell before running.

**`ModuleNotFoundError` for `ddgs`, `tavily`, or `crawl4ai`**
These are optional. Install with:
```bash
uv add --optional mcp-tools
```
