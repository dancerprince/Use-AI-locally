"""Application state container and FastAPI dependencies."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.engine import Engine
from sqlmodel import Session

from .config import Settings
from .errors import AppError
from .security import Crypto
from .services.mcp_manager import McpManager
from .services.model_manager import ModelManager
from .services.repository import Repository
from .services.runtime import RuntimeManager
from .services.settings_store import SettingsStore


@dataclass
class AppState:
    settings: Settings
    engine: Engine
    crypto: Crypto
    mcp: McpManager
    store: SettingsStore
    models: ModelManager
    runtime: RuntimeManager


def get_state(request: Request) -> AppState:
    return request.app.state.oai  # type: ignore[no-any-return]


def get_db(state: AppState = Depends(get_state)) -> Iterator[Session]:
    with Session(state.engine) as s:
        yield s


def get_repo(db: Session = Depends(get_db), state: AppState = Depends(get_state)) -> Repository:
    return Repository(db, state.crypto, state.settings)


def require_token(request: Request, state: AppState = Depends(get_state)) -> None:
    """Optional bearer-token auth (enabled when OAI_API_TOKEN is set)."""
    expected = state.settings.api_token
    if not expected:
        return
    header = request.headers.get("authorization", "")
    supplied = header[7:] if header.lower().startswith("bearer ") else ""
    if not secrets.compare_digest(supplied, expected):
        raise AppError("Missing or invalid API token", code="unauthorized", status=401)
