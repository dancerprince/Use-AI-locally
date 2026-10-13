"""Model-provider abstraction. Messages use a normalised OpenAI-like shape:

``{"role", "content", "tool_calls"?: [{"id","name","arguments": dict}], "tool_call_id"?, "name"?}``
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class StreamEvent:
    """``type`` is ``delta`` (text chunk) or ``tool_calls`` (complete calls)."""

    type: str
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class PingResult:
    online: bool
    latency_ms: float | None = None
    models: list[str] = field(default_factory=list)
    error: str | None = None


class ProviderError(Exception):
    pass


class ModelProvider(abc.ABC):
    name: str

    def __init__(
        self, base_url: str, *, api_key: str | None, timeout_s: float, ping_timeout_s: float
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.ping_timeout_s = ping_timeout_s

    @abc.abstractmethod
    async def ping(self) -> PingResult: ...

    @abc.abstractmethod
    def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        temperature: float,
    ) -> AsyncIterator[StreamEvent]: ...
