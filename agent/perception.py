"""Perception role — the orchestrator.

Runs every iteration. Decomposes the query into goals on the first pass,
then tracks done-flags and attaches artifacts for subsequent passes.

Pinned to Gemini (provider="g") for reliable structured output across iterations.
Temperature=1.0 prevents Gemini from looping at low temperature.

Goals use positional identity — the LLM emits artifact_index (int) rather than
a free-form artifact handle string, preventing hallucinated handles.
"""
from __future__ import annotations

import json

from . import prompt_store
from .gateway import gateway
from .schemas import Goal, MemoryItem, Observation

_SCHEMA = {
    "type": "object",
    "properties": {
        "goals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "done": {"type": "boolean"},
                    "artifact_index": {"type": "integer"},
                },
                "required": ["text", "done", "artifact_index"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["goals"],
    "additionalProperties": False,
}


def observe(
    query: str,
    hits: list[MemoryItem],
    history: list[dict],
    prior_goals: list[Goal],
    run_id: str,
) -> Observation:
    system = prompt_store.get("perception")

    # Build indexed list of artifact handles visible in memory hits
    artifact_index: list[str] = []
    hits_text_parts: list[str] = []
    for item in hits:
        entry = f"- [{item.kind}] {item.descriptor}"
        if item.artifact_id:
            idx = len(artifact_index)
            artifact_index.append(item.artifact_id)
            entry += f"  (artifact_index={idx}, id={item.artifact_id})"
        hits_text_parts.append(entry)
    hits_text = "\n".join(hits_text_parts) or "(none)"

    history_text = json.dumps(history[-10:], default=str, indent=2) if history else "(none)"

    prior_goals_text = (
        json.dumps([g.model_dump() for g in prior_goals], indent=2)
        if prior_goals else "(first iteration — decompose the query)"
    )

    prompt = (
        f"USER QUERY:\n{query}\n\n"
        f"MEMORY HITS:\n{hits_text}\n\n"
        f"HISTORY (last 10 events):\n{history_text}\n\n"
        f"PRIOR GOALS:\n{prior_goals_text}\n\n"
        "Return the updated goal list."
    )

    raw = gateway.structured(
        prompt=prompt,
        system=system,
        schema=_SCHEMA,
        schema_name="observation",
        provider="g",
        auto_route="perception",
        temperature=1.0,
        max_tokens=1024,
    )

    new_goals: list[Goal] = []
    for i, g in enumerate(raw["goals"]):
        # Preserve ids from prior goals using positional identity
        goal_id = prior_goals[i].id if i < len(prior_goals) else f"g{i}"

        # Map artifact_index back to real handle (-1 means no attachment)
        art_id: str | None = None
        idx = g.get("artifact_index", -1)
        if isinstance(idx, int) and idx >= 0 and idx < len(artifact_index):
            art_id = artifact_index[idx]

        new_goals.append(Goal(
            id=goal_id,
            text=g["text"],
            done=g["done"],
            attach_artifact_id=art_id,
        ))

    # Sticky-done: a goal marked done by a prior pass can never flip back
    for i, prior in enumerate(prior_goals):
        if prior.done and i < len(new_goals):
            new_goals[i].done = True

    # Force-attach safety net for synthesis goals with no explicit attachment
    _force_attach_synthesis(new_goals, hits, artifact_index)

    return Observation(goals=new_goals)


_SYNTHESIS_KEYWORDS = {"synthesise", "synthesize", "extract", "list", "compare",
                       "decide", "summarise", "summarize", "analyse", "analyze"}


def _force_attach_synthesis(
    goals: list[Goal],
    hits: list[MemoryItem],
    artifact_index: list[str],
) -> None:
    """Attach the most recent artifact to unattached synthesis goals."""
    if not artifact_index:
        return
    latest = artifact_index[-1]
    for goal in goals:
        if goal.done or goal.attach_artifact_id:
            continue
        if any(kw in goal.text.lower() for kw in _SYNTHESIS_KEYWORDS):
            goal.attach_artifact_id = latest
