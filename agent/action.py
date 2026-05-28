"""Action role — pure MCP dispatch, no LLM call.

Receives a ToolCall and a live MCP ClientSession.
Returns (descriptor, artifact_id_or_None).

Two safety guards:
  1. Refuses any argument that begins with "art:" — artifact handles are not
     valid paths or URLs for MCP tools.
  2. Stores payloads larger than ARTIFACT_THRESHOLD_BYTES in the artifact store
     and returns a short descriptor instead of the raw bytes.
"""
from __future__ import annotations

from mcp import ClientSession

from .artifacts import ARTIFACT_THRESHOLD_BYTES, artifacts
from .schemas import ActionResult, ToolCall

_HANDLE_PREFIX = "art:"


async def execute(
    session: ClientSession,
    tool_call: ToolCall,
) -> ActionResult:
    # Guard: block artifact handles passed as tool arguments
    for key, val in tool_call.arguments.items():
        if isinstance(val, str) and val.startswith(_HANDLE_PREFIX):
            return ActionResult(
                descriptor=(
                    f"[error] argument '{key}' is an artifact handle ({val}), "
                    "not a valid path or URL. Read the bytes from ATTACHED ARTIFACTS instead."
                ),
                artifact_id=None,
            )

    result = await session.call_tool(tool_call.name, arguments=tool_call.arguments)

    # Collapse content blocks into a single text string
    text_parts: list[str] = []
    for block in result.content:
        if hasattr(block, "text"):
            text_parts.append(block.text)
        elif hasattr(block, "data"):
            text_parts.append(str(block.data))
        else:
            text_parts.append(str(block))
    raw_text = "\n".join(text_parts)
    raw_bytes = raw_text.encode("utf-8")

    if len(raw_bytes) > ARTIFACT_THRESHOLD_BYTES:
        art_id = artifacts.put(
            raw_bytes,
            content_type="text/plain",
            source=tool_call.name,
            descriptor=f"{tool_call.name} result ({len(raw_bytes)} bytes)",
        )
        preview = raw_text[:200].replace("\n", " ")
        descriptor = f"[artifact {art_id}, {len(raw_bytes)} bytes] preview: {preview}..."
        return ActionResult(descriptor=descriptor, artifact_id=art_id)

    return ActionResult(descriptor=raw_text, artifact_id=None)
