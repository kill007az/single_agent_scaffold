"""Web UI server for the single-agent scaffold.

Streams agent.py stdout as typed SSE events so the browser can render
the Memory → Perception → Decision → Action loop live.

Usage:
    uv run ui/server.py              # http://localhost:7100
    uv run ui/server.py --port 3000
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import json
import re
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent.parent
STATIC = Path(__file__).parent / "static"
STATE = ROOT / "state"

app = FastAPI(title="Single-Agent Scaffold UI")


# ── Log line patterns ─────────────────────────────────────────────────────────

_RUN_START  = re.compile(r'^\[run:([a-f0-9]+)\] query: (.+)$')
_ITER_START = re.compile(r'^─+\s*iter (\d+)\s*─+$')
_MEMORY     = re.compile(r'^\[memory\.read\]\s+(\d+) hits$')
_GOAL       = re.compile(r'^\[perception\]\s+\[(open|done)\] (.+?)(?:\s+attach=(\S+))?$')
_TOOL_CALL  = re.compile(r'^\[decision\]\s+TOOL_CALL: (\w+)\((.+)\)$')
_ANSWER     = re.compile(r'^\[decision\]\s+ANSWER: (.+)$')
_ACTION     = re.compile(r'^\[action\]\s+→\s*(.*)')
_VALIDATE   = re.compile(r'^\[validate\]\s+BLOCKED: (.+)$')
_ATTACH     = re.compile(r'^\[attach\]\s+(\S+) \((\d+) bytes\)$')
_SYNTHESIS  = re.compile(r'^\[synthesis\]\s+(.+)$')
_FINAL      = re.compile(r'^FINAL: (.+)$')
_ALL_DONE   = re.compile(r'^\[done\] all goals satisfied')
_STOPPED    = re.compile(r'^\[stopped\] reached MAX_ITERATIONS=(\d+)$')
_GW_RETRY   = re.compile(r'^\[gateway\] HTTP (\d+)')

# Lines that indicate the end of a multi-line action block
_SECTION_PREFIXES = ("─", "[memory", "[perception", "[decision", "[action", "[done",
                     "[stopped", "[gateway", "[validate", "[attach", "[synthesis", "FINAL:")


def _try_parse_args(raw: str) -> dict | str:
    """Parse {'k': 'v', ...} from TOOL_CALL line. Returns dict or raw string."""
    try:
        return ast.literal_eval(raw)
    except Exception:
        pass
    try:
        return json.loads(raw.replace("'", '"'))
    except Exception:
        return raw


def _summarise_action(lines: list[str]) -> str:
    """Turn buffered action output into a short human-readable string."""
    full = "\n".join(lines).strip()
    if not full:
        return ""
    try:
        data = json.loads(full)
        if isinstance(data, dict):
            parts = [f"{k}: {str(v)[:60]}" for k, v in list(data.items())[:5]]
            return "  ·  ".join(parts)
        return str(data)[:200]
    except Exception:
        return full[:300]


def _sse(event_type: str, payload: dict) -> str:
    payload["type"] = event_type
    return f"data: {json.dumps(payload)}\n\n"


# ── SSE stream ────────────────────────────────────────────────────────────────

@app.get("/stream")
async def stream(query: str, request: Request):
    async def generate():
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(ROOT / "agent.py"), query,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(ROOT),
        )

        action_buf: list[str] = []
        current_iter = 0

        def flush_action() -> str | None:
            if not action_buf:
                return None
            summary = _summarise_action(action_buf)
            action_buf.clear()
            ok = not summary.lower().startswith("error")
            return _sse("action_result", {"iter": current_iter, "summary": summary, "ok": ok})

        try:
            async for raw in proc.stdout:
                if await request.is_disconnected():
                    proc.kill()
                    break

                line = raw.decode("utf-8", errors="replace").rstrip()

                # ── Multi-line action block collection ─────────────────────
                m = _ACTION.match(line)
                if m:
                    flush_ev = flush_action()
                    if flush_ev:
                        yield flush_ev
                    first = m.group(1).strip()
                    if first:
                        action_buf.append(first)
                    continue

                if action_buf:
                    # Is this a continuation line or a new section?
                    is_section = any(line.startswith(p) for p in _SECTION_PREFIXES)
                    if is_section or not line.strip():
                        flush_ev = flush_action()
                        if flush_ev:
                            yield flush_ev
                        # Fall through to parse the section line below
                    else:
                        action_buf.append(line)
                        continue

                # ── Parse known line patterns ──────────────────────────────
                if m := _RUN_START.match(line):
                    yield _sse("run_start", {"run_id": m.group(1), "query": m.group(2)})

                elif m := _ITER_START.match(line):
                    current_iter = int(m.group(1))
                    yield _sse("iter_start", {"iter": current_iter})

                elif m := _MEMORY.match(line):
                    yield _sse("memory", {"iter": current_iter, "hits": int(m.group(1))})

                elif m := _GOAL.match(line):
                    yield _sse("goal", {
                        "iter": current_iter,
                        "status": m.group(1),
                        "text": m.group(2).strip(),
                        "attach": m.group(3),
                    })

                elif m := _TOOL_CALL.match(line):
                    yield _sse("tool_call", {
                        "iter": current_iter,
                        "name": m.group(1),
                        "arguments": _try_parse_args(m.group(2)),
                    })

                elif m := _ANSWER.match(line):
                    yield _sse("answer_preview", {"iter": current_iter, "text": m.group(1)})

                elif m := _VALIDATE.match(line):
                    yield _sse("blocked", {"iter": current_iter, "error": m.group(1)})

                elif m := _ATTACH.match(line):
                    yield _sse("attach", {
                        "iter": current_iter,
                        "artifact_id": m.group(1),
                        "size": int(m.group(2)),
                    })

                elif _ALL_DONE.match(line):
                    yield _sse("all_done", {"iter": current_iter})

                elif m := _SYNTHESIS.match(line):
                    yield _sse("synthesis", {"text": m.group(1)})

                elif m := _FINAL.match(line):
                    yield _sse("final", {"answer": m.group(1)})

                elif m := _STOPPED.match(line):
                    yield _sse("stopped", {"max_iter": int(m.group(1))})

                elif m := _GW_RETRY.match(line):
                    yield _sse("gateway_retry", {"status": m.group(1)})

        finally:
            flush_ev = flush_action()
            if flush_ev:
                yield flush_ev
            await proc.wait()
            yield _sse("run_end", {"exit_code": proc.returncode})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.post("/wipe")
async def wipe():
    memory_file = STATE / "memory.json"
    artifacts_dir = STATE / "artifacts"

    mem_wiped = 0
    if memory_file.exists():
        try:
            mem_wiped = len(json.loads(memory_file.read_text()))
        except Exception:
            pass
        memory_file.write_text("[]", encoding="utf-8")

    art_wiped = 0
    if artifacts_dir.exists():
        for f in artifacts_dir.iterdir():
            f.unlink(missing_ok=True)
            art_wiped += 1

    return {"ok": True, "wiped": {"memory_items": mem_wiped, "artifacts": art_wiped}}


@app.get("/status")
async def status():
    memory_file = STATE / "memory.json"
    artifacts_dir = STATE / "artifacts"
    mem = 0
    if memory_file.exists():
        try:
            mem = len(json.loads(memory_file.read_text()))
        except Exception:
            pass
    arts = len(list(artifacts_dir.glob("*.bin"))) if artifacts_dir.exists() else 0
    return {"memory_items": mem, "artifacts": arts}


# Static files — mounted last so API routes take precedence
app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Single-Agent Scaffold UI")
    parser.add_argument("--port", type=int, default=7100)
    args = parser.parse_args()
    print(f"\n  Single-Agent Scaffold  ->  http://127.0.0.1:{args.port}\n")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
