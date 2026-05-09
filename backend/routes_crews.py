from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .auth import require_admin
from .db import get_session
from .models import Crew, CrewRelation
from .schemas import CrewCreate, CrewOut, CrewRelationBase, CrewRelationOut, CrewUpdate

router = APIRouter(prefix="/api/crews", tags=["crews"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[CrewOut])
async def list_crews(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Crew).order_by(Crew.name))
    return result.scalars().all()


@router.post("", response_model=CrewOut, status_code=201)
async def create_crew(payload: CrewCreate, session: AsyncSession = Depends(get_session)):
    crew = Crew(**payload.model_dump())
    session.add(crew)
    await session.commit()
    await session.refresh(crew)
    return crew


@router.get("/{crew_id}", response_model=CrewOut)
async def get_crew(crew_id: int, session: AsyncSession = Depends(get_session)):
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")
    return crew


@router.patch("/{crew_id}", response_model=CrewOut)
async def update_crew(
    crew_id: int, payload: CrewUpdate, session: AsyncSession = Depends(get_session)
):
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(crew, k, v)
    await session.commit()
    await session.refresh(crew)
    return crew


@router.delete("/{crew_id}", status_code=204)
async def delete_crew(crew_id: int, session: AsyncSession = Depends(get_session)):
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")
    await session.delete(crew)
    await session.commit()


# ---- Relations ----


@router.get("/{crew_id}/relations", response_model=list[CrewRelationOut])
async def list_relations(crew_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(CrewRelation).where(
            (CrewRelation.crew_a_id == crew_id) | (CrewRelation.crew_b_id == crew_id)
        )
    )
    return result.scalars().all()


@router.post("/{crew_id}/relations", response_model=CrewRelationOut, status_code=201)
async def add_relation(
    crew_id: int,
    payload: CrewRelationBase,
    session: AsyncSession = Depends(get_session),
):
    if crew_id not in (payload.crew_a_id, payload.crew_b_id):
        raise HTTPException(400, "crew_id muss in Relation enthalten sein")
    if payload.crew_a_id == payload.crew_b_id:
        raise HTTPException(400, "Self-Relation nicht erlaubt")
    rel = CrewRelation(**payload.model_dump())
    session.add(rel)
    await session.commit()
    await session.refresh(rel)
    return rel


@router.delete("/relations/{relation_id}", status_code=204)
async def delete_relation(relation_id: int, session: AsyncSession = Depends(get_session)):
    rel = await session.get(CrewRelation, relation_id)
    if not rel:
        raise HTTPException(404, "Relation nicht gefunden")
    await session.delete(rel)
    await session.commit()
