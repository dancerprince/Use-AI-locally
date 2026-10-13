from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import __version__
from ..deps import AppState, get_state
from ..schemas import ModelHealth, ModelSettings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/health/runtime")
async def runtime_health(state: AppState = Depends(get_state)) -> dict[str, Any]:
    return (await state.runtime.status()).to_dict()


@router.get("/health/model", response_model=ModelHealth)
async def model_health(state: AppState = Depends(get_state)) -> ModelHealth:
    cfg = state.store.get()
    res = await state.store.provider(cfg).ping()
    return ModelHealth(
        online=res.online,
        provider=cfg.provider,
        base_url=cfg.base_url,
        latency_ms=res.latency_ms,
        models=res.models,
        error=res.error,
    )


@router.get("/settings/model", response_model=ModelSettings)
async def get_model_settings(state: AppState = Depends(get_state)) -> ModelSettings:
    return state.store.get_public()


@router.put("/settings/model", response_model=ModelSettings)
async def put_model_settings(
    body: ModelSettings, state: AppState = Depends(get_state)
) -> ModelSettings:
    return state.store.update(body)


@router.post("/settings/model/test", response_model=ModelHealth)
async def test_model_settings(
    body: ModelSettings, state: AppState = Depends(get_state)
) -> ModelHealth:
    current = state.store.get()
    if body.api_key and set(body.api_key) == {"•"}:
        body = body.model_copy(update={"api_key": current.api_key})
    res = await state.store.provider(body).ping()
    return ModelHealth(
        online=res.online,
        provider=body.provider,
        base_url=body.base_url,
        latency_ms=res.latency_ms,
        models=res.models,
        error=res.error,
    )
