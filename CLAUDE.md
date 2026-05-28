# Single-Agent Scaffold — Copilot Instructions

This file tells AI coding copilots (Claude Code, GitHub Copilot, Cursor, etc.) how to work
with this codebase. Read it before making any changes.

---

## What this project is

A single-agent scaffold built on the agent6 architecture. The agent has four cognitive roles:

| Role | File | Responsibility |
|------|------|----------------|
| Memory | `agent/memory.py` | Typed store for facts, preferences, tool outcomes, scratchpad |
| Perception | `agent/perception.py` | Orchestrator: decompose query → goals, track done-flags, attach artifacts |
| Decision | `agent/decision.py` | Pick next action (answer or tool call) for one goal |
| Action | `agent/action.py` | Dispatch MCP tool calls; store large payloads as artifacts |

Supporting components:

| Component | File | Role |
|-----------|------|------|
| Schemas | `agent/schemas.py` | Pydantic contracts between roles (source of truth) |
| Artifacts | `agent/artifacts.py` | Content-addressable blob store (state/artifacts/) |
| Gateway | `agent/gateway.py` | LLM Gateway V3 client wrapper |
| Prompt Store | `agent/prompt_store.py` | Load/cache system prompts from prompts/*.txt |
| MCP Server | `mcp_server/server.py` | Blank local MCP server (extend with tools here) |
| Main Loop | `agent.py` | Entry point — ties the four roles together |

---

## How to extend this scaffold

### Add a new MCP tool

1. Open `mcp_server/server.py`.
2. Add a function decorated with `@mcp.tool()`.
3. The function docstring becomes the tool description visible to Decision.
4. No other file needs to change — the agent discovers tools at startup.

```python
@mcp.tool()
def my_tool(param: str) -> dict:
    """Short description. Example: my_tool("value")."""
    return {"result": ...}
```

### Add or edit a system prompt

System prompts live in `prompts/*.txt`. Each role loads its prompt by filename:
- `prompts/perception.txt` → loaded by `perception.py`
- `prompts/decision.txt` → loaded by `decision.py`
- `prompts/memory.txt` → loaded by `memory.py`

To add a custom prompt for a new component: create `prompts/<name>.txt` and call
`prompt_store.get("<name>")` from your code.

Hot-reload during development: `prompt_store.reload()` clears the cache.

### Add a new LLM provider

Add the provider's credentials to `.env` and register it in `llm_gatewayV3/providers.py`
following the existing pattern. The gateway handles routing automatically.

### Change routing behaviour

Edit `llm_gatewayV3/main.py` — specifically `TIER_TO_ORDER` — to change which provider
handles TINY vs LARGE tier calls. Perception is pinned to Gemini (`provider="g"`) in
`agent/perception.py`; change `provider=` there to switch it.

### Modify memory persistence

Memory lives at `state/memory.json`. To reset: delete that file.
The `MemoryService` class in `agent/memory.py` owns all read/write logic.
The interface (`read`, `filter`, `remember`, `record_outcome`) is stable —
you can swap the storage backend without touching `perception.py`, `decision.py`,
`action.py`, or `agent.py`.

### Modify schemas

All role boundaries are typed in `agent/schemas.py`. If you add a field to `Goal`
or `DecisionOutput`, update the corresponding JSON Schema dict in `perception.py`
or `decision.py` respectively, and update any prompt that references the field names.

---

## Rules for copilots

- **Never modify `agent/schemas.py` without updating the matching JSON Schema dicts** in
  `perception.py` and `decision.py`. They must stay in sync.
- **Keep roles separated.** Memory must not call Perception; Decision must not write Memory.
  The loop in `agent.py` is the only place that calls multiple roles.
- **Do not embed raw bytes in `MemoryItem.value`.** Use `ArtifactStore.put()` and store
  the returned handle in `artifact_id`. Memory holds handles; the artifact store holds bytes.
- **Do not add LLM calls to `action.py`.** Action is pure dispatch — no gateway calls.
- **All new tools go into `mcp_server/server.py`**, not into agent role files.
- **Prompts are editable; code is not the place for prompt text.** If you find a long
  string being passed as `system=` in role files, extract it to `prompts/`.
- **Test with a clean state.** Delete `state/memory.json` and `state/artifacts/` between
  runs when testing to avoid stale memory contaminating results.

---

## How to branch this scaffold for a new project

1. Copy the entire directory (or `git checkout -b <new-project>`).
2. Add your domain-specific tools to `mcp_server/server.py`.
3. Edit the system prompts in `prompts/` to reflect your domain.
4. Keep `agent/`, `agent.py`, and `llm_gatewayV3/` unchanged — they are the scaffold core.
5. Commit. The scaffold core should remain mergeable from main.

---

## Running

```bash
# Install dependencies (uv creates .venv automatically)
uv sync

# Optional MCP server tools (web search, fetch)
uv add ddgs tavily-python crawl4ai

# Copy and fill in your API keys
cp .env.example .env

# Start the LLM gateway (in a separate terminal)
cd llm_gatewayV3 && uv run uvicorn main:app --port 8101

# Run the agent
uv run agent.py "Your query here"

# Or via the installed script entry point
uv run agent "Your query here"

# Interactive REPL
uv run agent.py

# Run the MCP server standalone (for testing tools)
uv run mcp_server/server.py --http 8200
```

---

## Key invariants

1. **Memory is read at the top of every iteration** before any other role runs.
2. **Goals have positional identity** — Perception must not reorder or drop goals once set.
3. **Artifact handles (`art:...`) are never passed as MCP tool arguments** — Action guards this.
4. **Perception marks goals done — Decision does not** — Decision selects actions only.
5. **The gateway is the single entry point for all LLM calls** — roles never call provider
   APIs directly.
