"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .config import Settings, get_settings
from .db import create_db_engine, init_db
from .deps import AppState, require_token
from .errors import install_error_handlers
from .logging_setup import configure_logging
from .paths import ensure_private_dir, migrate_legacy_data
from .routers import chat, connectors, health, mcp, models, skills
from .security import Crypto
from .services.mcp_manager import McpManager
from .services.model_manager import ModelManager
from .services.repository import Repository
from .services.runtime import RuntimeManager
from .services.settings_store import SettingsStore

log = logging.getLogger("offline_ai")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ensure_private_dir(settings.data_dir)
        migrate_legacy_data(settings.data_dir)
        engine = create_db_engine(settings)
        init_db(engine)
        crypto = Crypto(settings)
        store = SettingsStore(engine, settings, crypto)
        cfg = store.get()
        runtime = RuntimeManager(cfg.base_url, settings.models_dir)
        if settings.manage_runtime and cfg.provider == "ollama":
            st = await runtime.ensure_running()
            if not st.installed:
                log.warning("Ollama not found. Install it with: %s", st.install_hint)
        state = AppState(
            settings=settings,
            engine=engine,
            crypto=crypto,
            mcp=McpManager(settings),
            store=store,
            models=ModelManager(
                cfg.base_url, models_dir=settings.models_dir, data_dir=settings.data_dir
            ),
            runtime=runtime,
        )
        app.state.oai = state
        with Session(engine) as s:
            repo = Repository(s, crypto, settings)
            for row in repo.list_mcp():
                if row.enabled:
                    try:
                        await state.mcp.start(repo.mcp_config(row), wait=False)
                    except Exception:
                        log.exception("Could not start MCP server %s", row.name)
        log.info("Offline AI %s ready on http://%s:%s", __version__, settings.host, settings.port)
        try:
            yield
        finally:
            await state.models.shutdown()
            await state.mcp.shutdown()
            runtime.stop()
            engine.dispose()
            log.info("Shutdown complete")

    app = FastAPI(title="Offline AI", version=__version__, lifespan=lifespan)
    install_error_handlers(app)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
    )

    api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
    for r in (
        health.router,
        mcp.router,
        connectors.router,
        skills.router,
        chat.router,
        models.router,
    ):
        api.include_router(r)
    app.include_router(api)

    dist = settings.frontend_dist or _find_frontend()
    if dist.is_dir() and (dist / "index.html").exists():
        app.mount("/assets", _ImmutableStatic(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate, headers=_NO_CACHE)
            # index.html is never cached, so every browser always loads the current bundle.
            return FileResponse(dist / "index.html", headers={**_NO_CACHE, **_SECURITY})

    return app


_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
_SECURITY = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; img-src 'self' data: blob:; connect-src 'self' ws: wss:; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class _ImmutableStatic(StaticFiles):
    """Hashed Vite assets: safe to cache forever, names change on every build."""

    def file_response(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


def _find_frontend() -> Path:
    """Bundled UI inside the installed package first, then the dev build."""
    bundled = Path(__file__).resolve().parent / "static"
    if (bundled / "index.html").is_file():
        return bundled
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def run() -> None:
    from .cli import main

    main()


if __name__ == "__main__":
    run()
