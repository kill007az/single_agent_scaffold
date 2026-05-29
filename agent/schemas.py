"""Pydantic contracts for all role boundaries in the agent scaffold."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ── MCP tool return types ─────────────────────────────────────────────────────

class SearchResultItem(BaseModel):
    title: str
    url: str
    snippet: str


class FetchResult(BaseModel):
    status: int
    content_type: str
    length_bytes: int
    text: str


class TimeResult(BaseModel):
    iso: str
    human: str
    timezone: str
    offset_hours: float


class CurrencyResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    amount: float
    from_currency: str = Field(alias="from")
    to_currency: str = Field(alias="to")
    rate: float
    converted: float
    date: str
    source: str


class ReadFileResult(BaseModel):
    path: str
    size_bytes: int
    content: str
    encoding: str


class DirEntry(BaseModel):
    name: str
    type: str
    size_bytes: int


class FileWriteResult(BaseModel):
    ok: bool
    path: str
    size_bytes: int


class EditFileResult(BaseModel):
    ok: bool
    path: str
    replacements: int
    size_bytes: int


class MemoryItem(BaseModel):
    id: str
    kind: Literal["fact", "preference", "tool_outcome", "scratchpad"]
    keywords: list[str]
    descriptor: str
    value: dict[str, Any]
    artifact_id: str | None = None
    source: str
    run_id: str
    goal_id: str | None = None
    confidence: float = 1.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Artifact(BaseModel):
    id: str
    content_type: str
    size_bytes: int
    source: str
    descriptor: str


class Goal(BaseModel):
    id: str
    text: str
    done: bool = False
    attach_artifact_id: str | None = None


class Observation(BaseModel):
    goals: list[Goal]

    @property
    def all_done(self) -> bool:
        return all(g.done for g in self.goals)

    def next_unfinished(self) -> Goal | None:
        return next((g for g in self.goals if not g.done), None)


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class DecisionOutput(BaseModel):
    answer: str | None = None
    tool_call: ToolCall | None = None

    @model_validator(mode="after")
    def _one_of(self) -> "DecisionOutput":
        if self.answer is None and self.tool_call is None:
            raise ValueError("DecisionOutput must have either 'answer' or 'tool_call'")
        if self.answer is not None and self.tool_call is not None:
            raise ValueError("DecisionOutput must not have both 'answer' and 'tool_call'")
        return self

    @property
    def is_answer(self) -> bool:
        return self.answer is not None


class ActionResult(BaseModel):
    """Typed return value from Action.execute — the boundary between Action and the loop."""
    descriptor: str
    artifact_id: str | None = None


class MCPTool(BaseModel):
    """A single MCP tool as presented to Decision."""
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ActionRequest(BaseModel):
    """Validated pairing of a ToolCall with its MCPTool schema.

    Validates that tool_call.arguments satisfies the tool's input_schema
    (required fields present, no art: handles) before Action dispatches.
    Raises ValueError on violations so the loop records the error without
    hitting the MCP server.
    """
    tool_call: ToolCall
    tool_schema: MCPTool

    def validated(self) -> "ActionRequest":
        import jsonschema

        schema = self.tool_schema.input_schema
        required = set(schema.get("required", []))
        missing = required - set(self.tool_call.arguments.keys())
        if missing:
            raise ValueError(
                f"Tool '{self.tool_call.name}' missing required argument(s): "
                f"{sorted(missing)}. Got: {self.tool_call.arguments}"
            )

        for key, val in self.tool_call.arguments.items():
            if isinstance(val, str) and val.startswith("art:"):
                raise ValueError(
                    f"Tool argument '{key}' is an artifact handle ({val}), "
                    "not a valid value. Read bytes from ATTACHED ARTIFACTS instead."
                )

        try:
            jsonschema.validate(self.tool_call.arguments, schema)
        except jsonschema.ValidationError as e:
            raise ValueError(f"Tool argument validation failed: {e.message}") from e

        return self
