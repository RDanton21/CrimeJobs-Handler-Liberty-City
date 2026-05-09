from datetime import datetime
from pathlib import Path
from uuid import uuid4

import aiofiles
import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from .ai import get_provider
from .auth import require_admin
from .config import settings
from .db import get_session
from .models import Crew, CrewRelation, Mission, MissionStatus
from .prompts import MissionContext, build_rewrite_prompt, build_user_prompt
from .schemas import (
    MissionGenerateRequest,
    MissionOut,
    MissionRewriteRequest,
    MissionUpdate,
    StatusOverrideRequest,
)
from .settings_store import get as settings_get

router = APIRouter(prefix="/api/missions", tags=["missions"], dependencies=[Depends(require_admin)])


async def _load_context(session: AsyncSession, crew: Crew, extra: str) -> MissionContext:
    rel_q = await session.execute(
        select(CrewRelation).where(
            (CrewRelation.crew_a_id == crew.id) | (CrewRelation.crew_b_id == crew.id)
        )
    )
    relations: list[dict] = []
    for r in rel_q.scalars().all():
        other_id = r.crew_b_id if r.crew_a_id == crew.id else r.crew_a_id
        other = await session.get(Crew, other_id)
        if other is None:
            continue
        relations.append(
            {
                "name": other.name,
                "story": other.story_background,
                "relation_type": r.relation_type.value,
                "notes": r.notes,
            }
        )

    hist_q = await session.execute(
        select(Mission)
        .where(
            Mission.crew_id == crew.id,
            Mission.status != MissionStatus.DRAFT,
            Mission.archived_at.is_(None),
        )
        .order_by(desc(Mission.created_at))
        .limit(5)
    )
    history: list[dict] = []
    for m in hist_q.scalars().all():
        history.append(
            {
                "content": m.content_final or m.content_generated,
                "status": m.status.value,
                "created_at": m.created_at.isoformat() if m.created_at else "",
            }
        )

    return MissionContext(
        crew_name=crew.name,
        crew_story=crew.story_background,
        related_crews=relations,
        history=history,
        extra_instructions=extra,
    )


@router.post("/generate", response_model=MissionOut)
async def generate_mission(
    payload: MissionGenerateRequest, session: AsyncSession = Depends(get_session)
):
    crew = await session.get(Crew, payload.crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")

    keys = {
        "anthropic": await settings_get(session, "anthropic_api_key", settings.anthropic_api_key),
        "openai": await settings_get(session, "openai_api_key", settings.openai_api_key),
    }
    models = {
        "claude": await settings_get(session, "default_claude_model", settings.default_claude_model),
        "openai": await settings_get(session, "default_openai_model", settings.default_openai_model),
    }
    provider_name = payload.provider or await settings_get(
        session, "default_provider", settings.default_ai_provider
    )

    provider = await get_provider(provider_name, keys=keys, models=models)

    ctx = await _load_context(session, crew, payload.extra_instructions)
    user_prompt = build_user_prompt(ctx)

    try:
        text = await provider.generate(user_prompt, model=payload.model)
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc

    mission = Mission(
        crew_id=crew.id,
        ai_provider=provider.name,
        ai_model=payload.model or "",
        prompt_used=user_prompt,
        content_generated=text,
        content_final=text,
        discord_channel_id=crew.discord_channel_id,
        status=MissionStatus.DRAFT,
    )
    session.add(mission)
    await session.commit()
    await session.refresh(mission)
    return mission


@router.post("/rewrite", response_model=MissionOut)
async def rewrite_mission(
    payload: MissionRewriteRequest, session: AsyncSession = Depends(get_session)
):
    if not payload.raw_input.strip():
        raise HTTPException(400, "raw_input darf nicht leer sein")

    crew = await session.get(Crew, payload.crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")

    keys = {
        "anthropic": await settings_get(session, "anthropic_api_key", settings.anthropic_api_key),
        "openai": await settings_get(session, "openai_api_key", settings.openai_api_key),
    }
    models = {
        "claude": await settings_get(session, "default_claude_model", settings.default_claude_model),
        "openai": await settings_get(session, "default_openai_model", settings.default_openai_model),
    }
    provider_name = payload.provider or await settings_get(
        session, "default_provider", settings.default_ai_provider
    )

    provider = await get_provider(provider_name, keys=keys, models=models)

    ctx = await _load_context(session, crew, payload.extra_instructions)
    user_prompt = build_rewrite_prompt(ctx, payload.raw_input)

    try:
        text = await provider.generate(user_prompt, model=payload.model)
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc

    mission = Mission(
        crew_id=crew.id,
        ai_provider=provider.name,
        ai_model=payload.model or "",
        prompt_used=user_prompt,
        content_generated=text,
        content_final=text,
        discord_channel_id=crew.discord_channel_id,
        status=MissionStatus.DRAFT,
    )
    session.add(mission)
    await session.commit()
    await session.refresh(mission)
    return mission


@router.get("", response_model=list[MissionOut])
async def list_missions(
    crew_id: int | None = None,
    archived: bool = False,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    q = select(Mission).order_by(desc(Mission.created_at)).limit(limit)
    if crew_id is not None:
        q = q.where(Mission.crew_id == crew_id)
    if archived:
        q = q.where(Mission.archived_at.is_not(None))
    else:
        q = q.where(Mission.archived_at.is_(None))
    result = await session.execute(q)
    return result.scalars().all()


@router.get("/{mission_id}", response_model=MissionOut)
async def get_mission(mission_id: int, session: AsyncSession = Depends(get_session)):
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    return m


@router.patch("/{mission_id}", response_model=MissionOut)
async def update_mission(
    mission_id: int, payload: MissionUpdate, session: AsyncSession = Depends(get_session)
):
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    if m.status != MissionStatus.DRAFT:
        raise HTTPException(409, "Mission ist nicht mehr im Draft-Status")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(m, k, v)
    await session.commit()
    await session.refresh(m)
    return m


@router.post("/{mission_id}/image", response_model=MissionOut)
async def upload_image(
    mission_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    if m.status != MissionStatus.DRAFT:
        raise HTTPException(409, "Bilder nur im Draft-Status setzbar")

    ext = Path(file.filename or "img.png").suffix.lower() or ".png"
    if ext not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        raise HTTPException(400, "Format nicht unterstützt")

    target_dir = Path(settings.image_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"mission_{mission_id}_{uuid4().hex}{ext}"

    async with aiofiles.open(target, "wb") as f:
        await f.write(await file.read())

    m.image_path = str(target)
    await session.commit()
    await session.refresh(m)
    return m


@router.delete("/{mission_id}/image", response_model=MissionOut)
async def delete_image(mission_id: int, session: AsyncSession = Depends(get_session)):
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    if m.image_path:
        try:
            Path(m.image_path).unlink(missing_ok=True)
        except Exception:
            pass
    m.image_path = ""
    await session.commit()
    await session.refresh(m)
    return m


@router.post("/{mission_id}/send", response_model=MissionOut)
async def send_to_discord(mission_id: int, session: AsyncSession = Depends(get_session)):
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    if m.status != MissionStatus.DRAFT:
        raise HTTPException(409, "Mission ist nicht im Draft-Status")
    if not m.discord_channel_id:
        crew = await session.get(Crew, m.crew_id)
        if crew and crew.discord_channel_id:
            m.discord_channel_id = crew.discord_channel_id
            await session.commit()
        else:
            raise HTTPException(400, "Crew hat keinen Discord-Channel hinterlegt")

    async with httpx.AsyncClient(timeout=30.0) as cli:
        try:
            r = await cli.post("http://127.0.0.1:8001/send", json={"mission_id": mission_id})
        except Exception as exc:
            raise HTTPException(503, f"Discord-Bot nicht erreichbar: {exc}") from exc
    if r.status_code >= 400:
        raise HTTPException(502, f"Bot Fehler: {r.text}")

    await session.refresh(m)
    return m


@router.post("/{mission_id}/override", response_model=MissionOut)
async def override_status(
    mission_id: int,
    payload: StatusOverrideRequest,
    session: AsyncSession = Depends(get_session),
):
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    if payload.status not in {
        MissionStatus.APPROVED,
        MissionStatus.REJECTED,
        MissionStatus.CANCELLED,
    }:
        raise HTTPException(400, "Override nur auf approved/rejected/cancelled")
    m.status = payload.status
    m.reacted_at = datetime.utcnow()
    await session.commit()
    await session.refresh(m)
    return m


@router.delete("/{mission_id}", response_model=MissionOut)
async def archive_mission(mission_id: int, session: AsyncSession = Depends(get_session)):
    """Soft-Delete: Mission ins Archiv verschieben + Discord-Message loeschen +
    Boss-Texte aus Zusatzinfo-Channel im Mission-Zeitfenster loeschen."""
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    if m.archived_at is not None:
        return m  # bereits archiviert

    crew = await session.get(Crew, m.crew_id)

    # Boss-Texte aus Zusatzinfo-Channel im Zeitfenster (sent_at .. next_mission.sent_at) loeschen
    if crew and crew.info_channel_id and m.sent_at:
        next_q = await session.execute(
            select(Mission)
            .where(
                Mission.crew_id == crew.id,
                Mission.id != m.id,
                Mission.archived_at.is_(None),
                Mission.sent_at.is_not(None),
                Mission.sent_at > m.sent_at,
            )
            .order_by(Mission.sent_at)
            .limit(1)
        )
        next_m = next_q.scalar_one_or_none()
        before_iso = next_m.sent_at.isoformat() if next_m else None

        try:
            async with httpx.AsyncClient(timeout=30.0) as cli:
                await cli.post(
                    "http://127.0.0.1:8001/delete_in_range",
                    json={
                        "channel_id": crew.info_channel_id,
                        "after_iso": m.sent_at.isoformat(),
                        "before_iso": before_iso,
                    },
                )
        except Exception:
            pass  # Bot offline -> Auftrags-Delete + DB-Archiv weiterlaufen lassen

    # Discord-Message im Auftrags-Channel loeschen
    if m.discord_message_id and m.discord_channel_id:
        try:
            async with httpx.AsyncClient(timeout=15.0) as cli:
                await cli.post(
                    "http://127.0.0.1:8001/delete_message",
                    json={
                        "channel_id": m.discord_channel_id,
                        "message_id": m.discord_message_id,
                    },
                )
        except Exception:
            pass  # Bot offline -> nur DB-Archiv

    m.archived_at = datetime.utcnow()
    await session.commit()
    await session.refresh(m)
    return m


@router.post("/{mission_id}/restore", response_model=MissionOut)
async def restore_mission(mission_id: int, session: AsyncSession = Depends(get_session)):
    """Mission aus Archiv zurueckholen (Discord-Message bleibt geloescht)."""
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    m.archived_at = None
    m.discord_message_id = ""  # alte Message-Referenz entfernen, sie wurde geloescht
    await session.commit()
    await session.refresh(m)
    return m


@router.delete("/{mission_id}/purge", status_code=204)
async def purge_mission(mission_id: int, session: AsyncSession = Depends(get_session)):
    """Hard-Delete: endgueltig loeschen (auch aus Archiv)."""
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    if m.image_path:
        try:
            Path(m.image_path).unlink(missing_ok=True)
        except Exception:
            pass
    await session.delete(m)
    await session.commit()
