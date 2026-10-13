from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..deps import AppState, get_state
from ..errors import AppError
from ..services.model_manager import ModelManager

router = APIRouter(prefix="/models", tags=["models"])


class PullIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)


def manager(state: AppState = Depends(get_state)) -> ModelManager:
    cfg = state.store.get()
    if cfg.provider != "ollama":
        raise AppError(
            "Model downloads are only available with the Ollama provider",
            code="unsupported_provider",
            status=409,
        )
    state.models.base_url = cfg.base_url.rstrip("/")
    return state.models


@router.get("/runtime")
async def runtime_status(state: AppState = Depends(get_state)) -> dict[str, Any]:
    return (await state.runtime.status()).to_dict()


@router.get("")
async def list_models(m: ModelManager = Depends(manager)) -> list[dict[str, Any]]:
    return await m.list_installed()


@router.get("/catalog")
async def catalog(m: ModelManager = Depends(manager)) -> list[dict[str, Any]]:
    return await m.catalog()


@router.get("/pulls")
async def list_pulls(m: ModelManager = Depends(manager)) -> list[dict[str, Any]]:
    return [j.snapshot() for j in m.jobs.values()]


@router.post("/pull", status_code=202)
async def pull(body: PullIn, m: ModelManager = Depends(manager)) -> dict[str, Any]:
    job = m.start_pull(body.name)
    return {"job_id": job.id, **job.snapshot()}


@router.get("/pull/{job_id}/events")
async def pull_events(job_id: str, m: ModelManager = Depends(manager)) -> StreamingResponse:
    m.get_job(job_id)

    async def gen() -> AsyncIterator[str]:
        async for snap in m.events(job_id):
            yield f"event: progress\ndata: {json.dumps(snap)}\n\n"

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


@router.delete("/pull/{job_id}")
async def cancel_pull(job_id: str, m: ModelManager = Depends(manager)) -> dict[str, Any]:
    return m.cancel(job_id).snapshot()


@router.get("/{name:path}")
async def show_model(name: str, m: ModelManager = Depends(manager)) -> dict[str, Any]:
    return await m.show(name)


@router.delete("/{name:path}", status_code=204)
async def delete_model(name: str, m: ModelManager = Depends(manager)) -> None:
    await m.delete(name)
