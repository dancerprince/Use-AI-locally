from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from ..deps import AppState, get_repo, get_state
from ..errors import AppError
from ..models import McpServer
from ..schemas import McpServerIn, McpServerOut, McpToolOut, TestResult, ToggleIn
from ..security import mask_values
from ..services.mcp_manager import validate_stdio_command
from ..services.repository import Repository

router = APIRouter(prefix="/mcp-servers", tags=["mcp"])


def _out(row: McpServer, repo: Repository, state: AppState) -> McpServerOut:
    assert row.id is not None
    status, err, tools = state.mcp.status(row.id)
    sec = repo.mcp_secrets(row)
    return McpServerOut(
        id=row.id,
        name=row.name,
        transport=row.transport,  # type: ignore[arg-type]
        command=row.command,
        args=list(row.args or []),
        env=mask_values(sec["env"]),
        url=row.url,
        headers=mask_values(sec["headers"]),
        enabled=row.enabled,
        status=status if row.enabled else "disabled",
        last_error=err,
        tools=[McpToolOut(**t.__dict__) for t in tools],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _guard(body: McpServerIn, state: AppState) -> None:
    if body.transport == "stdio":
        assert body.command
        validate_stdio_command(body.command, state.settings.mcp_stdio_allowed_commands)
        if not body.confirmed:
            raise AppError(
                "stdio servers execute a local command. Re-submit with confirmed=true to approve.",
                code="confirmation_required",
                status=428,
            )


@router.get("", response_model=list[McpServerOut])
async def list_servers(repo: Repository = Depends(get_repo), state: AppState = Depends(get_state)):
    return [_out(r, repo, state) for r in repo.list_mcp()]


@router.post("", response_model=McpServerOut, status_code=201)
async def create_server(
    body: McpServerIn, repo: Repository = Depends(get_repo), state: AppState = Depends(get_state)
):
    _guard(body, state)
    row = repo.save_mcp(body)
    if row.enabled:
        await state.mcp.start(repo.mcp_config(row))
    return _out(row, repo, state)


@router.get("/{sid}", response_model=McpServerOut)
async def get_server(
    sid: int, repo: Repository = Depends(get_repo), state: AppState = Depends(get_state)
):
    return _out(repo.get_mcp(sid), repo, state)


@router.put("/{sid}", response_model=McpServerOut)
async def update_server(
    sid: int,
    body: McpServerIn,
    repo: Repository = Depends(get_repo),
    state: AppState = Depends(get_state),
):
    _guard(body, state)
    row = repo.save_mcp(body, repo.get_mcp(sid))
    await state.mcp.stop(sid)
    if row.enabled:
        await state.mcp.start(repo.mcp_config(row))
    return _out(row, repo, state)


@router.patch("/{sid}/enabled", response_model=McpServerOut)
async def toggle_server(
    sid: int,
    body: ToggleIn,
    repo: Repository = Depends(get_repo),
    state: AppState = Depends(get_state),
):
    row = repo.get_mcp(sid)
    row.enabled = body.enabled
    repo.s.add(row)
    repo.s.commit()
    repo.s.refresh(row)
    if row.enabled:
        await state.mcp.start(repo.mcp_config(row))
    else:
        await state.mcp.stop(sid)
    return _out(row, repo, state)


@router.post("/{sid}/reconnect", response_model=McpServerOut)
async def reconnect_server(
    sid: int, repo: Repository = Depends(get_repo), state: AppState = Depends(get_state)
):
    row = repo.get_mcp(sid)
    if not row.enabled:
        raise AppError("Enable the server before reconnecting")
    await state.mcp.start(repo.mcp_config(row))
    return _out(row, repo, state)


@router.post("/{sid}/test", response_model=TestResult)
async def test_server(
    sid: int, repo: Repository = Depends(get_repo), state: AppState = Depends(get_state)
):
    row = repo.get_mcp(sid)
    if row.enabled:
        await state.mcp.start(repo.mcp_config(row))
    status, err, tools = state.mcp.status(sid)
    ok = status == "connected"
    msg = f"Connected, {len(tools)} tools available" if ok else (err or f"Status: {status}")
    return TestResult(ok=ok, message=msg, details=[t.name for t in tools])


@router.delete("/{sid}", status_code=204)
async def delete_server(
    sid: int, repo: Repository = Depends(get_repo), state: AppState = Depends(get_state)
):
    row = repo.get_mcp(sid)
    await state.mcp.stop(sid)
    repo.delete(row)
    return Response(status_code=204)
