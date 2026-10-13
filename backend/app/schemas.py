"""Request/response DTOs. Validation lives here; secrets are never echoed back in clear."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

# Names become part of tool identifiers (``mcp__<name>__<tool>``), so keep them strict.
NAME_RE = r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$"
Name = Annotated[str, StringConstraints(pattern=NAME_RE, strip_whitespace=True)]
KV = dict[
    Annotated[str, StringConstraints(min_length=1, max_length=128)],
    Annotated[str, StringConstraints(max_length=4096)],
]
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- health / models
class ModelHealth(BaseModel):
    online: bool
    provider: str
    base_url: str
    latency_ms: float | None = None
    models: list[str] = []
    error: str | None = None


class ModelSettings(Strict):
    provider: Literal["ollama", "openai"] = "ollama"
    base_url: Annotated[str, StringConstraints(max_length=512)] = "http://localhost:11434"
    api_key: str | None = Field(default=None, max_length=512)
    default_model: str | None = Field(default=None, max_length=256)
    temperature: float = Field(0.7, ge=0, le=2)
    system_prompt: str = Field("You are a helpful local AI assistant.", max_length=16_000)

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return v.rstrip("/")


# ---------------------------------------------------------------- MCP servers
Transport = Literal["stdio", "sse", "http"]


class McpServerIn(Strict):
    name: Name
    transport: Transport
    command: str | None = Field(default=None, max_length=256)
    args: list[Annotated[str, StringConstraints(max_length=1024)]] = Field(
        default_factory=list, max_length=64
    )
    env: KV = Field(default_factory=dict)
    url: str | None = Field(default=None, max_length=2048)
    headers: KV = Field(default_factory=dict)
    enabled: bool = True
    # Explicit acknowledgement that a local command will be executed (stdio only).
    confirmed: bool = False

    @model_validator(mode="after")
    def _check_transport(self) -> McpServerIn:
        if self.transport == "stdio":
            if not self.command:
                raise ValueError("command is required for stdio transport")
            if any(not ENV_KEY_RE.match(k) for k in self.env):
                raise ValueError("env keys must be valid environment variable names")
        else:
            if not self.url or not self.url.startswith(("http://", "https://")):
                raise ValueError("an http(s) url is required for sse/http transport")
        return self


class McpToolOut(BaseModel):
    name: str
    exposed_name: str
    description: str | None = None
    input_schema: dict[str, Any] = {}


class McpServerOut(BaseModel):
    id: int
    name: str
    transport: Transport
    command: str | None
    args: list[str]
    env: dict[str, str]
    url: str | None
    headers: dict[str, str]
    enabled: bool
    status: str
    last_error: str | None
    tools: list[McpToolOut]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- connectors
ConnectorType = Literal["http", "filesystem", "sqlite", "postgres", "webhook"]


class ConnectorIn(Strict):
    name: Name
    type: ConnectorType
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ConnectorOut(BaseModel):
    id: int
    name: str
    type: ConnectorType
    config: dict[str, Any]
    enabled: bool
    tools: list[str]
    created_at: datetime
    updated_at: datetime


class TestResult(BaseModel):
    ok: bool
    message: str
    details: Any = None


# ---------------------------------------------------------------- skills
class SkillIn(Strict):
    name: Name
    description: str = Field("", max_length=500)
    instructions: str = Field("", max_length=32_000)
    tools: list[Annotated[str, StringConstraints(max_length=128)]] = Field(
        default_factory=list, max_length=100
    )
    enabled: bool = True


class SkillOut(SkillIn):
    model_config = ConfigDict(extra="ignore")
    id: int
    created_at: datetime
    updated_at: datetime


class ToggleIn(Strict):
    enabled: bool


# ---------------------------------------------------------------- chat
class ChatRequest(Strict):
    session_id: str | None = Field(default=None, max_length=64)
    message: str = Field(min_length=1)
    model: str | None = Field(default=None, max_length=256)
    skill_ids: list[int] | None = None  # None => all enabled skills
    use_tools: bool = True


class ChatSessionOut(BaseModel):
    id: str
    title: str
    model: str | None
    created_at: datetime
    updated_at: datetime


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None
    tool_call_id: str | None
    name: str | None
    created_at: datetime


class ToolInfo(BaseModel):
    name: str
    source: str
    description: str | None = None
