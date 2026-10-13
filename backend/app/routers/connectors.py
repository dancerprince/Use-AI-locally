from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response

from ..deps import get_repo
from ..errors import AppError
from ..models import Connector
from ..schemas import ConnectorIn, ConnectorOut, TestResult, ToggleIn
from ..services.connectors import CONNECTOR_TYPES
from ..services.repository import Repository

router = APIRouter(prefix="/connectors", tags=["connectors"])


def _out(row: Connector, repo: Repository) -> ConnectorOut:
    assert row.id is not None
    try:
        tools = [t.name for t in repo.adapter(row).tools()]
    except AppError:
        tools = []
    return ConnectorOut(
        id=row.id,
        name=row.name,
        type=row.type,  # type: ignore[arg-type]
        config=repo.masked_connector_config(row),
        enabled=row.enabled,
        tools=tools,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/types")
async def connector_types() -> list[dict[str, Any]]:
    return [
        {"type": t, "secret_fields": list(c.secret_fields), "schema": c.Config.model_json_schema()}
        for t, c in CONNECTOR_TYPES.items()
    ]


@router.get("", response_model=list[ConnectorOut])
async def list_connectors(repo: Repository = Depends(get_repo)):
    return [_out(r, repo) for r in repo.list_connectors()]


@router.post("", response_model=ConnectorOut, status_code=201)
async def create_connector(body: ConnectorIn, repo: Repository = Depends(get_repo)):
    return _out(repo.save_connector(body), repo)


@router.get("/{cid}", response_model=ConnectorOut)
async def get_connector(cid: int, repo: Repository = Depends(get_repo)):
    return _out(repo.get_connector(cid), repo)


@router.put("/{cid}", response_model=ConnectorOut)
async def update_connector(cid: int, body: ConnectorIn, repo: Repository = Depends(get_repo)):
    return _out(repo.save_connector(body, repo.get_connector(cid)), repo)


@router.patch("/{cid}/enabled", response_model=ConnectorOut)
async def toggle_connector(cid: int, body: ToggleIn, repo: Repository = Depends(get_repo)):
    row = repo.get_connector(cid)
    row.enabled = body.enabled
    repo.s.add(row)
    repo.s.commit()
    repo.s.refresh(row)
    return _out(row, repo)


@router.post("/{cid}/test", response_model=TestResult)
async def test_connector(cid: int, repo: Repository = Depends(get_repo)):
    row = repo.get_connector(cid)
    try:
        msg = await repo.adapter(row).test()
        return TestResult(ok=True, message=msg)
    except AppError as exc:
        return TestResult(ok=False, message=exc.message)
    except Exception as exc:
        return TestResult(ok=False, message=f"{type(exc).__name__}: {exc}"[:500])


@router.delete("/{cid}", status_code=204)
async def delete_connector(cid: int, repo: Repository = Depends(get_repo)):
    repo.delete(repo.get_connector(cid))
    return Response(status_code=204)
