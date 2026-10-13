from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from ..deps import get_repo
from ..schemas import SkillIn, SkillOut, ToggleIn
from ..services.repository import Repository

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("", response_model=list[SkillOut])
async def list_skills(repo: Repository = Depends(get_repo)):
    return repo.list_skills()


@router.post("", response_model=SkillOut, status_code=201)
async def create_skill(body: SkillIn, repo: Repository = Depends(get_repo)):
    return repo.save_skill(body)


@router.get("/{sid}", response_model=SkillOut)
async def get_skill(sid: int, repo: Repository = Depends(get_repo)):
    return repo.get_skill(sid)


@router.put("/{sid}", response_model=SkillOut)
async def update_skill(sid: int, body: SkillIn, repo: Repository = Depends(get_repo)):
    return repo.save_skill(body, repo.get_skill(sid))


@router.patch("/{sid}/enabled", response_model=SkillOut)
async def toggle_skill(sid: int, body: ToggleIn, repo: Repository = Depends(get_repo)):
    row = repo.get_skill(sid)
    row.enabled = body.enabled
    repo.s.add(row)
    repo.s.commit()
    repo.s.refresh(row)
    return row


@router.delete("/{sid}", status_code=204)
async def delete_skill(sid: int, repo: Repository = Depends(get_repo)):
    repo.delete(repo.get_skill(sid))
    return Response(status_code=204)
