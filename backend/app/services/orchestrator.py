"""Chat orchestration: skills → system prompt, tool gathering, bounded tool-calling loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from ..config import Settings
from ..errors import AppError
from ..models import ChatMessage, ChatSession, Skill, utcnow
from ..providers import ModelProvider, ProviderError, ToolCall, ToolSpec
from .connectors import ConnectorAdapter
from .mcp_manager import McpManager

log = logging.getLogger(__name__)
HISTORY_LIMIT = 60


@dataclass
class ToolRegistry:
    specs: list[ToolSpec]
    sources: dict[str, str]  # exposed name -> "mcp:<server>" | "conn:<name>"
    connectors: dict[str, tuple[ConnectorAdapter, str]]  # exposed -> (adapter, local tool)
    mcp: McpManager

    @classmethod
    def build(cls, mcp: McpManager, adapters: list[ConnectorAdapter]) -> ToolRegistry:
        specs: list[ToolSpec] = []
        sources: dict[str, str] = {}
        conns: dict[str, tuple[ConnectorAdapter, str]] = {}
        for server, tool in mcp.all_tools():
            specs.append(
                ToolSpec(
                    tool.exposed_name, (tool.description or tool.name)[:1024], tool.input_schema
                )
            )
            sources[tool.exposed_name] = f"mcp:{server}"
        for adapter in adapters:
            for spec in adapter.tools():
                local = adapter.resolve(spec.name)
                if local:
                    specs.append(spec)
                    sources[spec.name] = f"conn:{adapter.name}"
                    conns[spec.name] = (adapter, local)
        return cls(specs, sources, conns, mcp)

    async def call(self, name: str, args: dict[str, Any]) -> str:
        if name in self.connectors:
            adapter, local = self.connectors[name]
            return await adapter.run(local, args)
        if self.sources.get(name, "").startswith("mcp:"):
            return await self.mcp.call_tool(name, args)
        raise AppError(f"Unknown tool '{name}'", code="not_found", status=404)


def build_system_prompt(base: str, skills: list[Skill]) -> str:
    parts = [base.strip()] if base.strip() else []
    for sk in skills:
        block = f"## Skill: {sk.name}\n"
        if sk.description:
            block += f"{sk.description}\n\n"
        block += sk.instructions.strip()
        if sk.tools:
            block += f"\n\nPreferred tools for this skill: {', '.join(sk.tools)}"
        parts.append(block)
    return "\n\n".join(parts)


def select_skills(session: Session, skill_ids: list[int] | None) -> list[Skill]:
    q = select(Skill).where(Skill.enabled == True)  # noqa: E712
    if skill_ids is not None:
        if not skill_ids:
            return []
        q = q.where(Skill.id.in_(skill_ids))  # type: ignore[union-attr]
    return list(session.exec(q.order_by(Skill.name)))


def _to_msg(m: ChatMessage) -> dict[str, Any]:
    d: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        d["tool_calls"] = m.tool_calls
    if m.tool_call_id:
        d["tool_call_id"] = m.tool_call_id
    if m.name:
        d["name"] = m.name
    return d


class Orchestrator:
    def __init__(
        self,
        *,
        db: Session,
        provider: ModelProvider,
        tools: ToolRegistry | None,
        settings: Settings,
        system_prompt: str,
        temperature: float,
    ) -> None:
        self.db = db
        self.provider = provider
        self.tools = tools
        self.settings = settings
        self.system_prompt = system_prompt
        self.temperature = temperature

    def _save(self, session_id: str, **kw: Any) -> ChatMessage:
        msg = ChatMessage(session_id=session_id, **kw)
        self.db.add(msg)
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def _history(self, session_id: str) -> list[dict[str, Any]]:
        rows = list(
            self.db.exec(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.id.desc())  # type: ignore[union-attr]
                .limit(HISTORY_LIMIT)
            )
        )[::-1]
        # Never start the window on an orphan tool result.
        while rows and rows[0].role == "tool":
            rows.pop(0)
        return [_to_msg(r) for r in rows]

    async def run(
        self, chat: ChatSession, user_text: str, model: str
    ) -> AsyncIterator[dict[str, Any]]:
        self._save(chat.id, role="user", content=user_text)
        if chat.title == "New chat":
            chat.title = (user_text.strip().splitlines() or ["New chat"])[0][:60]
        chat.model, chat.updated_at = model, utcnow()
        self.db.add(chat)
        self.db.commit()
        yield {"event": "session", "data": {"session_id": chat.id, "title": chat.title}}

        specs = self.tools.specs if self.tools else []
        for round_no in range(self.settings.max_tool_rounds + 1):
            messages = [{"role": "system", "content": self.system_prompt}, *self._history(chat.id)]
            # On the final round, withhold tools to force a textual answer.
            offer = specs if round_no < self.settings.max_tool_rounds else []
            text, calls = "", []
            try:
                async for ev in self.provider.chat_stream(
                    model=model, messages=messages, tools=offer, temperature=self.temperature
                ):
                    if ev.type == "delta":
                        text += ev.content
                        yield {"event": "delta", "data": {"content": ev.content}}
                    elif ev.type == "tool_calls":
                        calls.extend(ev.tool_calls)
            except ProviderError as exc:
                if text:
                    self._save(chat.id, role="assistant", content=text)
                yield {"event": "error", "data": {"message": str(exc)}}
                return

            self._save(
                chat.id,
                role="assistant",
                content=text,
                tool_calls=[c.to_dict() for c in calls] or None,
            )
            if not calls:
                yield {"event": "done", "data": {"rounds": round_no + 1}}
                return

            for call in calls:
                yield {
                    "event": "tool_call",
                    "data": call.to_dict() | {"source": self._source(call)},
                }
                result, ok = await self._exec(call)
                self._save(
                    chat.id, role="tool", content=result, tool_call_id=call.id, name=call.name
                )
                yield {
                    "event": "tool_result",
                    "data": {"id": call.id, "name": call.name, "ok": ok, "content": result},
                }

        yield {
            "event": "done",
            "data": {"rounds": self.settings.max_tool_rounds + 1, "truncated": True},
        }

    def _source(self, call: ToolCall) -> str:
        return self.tools.sources.get(call.name, "unknown") if self.tools else "unknown"

    async def _exec(self, call: ToolCall) -> tuple[str, bool]:
        if not self.tools:
            return "Tools are disabled for this chat.", False
        try:
            return await self.tools.call(call.name, call.arguments), True
        except AppError as exc:
            return f"Error: {exc.message}", False
        except TimeoutError:
            return f"Error: tool '{call.name}' timed out", False
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Tool %s failed", call.name)
            return f"Error: {type(exc).__name__}: {exc}"[:1000], False
