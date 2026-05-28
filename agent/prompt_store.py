"""Prompt store: load, cache, and hot-reload system prompts from the prompts/ directory.

Prompts are plain .txt files. The store resolves them by name (filename without extension).
At runtime, prompts are read fresh on first access and cached until invalidated.
Use `reload()` to force a re-read of all prompts (useful during development).

To add a new prompt: drop a .txt file into the prompts/ directory and call
`prompt_store.get("your_filename_without_ext")`.
"""
from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_cache: dict[str, str] = {}


def get(name: str) -> str:
    """Return the prompt text for `name`. Raises FileNotFoundError if missing."""
    if name not in _cache:
        _cache[name] = _load(name)
    return _cache[name]


def reload(name: str | None = None) -> None:
    """Invalidate cache for `name` (or all prompts if None)."""
    if name is None:
        _cache.clear()
    else:
        _cache.pop(name, None)


def set_override(name: str, text: str) -> None:
    """Override a prompt in memory without touching disk (useful for tests)."""
    _cache[name] = text


def list_prompts() -> list[str]:
    """Return names of all .txt files in the prompts directory."""
    return [p.stem for p in sorted(PROMPTS_DIR.glob("*.txt"))]


def _load(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt '{name}' not found at {path}. "
            f"Available: {list_prompts()}"
        )
    return path.read_text(encoding="utf-8").strip()
