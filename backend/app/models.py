"""Persistent tables. Secrets are stored only in ``*_enc`` (encrypted) columns."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin(SQLModel):
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class McpServer(TimestampMixin, table=True):
    __tablename__ = "mcp_servers"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, max_length=64)
    transport: str = Field(max_length=16)  # stdio | sse | http
    command: str | None = None
    args: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    url: str | None = None
    secrets_enc: str | None = Field(
        default=None, sa_column=Column(Text)
    )  # {"env":{}, "headers":{}}
    enabled: bool = True


class Connector(TimestampMixin, table=True):
    __tablename__ = "connectors"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, max_length=64)
    type: str = Field(max_length=32)
    config_enc: str = Field(sa_column=Column(Text, nullable=False))
    enabled: bool = True


class Skill(TimestampMixin, table=True):
    __tablename__ = "skills"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, max_length=64)
    description: str = ""
    instructions: str = Field(default="", sa_column=Column(Text, nullable=False))
    tools: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    enabled: bool = True


class ChatSession(TimestampMixin, table=True):
    __tablename__ = "chat_sessions"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    title: str = "New chat"
    model: str | None = None


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="chat_sessions.id", index=True, ondelete="CASCADE")
    role: str
    content: str = Field(default="", sa_column=Column(Text, nullable=False))
    tool_calls: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))
    tool_call_id: str | None = None
    name: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_settings"

    key: str = Field(primary_key=True)
    value: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
