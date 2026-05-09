from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .auth import require_admin
from .db import get_session
from .models import Crew, CrewRelation, Mission
from .schemas import CrewCreate, CrewOut, CrewRelationBase, CrewRelationOut, CrewUpdate

router = APIRouter(prefix="/api/crews", tags=["crews"], dependencies=[Depends(require_admin)])


async def _attach_last_mission(session: AsyncSession, crew: Crew) -> Crew:
    res = await session.execute(
        select(Mission)
        .where(Mission.crew_id == crew.id, Mission.archived_at.is_(None))
        .order_by(Mission.created_at.desc())
        .limit(1)
    )
    last = res.scalar_one_or_none()
    if last:
        crew.last_mission_status = last.status
        crew.last_mission_at = last.reacted_at or last.sent_at or last.created_at
    else:
        crew.last_mission_status = None
        crew.last_mission_at = None
    return crew


@router.get("", response_model=list[CrewOut])
async def list_crews(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Crew).order_by(Crew.name))
    crews = result.scalars().all()
    for c in crews:
        await _attach_last_mission(session, c)
    return crews


@router.post("", response_model=CrewOut, status_code=201)
async def create_crew(payload: CrewCreate, session: AsyncSession = Depends(get_session)):
    crew = Crew(**payload.model_dump())
    session.add(crew)
    await session.commit()
    await session.refresh(crew)
    await _attach_last_mission(session, crew)
    return crew


@router.get("/{crew_id}", response_model=CrewOut)
async def get_crew(crew_id: int, session: AsyncSession = Depends(get_session)):
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")
    await _attach_last_mission(session, crew)
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
    await _attach_last_mission(session, crew)
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


# ---- Boss-Info aus Zusatz-Channel ----


@router.get("/{crew_id}/boss_info")
async def get_crew_boss_info(crew_id: int, session: AsyncSession = Depends(get_session)):
    """Liest den Zusatzinfo-Channel der Crew via Bot, mappt Boss-Texte auf
    aktive (nicht-archivierte, gesendete) Missionen anhand des Zeitfensters
    zwischen Mission.sent_at und der nächsten sent_at."""
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")
    if not crew.info_channel_id:
        return []

    res = await session.execute(
        select(Mission)
        .where(
            Mission.crew_id == crew_id,
            Mission.archived_at.is_(None),
            Mission.sent_at.is_not(None),
        )
        .order_by(Mission.sent_at)
    )
    missions = list(res.scalars().all())
    if not missions:
        return []

    earliest = missions[0].sent_at

    async with httpx.AsyncClient(timeout=15.0) as cli:
        try:
            r = await cli.post(
                "http://127.0.0.1:8001/read_channel",
                json={
                    "channel_id": crew.info_channel_id,
                    "after_iso": earliest.isoformat(),
                    "limit": 100,
                },
            )
        except Exception as exc:
            raise HTTPException(503, f"Bot nicht erreichbar: {exc}") from exc

    if r.status_code >= 400:
        raise HTTPException(502, f"Bot Fehler: {r.text}")

    bot_msgs = r.json()

    out: list[dict] = []
    for i, m in enumerate(missions):
        start = m.sent_at
        end = missions[i + 1].sent_at if i + 1 < len(missions) else None
        bucket: list[dict] = []
        for bm in bot_msgs:
            try:
                ts = datetime.fromisoformat(bm["posted_at"])
            except (KeyError, ValueError):
                continue
            if ts < start:
                continue
            if end and ts >= end:
                continue
            bucket.append(bm)
        out.append({"mission_id": m.id, "messages": bucket})

    return out
