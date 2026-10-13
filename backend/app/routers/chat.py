from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from ..deps import AppState, get_db, get_repo, get_state
from ..errors import AppError, NotFoundError
from ..models import ChatMessage, ChatSession
from ..schemas import ChatMessageOut, ChatRequest, ChatSessionOut, ToolInfo
from ..services.orchestrator import Orchestrator, ToolRegistry, build_system_prompt, select_skills
from ..services.repository import Repository

router = APIRouter(tags=["chat"])


def _sse(event: dict[str, Any]) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event['data'], default=str)}\n\n"


def _registry(repo: Repository, state: AppState) -> ToolRegistry:
    adapters = []
    for row in repo.list_connectors():
        if row.enabled:
            try:
                adapters.append(repo.adapter(row))
            except AppError:
                continue
    return ToolRegistry.build(state.mcp, adapters)


@router.get("/tools", response_model=list[ToolInfo])
async def list_tools(repo: Repository = Depends(get_repo), state: AppState = Depends(get_state)):
    reg = _registry(repo, state)
    return [
        ToolInfo(name=s.name, source=reg.sources[s.name], description=s.description)
        for s in reg.specs
    ]


@router.post("/chat")
async def chat(
    body: ChatRequest,
    db: Session = Depends(get_db),
    repo: Repository = Depends(get_repo),
    state: AppState = Depends(get_state),
) -> StreamingResponse:
    if len(body.message) > state.settings.max_message_chars:
        raise AppError(f"Message exceeds {state.settings.max_message_chars} characters", status=413)
    cfg = state.store.get()
    model = body.model or cfg.default_model
    if not model:
        raise AppError(
            "No model selected. Pick one in the UI or set a default in Settings.", code="no_model"
        )

    if body.session_id:
        chat_row = db.get(ChatSession, body.session_id)
        if not chat_row:
            raise NotFoundError("Chat session")
    else:
        chat_row = ChatSession(model=model)
        db.add(chat_row)
        db.commit()
        db.refresh(chat_row)

    skills = select_skills(db, body.skill_ids)
    orch = Orchestrator(
        db=db,
        provider=state.store.provider(cfg),
        tools=_registry(repo, state) if body.use_tools else None,
        settings=state.settings,
        system_prompt=build_system_prompt(cfg.system_prompt, skills),
        temperature=cfg.temperature,
    )

    async def stream() -> AsyncIterator[str]:
        async for ev in orch.run(chat_row, body.message, model):
            yield _sse(ev)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chat/sessions", response_model=list[ChatSessionOut])
async def list_sessions(db: Session = Depends(get_db)):
    return list(db.exec(select(ChatSession).order_by(ChatSession.updated_at.desc())))  # type: ignore[attr-defined]


@router.get("/chat/sessions/{sid}/messages", response_model=list[ChatMessageOut])
async def list_messages(sid: str, db: Session = Depends(get_db)):
    if not db.get(ChatSession, sid):
        raise NotFoundError("Chat session")
    return list(
        db.exec(select(ChatMessage).where(ChatMessage.session_id == sid).order_by(ChatMessage.id))  # type: ignore[arg-type]
    )


@router.delete("/chat/sessions/{sid}", status_code=204)
async def delete_session(sid: str, db: Session = Depends(get_db)):
    row = db.get(ChatSession, sid)
    if not row:
        raise NotFoundError("Chat session")
    for m in db.exec(select(ChatMessage).where(ChatMessage.session_id == sid)):
        db.delete(m)
    db.delete(row)
    db.commit()
    return Response(status_code=204)
