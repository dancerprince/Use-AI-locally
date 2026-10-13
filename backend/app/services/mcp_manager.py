"""Long-lived MCP client sessions with automatic reconnect.

Each server is owned by a dedicated asyncio task: the MCP SDK uses anyio task groups,
whose context managers must be entered and exited from the same task. The session object
itself can be safely used from other tasks for ``call_tool``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from ..config import Settings
from ..errors import AppError
from .tooling import exposed_name, to_text, truncate

log = logging.getLogger(__name__)


@dataclass
class McpTool:
    name: str
    exposed_name: str
    description: str | None
    input_schema: dict[str, Any]


@dataclass
class McpConfig:
    id: int
    name: str
    transport: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class _Conn:
    config: McpConfig
    status: str = "connecting"  # connecting | connected | error | stopped
    last_error: str | None = None
    tools: list[McpTool] = field(default_factory=list)
    session: Any = None
    task: asyncio.Task[None] | None = None
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    ready: asyncio.Event = field(default_factory=asyncio.Event)


def validate_stdio_command(command: str, allowed: list[str]) -> None:
    base = Path(command).name
    if base not in allowed:
        raise AppError(
            f"Command '{base}' is not in the stdio allow-list ({', '.join(allowed)}). "
            "Extend OAI_MCP_STDIO_ALLOWED_COMMANDS to permit it.",
            code="command_forbidden",
            status=403,
        )


class McpManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._conns: dict[int, _Conn] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ lifecycle
    async def start(self, cfg: McpConfig, *, wait: bool = True) -> None:
        async with self._lock:
            await self._stop_locked(cfg.id)
            conn = _Conn(config=cfg)
            conn.task = asyncio.create_task(self._run(conn), name=f"mcp:{cfg.name}")
            self._conns[cfg.id] = conn
        if wait:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(conn.ready.wait(), self._settings.mcp_connect_timeout_s + 2)

    async def stop(self, server_id: int) -> None:
        async with self._lock:
            await self._stop_locked(server_id)

    async def _stop_locked(self, server_id: int) -> None:
        conn = self._conns.pop(server_id, None)
        if conn and conn.task:
            conn.stop.set()
            try:
                await asyncio.wait_for(asyncio.shield(conn.task), 10)
            except (TimeoutError, asyncio.CancelledError, Exception):
                conn.task.cancel()
                with contextlib.suppress(BaseException):
                    await conn.task

    async def shutdown(self) -> None:
        for sid in list(self._conns):
            await self.stop(sid)

    # ------------------------------------------------------------------ worker
    async def _run(self, conn: _Conn) -> None:
        backoff = 1.0
        while not conn.stop.is_set():
            try:
                conn.status = "connecting"
                await self._session_loop(conn)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # anyio may raise ExceptionGroup
                msg = _describe(exc)
                log.warning("MCP server '%s' failed: %s", conn.config.name, msg)
                conn.status, conn.last_error, conn.session = "error", msg, None
                conn.ready.set()
            if conn.stop.is_set():
                break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(conn.stop.wait(), backoff)
            backoff = min(backoff * 2, 60.0)
        conn.status, conn.session = "stopped", None

    async def _session_loop(self, conn: _Conn) -> None:
        from mcp import ClientSession

        timeout = self._settings.mcp_connect_timeout_s
        async with contextlib.AsyncExitStack() as stack:
            read, write = await stack.enter_async_context(self._transport(conn.config))
            session = await stack.enter_async_context(
                ClientSession(
                    read,
                    write,
                    read_timeout_seconds=timedelta(seconds=self._settings.tool_timeout_s),
                )
            )
            await asyncio.wait_for(session.initialize(), timeout)
            listed = await asyncio.wait_for(session.list_tools(), timeout)
            conn.tools = [
                McpTool(
                    name=t.name,
                    exposed_name=exposed_name("mcp", conn.config.name, t.name),
                    description=t.description,
                    input_schema=t.inputSchema or {"type": "object", "properties": {}},
                )
                for t in listed.tools
            ]
            conn.session, conn.status, conn.last_error = session, "connected", None
            conn.ready.set()
            log.info("MCP server '%s' connected (%d tools)", conn.config.name, len(conn.tools))
            # Keep-alive: ping periodically so dead servers are detected and reconnected.
            while not conn.stop.is_set():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(conn.stop.wait(), 30)
                if not conn.stop.is_set():
                    await asyncio.wait_for(session.send_ping(), timeout)
        conn.session = None

    def _transport(self, cfg: McpConfig) -> Any:
        if cfg.transport == "stdio":
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            assert cfg.command
            validate_stdio_command(cfg.command, self._settings.mcp_stdio_allowed_commands)
            resolved = shutil.which(cfg.command) or cfg.command
            # Minimal inherited env + user-supplied values (avoid leaking our own secrets).
            base_env = {
                k: v
                for k, v in os.environ.items()
                if k in {"PATH", "HOME", "LANG", "TMPDIR", "USER", "SYSTEMROOT"}
            }
            params = StdioServerParameters(
                command=resolved, args=cfg.args, env={**base_env, **cfg.env}
            )
            return stdio_client(params)
        if cfg.transport == "sse":
            from mcp.client.sse import sse_client

            return sse_client(
                cfg.url or "",
                headers=cfg.headers or None,
                timeout=self._settings.mcp_connect_timeout_s,
            )
        if cfg.transport == "http":
            return _streamable_http(
                cfg.url or "", cfg.headers, self._settings.mcp_connect_timeout_s
            )
        raise AppError(f"Unsupported transport '{cfg.transport}'")

    # ------------------------------------------------------------------ queries
    def status(self, server_id: int) -> tuple[str, str | None, list[McpTool]]:
        conn = self._conns.get(server_id)
        if not conn:
            return "stopped", None, []
        return conn.status, conn.last_error, list(conn.tools)

    def all_tools(self) -> list[tuple[str, McpTool]]:
        return [
            (c.config.name, t)
            for c in self._conns.values()
            if c.status == "connected"
            for t in c.tools
        ]

    async def call_tool(self, exposed: str, arguments: dict[str, Any]) -> str:
        for conn in self._conns.values():
            for tool in conn.tools:
                if tool.exposed_name == exposed:
                    if conn.session is None:
                        raise AppError(f"MCP server '{conn.config.name}' is not connected")
                    result = await asyncio.wait_for(
                        conn.session.call_tool(tool.name, arguments), self._settings.tool_timeout_s
                    )
                    parts = []
                    for item in result.content:
                        text = getattr(item, "text", None)
                        parts.append(
                            text
                            if text is not None
                            else to_text(item.model_dump(exclude_none=True))
                        )
                    text = "\n".join(parts) or to_text(
                        getattr(result, "structuredContent", None) or ""
                    )
                    if result.isError:
                        text = f"[tool error] {text}"
                    return truncate(text, self._settings.tool_result_max_chars)
        raise AppError(f"Unknown MCP tool '{exposed}'", code="not_found", status=404)


@contextlib.asynccontextmanager
async def _streamable_http(
    url: str, headers: dict[str, str], connect_timeout_s: float
) -> AsyncIterator[tuple[Any, Any]]:
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url, headers=headers or None, timeout=connect_timeout_s) as (
        read,
        write,
        _sid,
    ):
        yield read, write


def _describe(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(_describe(e) for e in exc.exceptions)
    if isinstance(exc, TimeoutError):
        return "Timed out while connecting"
    return f"{type(exc).__name__}: {exc}"[:500]
