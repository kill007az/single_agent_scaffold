"""MCP server for the single-agent scaffold.

Built-in tools (no extra dependencies):
    ping, get_time, currency_convert,
    read_file, list_dir, create_file, update_file, edit_file

Optional tools (install with: uv add --optional mcp-tools):
    web_search  — Tavily primary, DuckDuckGo fallback
    fetch_url   — clean markdown via crawl4ai / headless Chromium

Run modes:
    uv run mcp_server/server.py              # stdio (used by agent.py)
    uv run mcp_server/server.py --http 8200  # HTTP+SSE for standalone testing

Add domain-specific tools below using @mcp.tool().
The function docstring becomes the tool description visible to Decision.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).parent.parent / ".env")

SANDBOX = Path(__file__).parent.parent / "sandbox"
SANDBOX.mkdir(exist_ok=True)

USAGE_PATH = Path(__file__).parent.parent / "state" / "search_usage.json"
MONTHLY_CAP = 950
MAX_SEARCH_RESULTS = 5
_usage_lock = threading.Lock()

mcp = FastMCP("scaffold-mcp-server")


# ---------------------------------------------------------------------------
# Sandbox path guard
# ---------------------------------------------------------------------------

def _safe(path: str) -> Path:
    resolved = (SANDBOX / path).resolve()
    base = SANDBOX.resolve()
    if resolved != base and base not in resolved.parents:
        raise ValueError(f"Path '{path}' escapes the sandbox")
    return resolved


# ---------------------------------------------------------------------------
# Search usage tracking (Tavily has a monthly quota)
# ---------------------------------------------------------------------------

def _empty_usage(month: str) -> dict:
    return {"month": month, "tavily": {"count": 0, "errors": 0}, "duckduckgo": {"count": 0, "errors": 0}}


def _load_usage() -> dict:
    month = datetime.now().strftime("%Y-%m")
    if not USAGE_PATH.exists():
        return _empty_usage(month)
    try:
        data = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_usage(month)
    return data if data.get("month") == month else _empty_usage(month)


def _bump(provider: str, field: str = "count") -> None:
    with _usage_lock:
        data = _load_usage()
        data[provider][field] = data[provider].get(field, 0) + 1
        USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        USAGE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _under_cap(provider: str) -> bool:
    return _load_usage()[provider]["count"] < MONTHLY_CAP


# ---------------------------------------------------------------------------
# Core tools — always available
# ---------------------------------------------------------------------------

@mcp.tool()
def ping() -> dict:
    """Health-check. Returns server status. Example: ping()."""
    return {"status": "ok", "server": "scaffold-mcp-server"}


@mcp.tool()
def get_time(timezone: str = "UTC") -> dict:
    """Current time in a named IANA timezone. Example: get_time("Asia/Tokyo")."""
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    offset = now.utcoffset()
    return {
        "iso": now.isoformat(),
        "human": now.strftime("%A, %d %B %Y %H:%M:%S %Z"),
        "timezone": timezone,
        "offset_hours": offset.total_seconds() / 3600 if offset else 0.0,
    }


@mcp.tool()
def currency_convert(amount: float, from_currency: str, to_currency: str) -> dict:
    """Convert money between ISO-3 currencies via frankfurter.dev. Example: currency_convert(100, "USD", "JPY")."""
    f, t = from_currency.upper(), to_currency.upper()
    url = f"https://api.frankfurter.dev/v1/latest?amount={amount}&base={f}&symbols={t}"
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        data = r.json()
    converted = data["rates"][t]
    return {
        "amount": amount, "from": f, "to": t,
        "rate": round(converted / amount, 6) if amount else 0.0,
        "converted": converted,
        "date": data["date"],
        "source": "frankfurter.dev",
    }


@mcp.tool()
def read_file(path: str) -> dict:
    """Read a UTF-8 text file from the sandbox. Example: read_file("notes.txt")."""
    p = _safe(path)
    if not p.exists():
        raise FileNotFoundError(f"File '{path}' does not exist in sandbox")
    text = p.read_text(encoding="utf-8")
    return {"path": path, "size_bytes": p.stat().st_size, "content": text}


@mcp.tool()
def list_dir(path: str = ".") -> list[dict]:
    """List files and directories in the sandbox. Example: list_dir(".")."""
    p = _safe(path)
    if not p.exists():
        raise FileNotFoundError(f"Directory '{path}' does not exist in sandbox")
    return [
        {"name": c.name, "type": "dir" if c.is_dir() else "file",
         "size_bytes": 0 if c.is_dir() else c.stat().st_size}
        for c in sorted(p.iterdir())
    ]


@mcp.tool()
def create_file(path: str, content: str) -> dict:
    """Create a new file in the sandbox; errors if it already exists. Example: create_file("out.txt", "hello")."""
    p = _safe(path)
    if p.exists():
        raise ValueError(f"File '{path}' already exists — use update_file to overwrite")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": path, "size_bytes": p.stat().st_size}


@mcp.tool()
def update_file(path: str, content: str) -> dict:
    """Overwrite an existing sandbox file. Example: update_file("out.txt", "new content")."""
    p = _safe(path)
    if not p.exists():
        raise FileNotFoundError(f"File '{path}' does not exist — use create_file first")
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": path, "size_bytes": p.stat().st_size}


@mcp.tool()
def edit_file(path: str, find: str, replace: str, replace_all: bool = False) -> dict:
    """Find-and-replace inside a sandbox file. Example: edit_file("out.txt", "foo", "bar")."""
    p = _safe(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(find)
    if count == 0:
        raise ValueError(f"'{find}' not found in '{path}'")
    if count > 1 and not replace_all:
        raise ValueError(f"'{find}' appears {count} times — pass replace_all=True to replace all")
    new_text = text.replace(find, replace) if replace_all else text.replace(find, replace, 1)
    p.write_text(new_text, encoding="utf-8")
    return {"ok": True, "path": path, "replacements": count if replace_all else 1}


# ---------------------------------------------------------------------------
# Optional tools — require: uv add --optional mcp-tools
# ---------------------------------------------------------------------------

@mcp.tool()
def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web (Tavily primary, DuckDuckGo fallback). Requires mcp-tools optional deps. Example: web_search("python asyncio best practices", 3)."""
    max_results = max(1, min(max_results, MAX_SEARCH_RESULTS))

    if os.environ.get("TAVILY_API_KEY") and _under_cap("tavily"):
        try:
            from tavily import TavilyClient
            client = TavilyClient(os.environ["TAVILY_API_KEY"])
            resp = client.search(query=query, max_results=max_results, search_depth="advanced")
            results = [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")} for r in resp.get("results", [])]
            if results:
                _bump("tavily")
                return results
        except ImportError:
            pass
        except Exception:
            _bump("tavily", "errors")

    try:
        from ddgs import DDGS
        hits: list[dict] = []
        with DDGS() as ddgs:
            for backend in ("auto", "html", "lite"):
                try:
                    hits = list(ddgs.text(query, max_results=max_results, backend=backend))
                except Exception:
                    hits = []
                if hits:
                    break
        _bump("duckduckgo")
        return [{"title": h.get("title", ""), "url": h.get("href", ""), "snippet": h.get("body", "")} for h in hits]
    except ImportError:
        raise RuntimeError("web_search requires ddgs: run 'uv add --optional mcp-tools'")


@mcp.tool()
async def fetch_url(url: str) -> dict:
    """Fetch clean markdown from a URL via crawl4ai. Requires mcp-tools optional deps. Example: fetch_url("https://example.com")."""
    try:
        from crawl4ai import AsyncWebCrawler
    except ImportError:
        raise RuntimeError("fetch_url requires crawl4ai: run 'uv add --optional mcp-tools'")

    saved_fd = os.dup(1)
    os.dup2(2, 1)
    try:
        async with AsyncWebCrawler(verbose=False) as crawler:
            r = await crawler.arun(url=url)
    finally:
        os.dup2(saved_fd, 1)
        os.close(saved_fd)

    md = r.markdown
    raw = getattr(md, "raw_markdown", None) or getattr(md, "fit_markdown", None) or md or r.cleaned_html or ""
    text = str(raw)
    return {"status": int(getattr(r, "status_code", None) or 200), "content_type": "text/markdown", "length_bytes": len(text.encode()), "text": text}


# ---------------------------------------------------------------------------
# Add your domain-specific tools here
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scaffold MCP server")
    parser.add_argument("--http", type=int, metavar="PORT", help="Serve over HTTP+SSE instead of stdio")
    args = parser.parse_args()
    mcp.run(transport="sse" if args.http else "stdio",
            **{"host": "127.0.0.1", "port": args.http} if args.http else {})
