import asyncio
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .ai import get_provider
from .auth import require_admin
from .config import settings
from .db import get_session
from .models import Crew, CrewRelation, Mission
from .prompts import build_crime_business_briefing_prompt
from .schemas import (
    CrewCreate,
    CrewOut,
    CrewRelationBase,
    CrewRelationOut,
    CrewUpdate,
    CrimeBusinessSendRequest,
)
from .settings_store import get as settings_get_value

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


@router.get("/notifications")
async def crew_notifications(session: AsyncSession = Depends(get_session)):
    """Liefert pro Crew mit info_channel_id den Zeitstempel der jüngsten
    Nicht-Bot-Message im Info-Channel — fürs Blink-Indicator auf dem Dashboard.
    Bot-Calls laufen parallel, damit Polling auch bei vielen Crews schnell ist.

    WICHTIG: Diese Route MUSS vor allen `/{crew_id}`-Routes stehen, sonst matcht
    FastAPI 'notifications' als int crew_id und wirft 422."""
    res = await session.execute(
        select(Crew).where(Crew.info_channel_id != "").order_by(Crew.id)
    )
    crews_with_info = list(res.scalars().all())

    if not crews_with_info:
        return []

    async def _fetch_latest(channel_id: str) -> str | None:
        # Limit hoch genug, damit Bot-Messages oben nicht alles wegfiltern.
        try:
            async with httpx.AsyncClient(timeout=5.0) as cli:
                r = await cli.post(
                    "http://127.0.0.1:8001/read_channel",
                    json={"channel_id": channel_id, "limit": 10, "oldest_first": False},
                )
            if r.status_code >= 400:
                return None
            msgs = r.json()
            if not msgs:
                return None
            return msgs[0].get("posted_at")
        except Exception:
            return None

    timestamps = await asyncio.gather(
        *[_fetch_latest(c.info_channel_id) for c in crews_with_info]
    )

    return [
        {"crew_id": c.id, "latest_boss_message_at": ts}
        for c, ts in zip(crews_with_info, timestamps)
    ]


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


# ---- Crime-Business: KI-Umformulierung + Sendung an separaten Channel ----

@router.post("/{crew_id}/send-crime-business")
async def send_crime_business(
    crew_id: int,
    payload: CrimeBusinessSendRequest,
    session: AsyncSession = Depends(get_session),
):
    """Liest crime_business der Crew, formuliert es per KI im Noir-Stil um
    (passend zur Hintergrund-Story) und postet das Ergebnis in den
    crime_business_channel_id der Crew. Speichert KEINE Mission ab —
    eigenstaendiger Briefing-Post."""
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")
    if not (crew.crime_business or "").strip():
        raise HTTPException(400, "Keine Crime-Business-Beschreibung hinterlegt")
    if not (crew.crime_business_channel_id or "").strip():
        raise HTTPException(400, "Kein Crime-Business-Channel hinterlegt")

    # AI-Provider aufbauen (gleiche Konfiguration wie Mission-Generator)
    keys = {
        "anthropic": await settings_get_value(session, "anthropic_api_key", settings.anthropic_api_key),
        "openai": await settings_get_value(session, "openai_api_key", settings.openai_api_key),
    }
    models = {
        "claude": await settings_get_value(session, "default_claude_model", settings.default_claude_model),
        "openai": await settings_get_value(session, "default_openai_model", settings.default_openai_model),
    }
    provider_name = payload.provider or await settings_get_value(
        session, "default_provider", settings.default_ai_provider
    )
    provider = await get_provider(provider_name, keys=keys, models=models)

    system_prompt, user_prompt = build_crime_business_briefing_prompt(
        crew_name=crew.name,
        crew_story=crew.story_background or "",
        crime_business=crew.crime_business,
    )

    try:
        text = await provider.generate(user_prompt, model=payload.model, system_prompt=system_prompt)
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc

    # Sicherheits-Limit fuer Discord (2000 Zeichen max)
    text = (text or "").strip()
    if len(text) > 1990:
        text = text[:1985] + "…"

    # Bot-Call zum Posten in den Channel
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(
                "http://127.0.0.1:8001/post_text",
                json={"channel_id": crew.crime_business_channel_id, "content": text},
            )
        if r.status_code >= 400:
            try:
                detail = r.json().get("error", r.text)
            except Exception:
                detail = r.text
            raise HTTPException(r.status_code, f"Bot-Fehler: {detail}")
        bot_result = r.json()
    except httpx.RequestError as exc:
        raise HTTPException(503, f"Bot nicht erreichbar: {exc}") from exc

    return {
        "ok": True,
        "ai_provider": provider.name,
        "ai_model": payload.model or "",
        "char_count": len(text),
        "preview": text[:200],
        "discord_message_id": bot_result.get("message_id"),
    }
