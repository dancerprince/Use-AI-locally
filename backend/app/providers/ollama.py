"""Ollama native API provider (``/api/tags``, ``/api/chat``)."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .base import ModelProvider, PingResult, ProviderError, StreamEvent, ToolCall, ToolSpec


class OllamaProvider(ModelProvider):
    name = "ollama"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def ping(self) -> PingResult:
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.ping_timeout_s) as client:
                resp = await client.get(f"{self.base_url}/api/tags", headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            return PingResult(online=False, error=f"{type(exc).__name__}: {exc}"[:300])
        latency = round((time.perf_counter() - start) * 1000, 1)
        models = sorted(m.get("name", "") for m in data.get("models", []) if m.get("name"))
        return PingResult(online=True, latency_ms=latency, models=models)

    @staticmethod
    def _to_wire(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            msg: dict[str, Any] = {"role": m["role"], "content": m.get("content") or ""}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {"function": {"name": c["name"], "arguments": c["arguments"]}}
                    for c in m["tool_calls"]
                ]
            if m["role"] == "tool" and m.get("name"):
                msg["tool_name"] = m["name"]
            out.append(msg)
        return out

    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        temperature: float,
    ) -> AsyncIterator[StreamEvent]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._to_wire(messages),
            "stream": True,
            "options": {"temperature": temperature},
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        timeout = httpx.Timeout(self.timeout_s, connect=self.ping_timeout_s * 2)
        calls: list[ToolCall] = []
        try:
            async with (
                httpx.AsyncClient(timeout=timeout) as client,
                client.stream(
                    "POST", f"{self.base_url}/api/chat", json=payload, headers=self._headers()
                ) as resp,
            ):
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")[:500]
                    raise ProviderError(f"Ollama returned HTTP {resp.status_code}: {body}")
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise ProviderError(str(chunk["error"]))
                    msg = chunk.get("message") or {}
                    if msg.get("content"):
                        yield StreamEvent(type="delta", content=msg["content"])
                    for tc in msg.get("tool_calls") or []:
                        fn = tc.get("function") or {}
                        args = fn.get("arguments") or {}
                        if isinstance(args, str):
                            args = json.loads(args or "{}")
                        calls.append(
                            ToolCall(
                                id=uuid.uuid4().hex[:12], name=fn.get("name", ""), arguments=args
                            )
                        )
                    if chunk.get("done"):
                        break
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach Ollama at {self.base_url}: {exc}") from exc
        if calls:
            yield StreamEvent(type="tool_calls", tool_calls=calls)
