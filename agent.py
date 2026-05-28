"""Single-agent scaffold — main loop.

Architecture (agent6):
    Memory → Perception → Decision → Action (MCP)

The loop:
1. Classifies the user query into durable memory (one gateway call).
2. Each iteration: reads memory → Perception observes → Decision picks
   an action or answers → Action dispatches MCP → record outcome.
3. Terminates when Perception marks all goals done.

Usage:
    python agent.py "Your query here"
    python agent.py   # interactive REPL
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

# Force UTF-8 output on Windows so box-drawing characters don't crash
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv(Path(__file__).parent / ".env")

from agent import action, decision, perception
from agent.artifacts import artifacts
from agent.gateway import ensure_gateway
from agent.memory import memory
from agent.schemas import ActionRequest, Goal, MCPTool

MCP_SERVER = Path(__file__).parent / "mcp_server" / "server.py"
MAX_ITERATIONS = 20


@asynccontextmanager
async def mcp_session():
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(MCP_SERVER)],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _mcp_tools_for_decision(tools: list) -> list[MCPTool]:
    """Convert raw MCP tool objects to typed MCPTool contracts for Decision."""
    return [
        MCPTool(
            name=t.name,
            description=t.description or "",
            input_schema=t.inputSchema if hasattr(t, "inputSchema") else {},
        )
        for t in tools
    ]


def _final_answer(history: list[dict]) -> str:
    answers = [e["text"] for e in history if e.get("kind") == "answer" and e.get("text")]
    return answers[-1] if answers else "(no answer produced)"


async def run(query: str) -> str:
    ensure_gateway()

    run_id = uuid.uuid4().hex[:8]
    history: list[dict] = []
    prior_goals: list[Goal] = []

    print(f"\n[run:{run_id}] query: {query}\n")

    # Classify the query into durable memory so facts persist across runs
    try:
        memory.remember(query, source="user_query", run_id=run_id)
    except Exception as e:
        print(f"[memory.remember] warning: {e}")

    async with mcp_session() as session:
        raw_tools = (await session.list_tools()).tools
        mcp_tools = _mcp_tools_for_decision(raw_tools)

        for it in range(1, MAX_ITERATIONS + 1):
            print(f"─── iter {it} ───")

            hits = memory.read(query, history)
            print(f"[memory.read]   {len(hits)} hits")

            obs = perception.observe(query, hits, history, prior_goals, run_id)
            prior_goals = obs.goals

            for g in obs.goals:
                status = "done" if g.done else "open"
                attach = f"  attach={g.attach_artifact_id}" if g.attach_artifact_id else ""
                print(f"[perception]    [{status}] {g.text}{attach}")

            if obs.all_done:
                print("\n[done] all goals satisfied — synthesising final answer")
                synthesis_goal = Goal(
                    id="synthesis",
                    text=(
                        f"Synthesise a complete answer to the original query: '{query}'. "
                        "Use the results from RECENT HISTORY. Be specific: include all values, "
                        "times, rates, and units retrieved."
                    ),
                )
                out = decision.next_step(synthesis_goal, hits, [], history, mcp_tools)
                final_answer = out.answer if out.is_answer else "(synthesis produced no text)"
                print(f"[synthesis]     {final_answer[:200]}")
                history.append({"iter": it, "kind": "answer", "goal_id": "synthesis", "text": final_answer})
                break

            goal = obs.next_unfinished()

            attached: list[tuple[str, bytes]] = []
            if goal.attach_artifact_id and artifacts.exists(goal.attach_artifact_id):
                blob = artifacts.get_bytes(goal.attach_artifact_id)
                attached.append((goal.attach_artifact_id, blob))
                print(f"[attach]        {goal.attach_artifact_id} ({len(blob)} bytes)")

            out = decision.next_step(goal, hits, attached, history, mcp_tools)

            if out.is_answer:
                print(f"[decision]      ANSWER: {out.answer[:120]}...")
                history.append({
                    "iter": it, "kind": "answer",
                    "goal_id": goal.id, "text": out.answer,
                })
                continue

            tc = out.tool_call
            print(f"[decision]      TOOL_CALL: {tc.name}({tc.arguments})")

            # Validate arguments against tool schema before dispatching
            tool_schema = next((t for t in mcp_tools if t.name == tc.name), None)
            if tool_schema:
                try:
                    ActionRequest(tool_call=tc, tool_schema=tool_schema).validated()
                except ValueError as e:
                    err = str(e)
                    print(f"[validate]      BLOCKED: {err[:120]}")
                    memory.record_outcome(tool_call=tc, result_text=f"[blocked] {err}",
                                         artifact_id=None, run_id=run_id, goal_id=goal.id)
                    history.append({"iter": it, "kind": "action", "goal_id": goal.id,
                                    "tool": tc.name, "arguments": tc.arguments,
                                    "result_descriptor": f"[blocked] {err[:200]}", "artifact_id": None})
                    continue

            action_result = await action.execute(session, tc)
            print(f"[action]        → {action_result.descriptor[:120]}")

            memory.record_outcome(
                tool_call=tc,
                result_text=action_result.descriptor,
                artifact_id=action_result.artifact_id,
                run_id=run_id,
                goal_id=goal.id,
            )
            history.append({
                "iter": it, "kind": "action",
                "goal_id": goal.id,
                "tool": tc.name,
                "arguments": tc.arguments,
                "result_descriptor": action_result.descriptor[:300],
                "artifact_id": action_result.artifact_id,
            })
        else:
            print(f"\n[stopped] reached MAX_ITERATIONS={MAX_ITERATIONS}")

    final = _final_answer(history)
    print(f"\nFINAL: {final}\n")
    return final


def main() -> None:
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        asyncio.run(run(query))
    else:
        print("Single-agent scaffold REPL. Type 'exit' to quit.\n")
        while True:
            try:
                query = input("query> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not query or query.lower() in {"exit", "quit"}:
                break
            asyncio.run(run(query))


if __name__ == "__main__":
    main()
