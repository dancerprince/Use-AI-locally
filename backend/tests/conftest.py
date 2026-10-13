from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers import ModelProvider, PingResult, StreamEvent, ToolCall, ToolSpec


class FakeProvider(ModelProvider):
    """Scripted provider: each entry in ``script`` is one model turn."""

    name = "fake"

    def __init__(self, script: list[dict[str, Any]] | None = None, online: bool = True) -> None:
        super().__init__("http://fake", api_key=None, timeout_s=5, ping_timeout_s=1)
        self.script = list(script or [])
        self.online = online
        self.calls: list[dict[str, Any]] = []

    async def ping(self) -> PingResult:
        if not self.online:
            return PingResult(online=False, error="ConnectError: refused")
        return PingResult(online=True, latency_ms=1.2, models=["llama3.1:8b", "qwen2.5:7b"])

    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        temperature: float,
    ) -> AsyncIterator[StreamEvent]:
        self.calls.append({"model": model, "messages": messages, "tools": [t.name for t in tools]})
        turn = self.script.pop(0) if self.script else {"text": "done"}
        if turn.get("text"):
            for word in turn["text"].split(" "):
                yield StreamEvent(type="delta", content=word + " ")
        if turn.get("calls"):
            yield StreamEvent(
                type="tool_calls",
                tool_calls=[
                    ToolCall(id=f"c{i}", name=n, arguments=a)
                    for i, (n, a) in enumerate(turn["calls"])
                ],
            )


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        default_model="llama3.1:8b",
        max_tool_rounds=3,
        manage_runtime=False,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake_provider(client: TestClient, monkeypatch) -> FakeProvider:
    fp = FakeProvider()
    store = client.app.state.oai.store
    monkeypatch.setattr(store, "provider", lambda *_a, **_k: fp)
    return fp


def parse_sse(text: str) -> list[tuple[str, Any]]:
    import json

    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events
