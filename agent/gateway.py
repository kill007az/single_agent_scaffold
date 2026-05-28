"""Thin wrapper around the LLM Gateway V3 client with structured-output helpers."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

GATEWAY_URL = os.getenv("LLM_GATEWAY_V3_URL", "http://localhost:8101")
GATEWAY_DIR = Path(__file__).parent.parent / "llm_gatewayV3"
_gateway_proc: subprocess.Popen | None = None


def ensure_gateway() -> None:
    """Start the gateway process if it is not already running."""
    global _gateway_proc
    try:
        httpx.get(f"{GATEWAY_URL}/health", timeout=2)
        return
    except Exception:
        pass

    if not GATEWAY_DIR.exists():
        raise RuntimeError(
            f"llm_gatewayV3 directory not found at {GATEWAY_DIR}. "
            "Place the gateway source there before running the agent."
        )

    _gateway_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8101"],
        cwd=str(GATEWAY_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(20):
        time.sleep(0.5)
        try:
            httpx.get(f"{GATEWAY_URL}/health", timeout=2)
            return
        except Exception:
            continue
    raise RuntimeError("Gateway failed to start within 10 seconds.")


class GatewayClient:
    def __init__(self, base_url: str = GATEWAY_URL, timeout: float = 120):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def chat(
        self,
        *,
        prompt: str | None = None,
        messages: list[dict] | None = None,
        system: Any = None,
        provider: str | None = None,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        tools: list[dict] | None = None,
        tool_choice: Any = None,
        response_format: Any = None,
        auto_route: str | None = None,
    ) -> dict:
        body = {
            k: v for k, v in {
                "prompt": prompt,
                "messages": messages,
                "system": system,
                "provider": provider,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False,
                "tools": tools,
                "tool_choice": tool_choice,
                "response_format": response_format,
                "auto_route": auto_route,
            }.items() if v is not None
        }
        for attempt in range(3):
            r = httpx.post(f"{self.base_url}/v1/chat", json=body, timeout=self.timeout)
            if r.status_code in (429, 502, 503) and attempt < 2:
                import time
                wait = 10 * (attempt + 1)
                print(f"[gateway] HTTP {r.status_code} — retrying in {wait}s (attempt {attempt+1}/3)")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()  # final raise after exhausted retries
        return r.json()  # unreachable but satisfies type checkers

    def structured(
        self,
        *,
        prompt: str | None = None,
        messages: list[dict] | None = None,
        system: Any = None,
        schema: dict,
        schema_name: str = "out",
        provider: str | None = None,
        auto_route: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict:
        """Call the gateway expecting a JSON response conforming to `schema`."""
        response_format = {
            "type": "json_schema",
            "schema": schema,
            "name": schema_name,
            "strict": True,
        }
        resp = self.chat(
            prompt=prompt,
            messages=messages,
            system=system,
            provider=provider,
            auto_route=auto_route,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        text = resp.get("text", "")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(text[start:end])
            raise


gateway = GatewayClient()
