"""Typed memory service.

Four kinds: fact, preference, tool_outcome, scratchpad.

Reads are pure keyword search (no LLM cost).
Writes for free-form text call the gateway for classification (one LLM call).
Writes for tool outcomes are zero-cost — kind is known by construction.

State persists to state/memory.json and survives across runs.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from .gateway import gateway
from .schemas import MemoryItem, ToolCall

MEMORY_PATH = Path(__file__).parent.parent / "state" / "memory.json"
MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)

_STOPWORDS = {
    "a", "an", "the", "is", "it", "in", "on", "at", "to", "and", "or",
    "of", "for", "with", "this", "that", "was", "be", "are", "i", "me",
    "my", "you", "we", "they", "from", "by", "as", "do", "did", "has",
    "have", "had", "can", "will", "would", "could", "should", "may",
}

_CLASSIFY_SYSTEM = (
    "You are a memory classifier. Given a raw text snippet, extract structured "
    "memory fields and return them as JSON matching the given schema exactly.\n\n"
    "kind must be one of: fact, preference, tool_outcome, scratchpad.\n"
    "keywords: 3-8 lowercase tokens that summarise the content (exclude stopwords).\n"
    "descriptor: one short human-readable line.\n"
    "value: a dict with the structured payload — at minimum {\"raw\": <the text>}.\n"
    "confidence: 0.0-1.0 reflecting certainty."
)

_CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["fact", "preference", "tool_outcome", "scratchpad"]},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "descriptor": {"type": "string"},
        "value": {"type": "object"},
        "confidence": {"type": "number"},
    },
    "required": ["kind", "keywords", "descriptor", "value", "confidence"],
    "additionalProperties": False,
}


class MemoryService:
    def __init__(self, path: Path = MEMORY_PATH):
        self._path = path
        self._items: list[MemoryItem] = self._load()

    # ------------------------------------------------------------------ reads

    def read(
        self,
        query: str,
        history: list[dict] | None = None,
        kinds: list[str] | None = None,
        top_k: int = 8,
    ) -> list[MemoryItem]:
        """Keyword search over memory items. No LLM call."""
        tokens = self._tokenise(query)
        if history:
            for event in history[-6:]:
                tokens |= self._tokenise(str(event))

        candidates = [
            item for item in self._items
            if kinds is None or item.kind in kinds
        ]

        def score(item: MemoryItem) -> int:
            item_tokens = set(item.keywords) | self._tokenise(item.descriptor)
            return len(tokens & item_tokens)

        ranked = sorted(candidates, key=score, reverse=True)
        return [r for r in ranked[:top_k] if score(r) > 0] or ranked[:top_k]

    def filter(
        self,
        kinds: list[str] | None = None,
        goal_id: str | None = None,
        recent: int | None = None,
    ) -> list[MemoryItem]:
        results = self._items
        if kinds:
            results = [i for i in results if i.kind in kinds]
        if goal_id:
            results = [i for i in results if i.goal_id == goal_id]
        if recent:
            results = results[-recent:]
        return results

    # ----------------------------------------------------------------- writes

    def remember(
        self,
        raw_text: str,
        source: str,
        run_id: str,
        goal_id: str | None = None,
    ) -> MemoryItem:
        """Classify raw text and persist as a typed MemoryItem (one gateway call)."""
        classified = gateway.structured(
            prompt=f"Classify and extract this text into memory:\n\n{raw_text}",
            system=_CLASSIFY_SYSTEM,
            schema=_CLASSIFY_SCHEMA,
            schema_name="memory_item",
            auto_route="memory",
            provider="g",
            temperature=0.3,
        )
        item = MemoryItem(
            id=uuid.uuid4().hex[:12],
            kind=classified["kind"],
            keywords=classified["keywords"],
            descriptor=classified["descriptor"],
            value=classified["value"],
            confidence=classified.get("confidence", 1.0),
            source=source,
            run_id=run_id,
            goal_id=goal_id,
            created_at=datetime.utcnow(),
        )
        self._items.append(item)
        self._save()
        return item

    def record_outcome(
        self,
        tool_call: ToolCall,
        result_text: str,
        artifact_id: str | None,
        run_id: str,
        goal_id: str | None = None,
    ) -> MemoryItem:
        """Record an MCP dispatch result as a tool_outcome (no LLM call)."""
        keywords = [tool_call.name] + [
            str(v)[:30].lower()
            for v in tool_call.arguments.values()
            if isinstance(v, str)
        ]
        item = MemoryItem(
            id=uuid.uuid4().hex[:12],
            kind="tool_outcome",
            keywords=keywords[:8],
            descriptor=f"{tool_call.name}({tool_call.arguments}) → {result_text[:80]}",
            value={"tool": tool_call.name, "arguments": tool_call.arguments, "result": result_text[:200]},
            artifact_id=artifact_id,
            source="action",
            run_id=run_id,
            goal_id=goal_id,
            created_at=datetime.utcnow(),
        )
        self._items.append(item)
        self._save()
        return item

    # -------------------------------------------------------------- internals

    def _tokenise(self, text: str) -> set[str]:
        return {
            w.lower().strip(".,!?\"'")
            for w in text.split()
            if w.lower() not in _STOPWORDS and len(w) > 2
        }

    def _load(self) -> list[MemoryItem]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return [MemoryItem.model_validate(r) for r in raw]
        except Exception:
            return []

    def _save(self) -> None:
        data = [item.model_dump(mode="json") for item in self._items]
        self._path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


memory = MemoryService()
