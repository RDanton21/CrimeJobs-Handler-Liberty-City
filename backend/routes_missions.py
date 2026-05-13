import asyncio
import json
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4


async def _resolve_active_system_prompt(session) -> str | None:
    """Aktiver SystemPrompt aus DB > legacy settings.system_prompt > None (Default greift)."""
    res = await session.execute(select(SystemPrompt).where(SystemPrompt.is_active.is_(True)))
    sp = res.scalar_one_or_none()
    if sp and sp.text.strip():
        return sp.text
    legacy = await settings_get(session, "system_prompt", "")
    return legacy or None


def _normalize_naive_utc(dt: datetime | None) -> datetime | None:
    """Pydantic kann tz-aware datetimes liefern (z.B. ISO mit Z-Suffix).
    SQLite DATETIME ist naive — wir konvertieren zu naive UTC."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

import aiofiles
import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .ai import get_provider
from .auth import require_admin
from .config import settings
from .db import get_session
from .models import Crew, CrewRelation, Mission, MissionStatus, SystemPrompt
from .prompts import (
    MissionContext,
    build_mission_suggestions_prompt,
    build_rewrite_prompt,
    build_user_prompt,
)
from .schemas import (
    BulkSendRequest,
    MissionGenerateRequest,
    MissionManualRequest,
    MissionOut,
    MissionRewriteRequest,
    MissionSuggestionsRequest,
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
        crime_business=getattr(crew, "crime_business", "") or "",
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
    system_prompt_val = await _resolve_active_system_prompt(session)

    try:
        text = await provider.generate(user_prompt, model=payload.model, system_prompt=system_prompt_val)
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc

    deadline_at = None
    if payload.deadline_minutes and payload.deadline_minutes > 0:
        deadline_at = datetime.utcnow() + timedelta(minutes=payload.deadline_minutes)

    final_text = text
    if payload.append_text and payload.append_text.strip():
        final_text = f"{text}\n\n---\n\n{payload.append_text.strip()}"

    mission = Mission(
        crew_id=crew.id,
        ai_provider=provider.name,
        ai_model=payload.model or "",
        prompt_used=user_prompt,
        content_generated=text,
        content_final=final_text,
        discord_channel_id=crew.discord_channel_id,
        status=MissionStatus.DRAFT,
        deadline_at=deadline_at,
        scheduled_send_at=_normalize_naive_utc(payload.scheduled_send_at),
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
    system_prompt_val = await _resolve_active_system_prompt(session)

    try:
        text = await provider.generate(user_prompt, model=payload.model, system_prompt=system_prompt_val)
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc

    deadline_at = None
    if payload.deadline_minutes and payload.deadline_minutes > 0:
        deadline_at = datetime.utcnow() + timedelta(minutes=payload.deadline_minutes)

    final_text = text
    if payload.append_text and payload.append_text.strip():
        final_text = f"{text}\n\n---\n\n{payload.append_text.strip()}"

    mission = Mission(
        crew_id=crew.id,
        ai_provider=provider.name,
        ai_model=payload.model or "",
        prompt_used=user_prompt,
        content_generated=text,
        content_final=final_text,
        discord_channel_id=crew.discord_channel_id,
        status=MissionStatus.DRAFT,
        deadline_at=deadline_at,
        scheduled_send_at=_normalize_naive_utc(payload.scheduled_send_at),
    )
    session.add(mission)
    await session.commit()
    await session.refresh(mission)
    return mission


@router.post("/suggestions/{crew_id}")
async def mission_suggestions(
    crew_id: int,
    payload: MissionSuggestionsRequest,
    session: AsyncSession = Depends(get_session),
):
    """Liefert 3 KI-Vorschlaege fuer den naechsten Auftrag der Crew. Basis ist
    die letzte Reaktion: '👍 erledigt' -> Eskalation, '👎 fehlgeschlagen' ->
    Tonwechsel, '❌ nicht ausfuehrbar' -> realistischere Alternativen, kein
    vorheriger Auftrag -> frischer Einstieg.

    Speichert KEINE Mission — der User waehlt einen Vorschlag im Frontend
    und sendet ihn dann manuell via /manual oder /rewrite weiter.
    """
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")

    provider_override = payload.provider
    model_override = payload.model

    keys = {
        "anthropic": await settings_get(session, "anthropic_api_key", settings.anthropic_api_key),
        "openai": await settings_get(session, "openai_api_key", settings.openai_api_key),
    }
    models = {
        "claude": await settings_get(session, "default_claude_model", settings.default_claude_model),
        "openai": await settings_get(session, "default_openai_model", settings.default_openai_model),
    }
    provider_name = provider_override or await settings_get(
        session, "default_provider", settings.default_ai_provider
    )
    provider = await get_provider(provider_name, keys=keys, models=models)

    ctx = await _load_context(session, crew, "")
    system_prompt, user_prompt = build_mission_suggestions_prompt(ctx)

    try:
        text = await provider.generate(user_prompt, model=model_override, system_prompt=system_prompt)
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc

    # KI-Antwort als JSON parsen. Wenn die KI Markdown-Fences oder Erklaerungen
    # mitschickt, versuchen wir die JSON-Liste innerhalb des Strings zu finden.
    raw = (text or "").strip()
    suggestions: list[dict] = []
    try:
        suggestions = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: suche das erste '[' ... ']' Substring
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1 and end > start:
            snippet = raw[start : end + 1]
            try:
                suggestions = json.loads(snippet)
            except json.JSONDecodeError:
                suggestions = []

    # Validieren + auf 3 Eintraege normalisieren
    cleaned: list[dict] = []
    if isinstance(suggestions, list):
        for s in suggestions[:3]:
            if not isinstance(s, dict):
                continue
            title = str(s.get("title", "")).strip()
            content = str(s.get("content", "")).strip()
            if title or content:
                cleaned.append({"title": title or "Vorschlag", "content": content})

    last_status = ""
    if ctx.history:
        last_status = ctx.history[0].get("status", "")

    return {
        "ok": True,
        "ai_provider": provider.name,
        "ai_model": model_override or "",
        "last_status": last_status,
        "suggestions": cleaned,
        "raw": raw if not cleaned else "",  # Debug-Hilfe falls Parsing fehlschlaegt
    }


@router.post("/manual", response_model=MissionOut)
async def create_manual_mission(
    payload: MissionManualRequest, session: AsyncSession = Depends(get_session)
):
    """Erstellt eine Mission ohne KI-Generierung. Inhalt wird 1:1 als content_final
    übernommen — gedacht für Klartext-Aufträge mit Adressen, GPS, etc."""
    if not payload.content.strip():
        raise HTTPException(400, "content darf nicht leer sein")

    crew = await session.get(Crew, payload.crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")

    deadline_at = None
    if payload.deadline_minutes and payload.deadline_minutes > 0:
        deadline_at = datetime.utcnow() + timedelta(minutes=payload.deadline_minutes)

    text = payload.content.strip()
    mission = Mission(
        crew_id=crew.id,
        ai_provider="manual",
        ai_model="",
        prompt_used="",
        content_generated=text,
        content_final=text,
        discord_channel_id=crew.discord_channel_id,
        status=MissionStatus.DRAFT,
        deadline_at=deadline_at,
        scheduled_send_at=_normalize_naive_utc(payload.scheduled_send_at),
    )
    session.add(mission)
    await session.commit()
    await session.refresh(mission)
    return mission


@router.post("/bulk_send")
async def bulk_send(
    payload: BulkSendRequest, session: AsyncSession = Depends(get_session)
):
    """Bulk-Variante: erstellt für jede Crew eine manuelle Mission und sendet
    sie parallel via Bot (5 gleichzeitig). Returns Liste mit Status pro Crew."""
    text = payload.content.strip()
    if not text:
        raise HTTPException(400, "content darf nicht leer sein")
    if not payload.crew_ids:
        return []

    deadline_at = None
    if payload.deadline_minutes and payload.deadline_minutes > 0:
        deadline_at = datetime.utcnow() + timedelta(minutes=payload.deadline_minutes)
    schedule_at = _normalize_naive_utc(payload.scheduled_send_at)

    # Phase 1: Missions sequentiell anlegen + Names sammeln
    creations: list[dict] = []
    for cid in payload.crew_ids:
        crew = await session.get(Crew, cid)
        if not crew:
            creations.append({"crew_id": cid, "name": f"#{cid}", "mission": None,
                              "error": "Crew nicht gefunden"})
            continue
        mission = Mission(
            crew_id=crew.id,
            ai_provider="manual",
            ai_model="",
            prompt_used="",
            content_generated=text,
            content_final=text,
            discord_channel_id=crew.discord_channel_id,
            status=MissionStatus.DRAFT,
            deadline_at=deadline_at,
            scheduled_send_at=schedule_at,
        )
        session.add(mission)
        creations.append({"crew_id": cid, "name": crew.name, "mission": mission, "error": None})
    await session.commit()
    for entry in creations:
        if entry["mission"]:
            await session.refresh(entry["mission"])

    # Wenn Schedule: nicht jetzt senden, Bot picks up
    if schedule_at:
        return [
            {
                "crew_id": e["crew_id"], "name": e["name"],
                "ok": e["error"] is None,
                "mission_id": e["mission"].id if e["mission"] else None,
                "scheduled": True,
                "error": e["error"],
            }
            for e in creations
        ]

    # Phase 2: parallele Bot-Sends, max 5 gleichzeitig
    sem = asyncio.Semaphore(5)

    async def _send_one(entry: dict) -> dict:
        if entry["error"] is not None or entry["mission"] is None:
            return {
                "crew_id": entry["crew_id"], "name": entry["name"], "ok": False,
                "mission_id": None, "error": entry["error"] or "create failed",
            }
        m = entry["mission"]
        async with sem:
            try:
                async with httpx.AsyncClient(timeout=60.0) as cli:
                    r = await cli.post(
                        "http://127.0.0.1:8001/send", json={"mission_id": m.id}
                    )
                if r.status_code >= 400:
                    return {
                        "crew_id": entry["crew_id"], "name": entry["name"], "ok": False,
                        "mission_id": m.id, "error": f"Bot {r.status_code}: {r.text[:200]}",
                    }
                return {
                    "crew_id": entry["crew_id"], "name": entry["name"], "ok": True,
                    "mission_id": m.id, "error": None,
                }
            except Exception as exc:
                return {
                    "crew_id": entry["crew_id"], "name": entry["name"], "ok": False,
                    "mission_id": m.id, "error": str(exc),
                }

    return await asyncio.gather(*[_send_one(e) for e in creations])


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


RANKING_POINTS = {
    MissionStatus.APPROVED: 2,
    MissionStatus.REJECTED: -1,
    MissionStatus.CANCELLED: 0,
    MissionStatus.PENDING: 0,
    MissionStatus.DRAFT: 0,
}


@router.get("/ranking")
async def mission_ranking(
    since: datetime | None = None,
    crime_only: bool = True,
    session: AsyncSession = Depends(get_session),
):
    """Performance-Ranking pro Crew + Stadtteil-Aggregat.

    Punkte: approved=+2, rejected=-1, cancelled/pending/draft=0.
    Bei crime_only=true werden Crews aus FIRMS_TO_CREATE ausgeschlossen
    (13 Zivil-Firmen werden nicht gerankt)."""
    # Lokaler Import um circular-import zu vermeiden (FIRMS_TO_CREATE liegt im
    # seed-Skript). Sicher, da seed_event_lore.py keine Bot/Backend-Routen importiert.
    from .seed_event_lore import FIRMS_TO_CREATE
    firm_names = {name for name, _district in FIRMS_TO_CREATE}

    # Alle Crews laden (fuer Metadata wie name/district/color_hex)
    crews_result = await session.execute(select(Crew).order_by(Crew.id))
    crews: list[Crew] = list(crews_result.scalars().all())

    if crime_only:
        crews = [c for c in crews if c.name not in firm_names]

    crew_ids = [c.id for c in crews]
    if not crew_ids:
        return {
            "crews": [],
            "districts": [],
            "since": since.isoformat() if since else None,
            "crime_only": crime_only,
        }

    # Counts pro (crew_id, status) aggregieren
    q = (
        select(Mission.crew_id, Mission.status, func.count(Mission.id))
        .where(Mission.crew_id.in_(crew_ids))
        .group_by(Mission.crew_id, Mission.status)
    )
    if since is not None:
        q = q.where(Mission.created_at >= since)
    rows = (await session.execute(q)).all()

    # In dict[crew_id] = {status: count, ...}
    by_crew: dict[int, dict[str, int]] = {
        cid: {s.value: 0 for s in MissionStatus} for cid in crew_ids
    }
    for crew_id, status, count in rows:
        key = status.value if hasattr(status, "value") else str(status)
        by_crew[crew_id][key] = count

    crew_entries: list[dict] = []
    for c in crews:
        counts = by_crew[c.id]
        approved = counts.get(MissionStatus.APPROVED.value, 0)
        rejected = counts.get(MissionStatus.REJECTED.value, 0)
        cancelled = counts.get(MissionStatus.CANCELLED.value, 0)
        pending = counts.get(MissionStatus.PENDING.value, 0)
        draft = counts.get(MissionStatus.DRAFT.value, 0)
        points = approved * 2 + rejected * -1
        total = approved + rejected + cancelled + pending + draft
        crew_entries.append({
            "crew_id": c.id,
            "name": c.name,
            "district": c.district or "",
            "color_hex": c.color_hex,
            "approved": approved,
            "rejected": rejected,
            "cancelled": cancelled,
            "pending": pending,
            "total": total,
            "points": points,
        })
    crew_entries.sort(key=lambda e: (-e["points"], -e["approved"], e["name"]))

    # Stadtteil-Aggregat
    district_acc: dict[str, dict[str, int]] = {}
    for e in crew_entries:
        d = e["district"] or "(ohne)"
        bucket = district_acc.setdefault(d, {
            "name": d, "points": 0, "approved": 0, "rejected": 0,
            "cancelled": 0, "pending": 0, "crew_count": 0,
        })
        bucket["points"] += e["points"]
        bucket["approved"] += e["approved"]
        bucket["rejected"] += e["rejected"]
        bucket["cancelled"] += e["cancelled"]
        bucket["pending"] += e["pending"]
        bucket["crew_count"] += 1
    district_entries = list(district_acc.values())
    district_entries.sort(key=lambda e: (-e["points"], -e["approved"], e["name"]))

    return {
        "crews": crew_entries,
        "districts": district_entries,
        "since": since.isoformat() if since else None,
        "crime_only": crime_only,
    }


@router.get("/stats")
async def mission_stats(
    crew_id: int | None = None,
    district: str | None = None,
    since: datetime | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Reaktions-Aggregat: Anzahl Missions je Status, optional gefiltert nach
    Crew, Stadtteil und Zeitfenster (created_at >= since). Archivierte werden mitgezählt."""
    q = select(Mission.status, func.count(Mission.id)).group_by(Mission.status)
    if crew_id is not None:
        q = q.where(Mission.crew_id == crew_id)
    if district:
        q = q.join(Crew, Crew.id == Mission.crew_id).where(Crew.district == district)
    if since is not None:
        q = q.where(Mission.created_at >= since)
    res = await session.execute(q)
    counts = {s.value: 0 for s in MissionStatus}
    for status, count in res.all():
        key = status.value if hasattr(status, "value") else str(status)
        counts[key] = count
    counts["total"] = sum(counts.values())
    return counts


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
    data = payload.model_dump(exclude_unset=True)
    clear_schedule = data.pop("clear_scheduled_send_at", False)
    if clear_schedule:
        m.scheduled_send_at = None
    if "scheduled_send_at" in data:
        m.scheduled_send_at = _normalize_naive_utc(data.pop("scheduled_send_at"))
    for k, v in data.items():
        setattr(m, k, v)
    await session.commit()
    await session.refresh(m)
    return m


@router.post("/{mission_id}/rewrite", response_model=MissionOut)
async def rewrite_existing_mission(
    mission_id: int, session: AsyncSession = Depends(get_session)
):
    """Schreibt den aktuellen Draft-Text durch einen neuen KI-Wurf. Nutzt
    content_final als Roh-Input + Crew-Story als Kontext."""
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    if m.status != MissionStatus.DRAFT:
        raise HTTPException(409, "Nur DRAFT-Missions können umformuliert werden")

    crew = await session.get(Crew, m.crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")

    current_text = (m.content_final or m.content_generated or "").strip()
    if not current_text:
        raise HTTPException(400, "Kein Text zum Umformulieren vorhanden")

    keys = {
        "anthropic": await settings_get(session, "anthropic_api_key", settings.anthropic_api_key),
        "openai": await settings_get(session, "openai_api_key", settings.openai_api_key),
    }
    models = {
        "claude": await settings_get(session, "default_claude_model", settings.default_claude_model),
        "openai": await settings_get(session, "default_openai_model", settings.default_openai_model),
    }
    provider_name = m.ai_provider if m.ai_provider in ("anthropic", "openai") else (
        await settings_get(session, "default_provider", settings.default_ai_provider)
    )
    provider = await get_provider(provider_name, keys=keys, models=models)

    ctx = await _load_context(session, crew, "")
    user_prompt = build_rewrite_prompt(ctx, current_text)
    system_prompt_val = await _resolve_active_system_prompt(session)

    try:
        new_text = await provider.generate(
            user_prompt, model=m.ai_model or None, system_prompt=system_prompt_val
        )
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc

    m.content_generated = new_text
    m.content_final = new_text
    m.prompt_used = user_prompt
    m.ai_provider = provider.name
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

    async with httpx.AsyncClient(timeout=60.0) as cli:
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


@router.get("/{mission_id}/pdf")
async def mission_pdf(mission_id: int, session: AsyncSession = Depends(get_session)):
    """Erzeugt ein PDF mit Auftragstext, Bild und archiviertem Boss-Feedback."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, HRFlowable,
    )

    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    crew = await session.get(Crew, m.crew_id)
    crew_name = crew.name if crew else "Unbekannt"

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title=f"Auftrag {mission_id} — {crew_name}",
    )
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle("body", parent=styles["Normal"], fontSize=11, leading=15)
    boss_meta = ParagraphStyle(
        "bossMeta", parent=styles["Normal"], fontSize=9,
        textColor=colors.grey, leading=12,
    )

    story = []
    story.append(Paragraph(f"<b>{crew_name}</b>", styles["Title"]))
    status_label = {
        "approved": "👍 Erledigt", "rejected": "👎 Fehlgeschlagen",
        "cancelled": "❌ Nicht durchführbar", "pending": "⏳ Wartet",
        "draft": "Entwurf",
    }.get(m.status.value, m.status.value)
    meta_parts = [f"<b>Status:</b> {status_label}"]
    if m.created_at:
        meta_parts.append(f"<b>Erstellt:</b> {m.created_at.strftime('%d.%m.%Y %H:%M')}")
    if m.sent_at:
        meta_parts.append(f"<b>Gesendet:</b> {m.sent_at.strftime('%d.%m.%Y %H:%M')}")
    if m.deadline_at:
        meta_parts.append(f"<b>Deadline:</b> {m.deadline_at.strftime('%d.%m.%Y %H:%M')}")
    story.append(Paragraph(" &nbsp; · &nbsp; ".join(meta_parts), boss_meta))
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 10))

    content = (m.content_final or m.content_generated or "").strip()
    if content:
        for para in content.split("\n\n"):
            story.append(Paragraph(para.replace("\n", "<br/>"), body_style))
            story.append(Spacer(1, 8))

    if m.image_path:
        img_path = Path(m.image_path)
        if img_path.exists():
            try:
                img = RLImage(str(img_path))
                ratio = img.imageHeight / img.imageWidth if img.imageWidth else 0.6
                target_w = 12 * cm
                img.drawWidth = target_w
                img.drawHeight = target_w * ratio
                story.append(Spacer(1, 8))
                story.append(img)
                story.append(Spacer(1, 8))
            except Exception:
                pass

    if m.archived_boss_info:
        try:
            boss_msgs = json.loads(m.archived_boss_info)
        except (json.JSONDecodeError, TypeError):
            boss_msgs = []
        if boss_msgs:
            story.append(Spacer(1, 12))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
            story.append(Spacer(1, 8))
            story.append(Paragraph("<b>Boss-Feedback aus Zusatzinfo-Channel</b>", styles["Heading3"]))
            story.append(Spacer(1, 6))
            for bm in boss_msgs:
                author = (bm.get("author") or "").replace("<", "&lt;").replace(">", "&gt;")
                posted = bm.get("posted_at") or ""
                try:
                    posted_fmt = datetime.fromisoformat(posted).strftime("%d.%m.%Y %H:%M")
                except (ValueError, TypeError):
                    posted_fmt = posted
                story.append(Paragraph(f"<b>{author}</b> &nbsp; <font size=9 color='#888'>{posted_fmt}</font>", body_style))
                content_text = (bm.get("content") or "").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
                story.append(Paragraph(content_text, body_style))
                story.append(Spacer(1, 8))

    doc.build(story)
    buf.seek(0)

    safe_crew = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in crew_name)
    filename = f"auftrag_{mission_id}_{safe_crew}.pdf"
    return Response(
        content=buf.read(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

    # Boss-Texte aus Zusatzinfo-Channel + Versager-Reply zusammen archivieren:
    # erst snapshotten (in m.archived_boss_info), dann aus Discord löschen.
    kept: list[dict] = []
    before_iso: str | None = None

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
            async with httpx.AsyncClient(timeout=15.0) as cli:
                r = await cli.post(
                    "http://127.0.0.1:8001/read_channel",
                    json={
                        "channel_id": crew.info_channel_id,
                        "after_iso": m.sent_at.isoformat(),
                        "limit": 100,
                    },
                )
            if r.status_code < 400:
                all_msgs = r.json()
                end_dt = datetime.fromisoformat(before_iso) if before_iso else None
                for bm in all_msgs:
                    try:
                        ts = datetime.fromisoformat(bm["posted_at"])
                    except (KeyError, ValueError):
                        continue
                    if end_dt and ts >= end_dt:
                        continue
                    kept.append(bm)
        except Exception:
            pass  # Bot offline -> nichts archiviert, weiter

    # Versager-Reply mit ins Archiv aufnehmen (auch ohne info_channel_id)
    if m.expiry_text:
        kept.append({
            "author": "⏳ Deadline",
            "content": m.expiry_text,
            "posted_at": (m.reacted_at or datetime.utcnow()).isoformat(),
            "message_id": m.expiry_message_id or "",
        })

    # Reaktions-Antwort mit ins Archiv aufnehmen
    if m.reaction_reply_text:
        kept.append({
            "author": "💬 Reaktions-Antwort",
            "content": m.reaction_reply_text,
            "posted_at": (m.reacted_at or datetime.utcnow()).isoformat(),
            "message_id": m.reaction_reply_message_id or "",
        })

    if kept:
        m.archived_boss_info = json.dumps(kept, ensure_ascii=False)

    # Boss-Texte aus Info-Channel löschen
    if crew and crew.info_channel_id and m.sent_at:
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
            pass  # Bot offline -> weiter

    # Original-Auftrags-Message + Versager-Reply + Reaktions-Antwort löschen
    if m.discord_channel_id:
        for msg_id in filter(None, [m.discord_message_id, m.expiry_message_id, m.reaction_reply_message_id]):
            try:
                async with httpx.AsyncClient(timeout=15.0) as cli:
                    await cli.post(
                        "http://127.0.0.1:8001/delete_message",
                        json={
                            "channel_id": m.discord_channel_id,
                            "message_id": msg_id,
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
