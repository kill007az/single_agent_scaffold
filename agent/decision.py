"""Decision role — selects the next action for one bounded goal.

Returns either a final answer (plain text) or a single ToolCall.
Never returns both. Never narrates.

Uses native gateway tool calling (tools=, tool_choice="auto") so the model
properly populates all required arguments. Parses resp["tool_calls"] for
tool dispatch and resp["text"] for direct answers.
"""
from __future__ import annotations

import json

from . import prompt_store
from .gateway import gateway
from .schemas import DecisionOutput, Goal, MCPTool, MemoryItem, ToolCall


def next_step(
    goal: Goal,
    hits: list[MemoryItem],
    attached: list[tuple[str, bytes]],
    history: list[dict],
    mcp_tools: list[MCPTool],
) -> DecisionOutput:
    system = prompt_store.get("decision")

    hits_text = "\n".join(
        f"- [{h.kind}] {h.descriptor}" for h in hits
    ) or "(none)"

    history_text = json.dumps(history[-6:], default=str, indent=2) if history else "(none)"

    attached_section = ""
    if attached:
        parts = []
        for art_id, blob in attached:
            try:
                text = blob.decode("utf-8", errors="replace")
            except Exception:
                text = f"<binary {len(blob)} bytes>"
            parts.append(f"--- {art_id} ({len(blob)} bytes) ---\n{text[:8000]}")
        attached_section = "\n\nATTACHED ARTIFACTS:\n" + "\n\n".join(parts)

    prompt = (
        f"CURRENT GOAL:\n{goal.text}\n\n"
        f"MEMORY HITS:\n{hits_text}\n\n"
        f"RECENT HISTORY:\n{history_text}"
        f"{attached_section}\n\n"
        "Either call a tool to progress toward the goal, or answer directly if you already have enough information."
    )

    gateway_tools = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in mcp_tools
    ]

    resp = gateway.chat(
        prompt=prompt,
        system=system,
        tools=gateway_tools if gateway_tools else None,
        tool_choice="auto" if gateway_tools else None,
        auto_route="decision",
        temperature=0.7,
        max_tokens=2048,
    )

    tool_calls = resp.get("tool_calls") or []
    if tool_calls:
        tc = tool_calls[0]
        return DecisionOutput(tool_call=ToolCall(
            name=tc.get("name", ""),
            arguments=tc.get("arguments") or tc.get("input") or {},
        ))

    answer = (resp.get("text") or "").strip()
    return DecisionOutput(answer=answer or "(no response)")
