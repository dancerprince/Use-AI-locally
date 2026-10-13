"""OpenAI-compatible provider (LM Studio, llama.cpp server, vLLM, LocalAI, Jan ...)."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .base import ModelProvider, PingResult, ProviderError, StreamEvent, ToolCall, ToolSpec


class OpenAICompatProvider(ModelProvider):
    name = "openai"

    @property
    def _api(self) -> str:
        return self.base_url if self.base_url.endswith("/v1") else f"{self.base_url}/v1"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def ping(self) -> PingResult:
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.ping_timeout_s) as client:
                resp = await client.get(f"{self._api}/models", headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            return PingResult(online=False, error=f"{type(exc).__name__}: {exc}"[:300])
        latency = round((time.perf_counter() - start) * 1000, 1)
        models = sorted(m.get("id", "") for m in data.get("data", []) if m.get("id"))
        return PingResult(online=True, latency_ms=latency, models=models)

    @staticmethod
    def _to_wire(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            msg: dict[str, Any] = {"role": m["role"], "content": m.get("content") or ""}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])},
                    }
                    for c in m["tool_calls"]
                ]
            if m["role"] == "tool":
                msg["tool_call_id"] = m.get("tool_call_id")
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
            "temperature": temperature,
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
        partial: dict[int, dict[str, str]] = {}
        try:
            async with (
                httpx.AsyncClient(timeout=timeout) as client,
                client.stream(
                    "POST", f"{self._api}/chat/completions", json=payload, headers=self._headers()
                ) as resp,
            ):
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")[:500]
                    raise ProviderError(f"Model server returned HTTP {resp.status_code}: {body}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            yield StreamEvent(type="delta", content=delta["content"])
                        for tc in delta.get("tool_calls") or []:
                            slot = partial.setdefault(
                                tc.get("index", 0), {"id": "", "name": "", "args": ""}
                            )
                            slot["id"] = tc.get("id") or slot["id"]
                            fn = tc.get("function") or {}
                            slot["name"] += fn.get("name") or ""
                            slot["args"] += fn.get("arguments") or ""
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach model server at {self.base_url}: {exc}") from exc
        if partial:
            calls = []
            for idx, slot in sorted(partial.items()):
                try:
                    args = json.loads(slot["args"] or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": slot["args"]}
                calls.append(
                    ToolCall(id=slot["id"] or f"call_{idx}", name=slot["name"], arguments=args)
                )
            yield StreamEvent(type="tool_calls", tool_calls=calls)
