"""Dashboard-spezifische Endpoints — aktuell: Personal-Bedarf-Live-Feed.

Liefert eine ETag-versehene Liste von 'anstehenden' Missions (nächste 24h
geplant + bereits versandt aber noch nicht archiviert) mit ihren
Personal-Briefings. Das Frontend pollt diesen Endpoint alle ~30s und
zeigt eine Notification, wenn sich der ETag ändert.

Personal-Endpoint hier ausgelagert (statt im routes_missions.PATCH),
weil Personal-Planung auch NACH dem Versenden einer Mission noch änderbar
sein soll — der normale PATCH /missions/{id} blockiert nicht-DRAFT.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .ai import get_provider
from .auth import require_admin
from .config import settings as app_settings
from .db import get_session
from .models import Crew, Mission, MissionStatus
from .personnel_ai import TEMPLATES, generate_personnel_brief as ai_personnel_brief
from .settings_store import get as settings_get


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(require_admin)])


class PersonnelUpdate(BaseModel):
    personnel_brief: str


def _slot_for(m: Mission) -> datetime | None:
    """Bevorzugt scheduled_send_at (geplante Zukunft), fällt zurück auf sent_at."""
    return m.scheduled_send_at or m.sent_at or m.created_at


def _serialize_mission(m: Mission, crew: Crew | None, slot: datetime | None) -> dict:
    return {
        "mission_id": m.id,
        "crew_id": m.crew_id,
        "crew_name": crew.name if crew else "—",
        "crew_color_hex": crew.color_hex if crew else "#71717a",
        "crew_district": crew.district if crew else "",
        "slot": slot.isoformat() if slot else None,
        "status": m.status.value,
        "deadline_at": m.deadline_at.isoformat() if m.deadline_at else None,
        "personnel_brief": m.personnel_brief or "",
        "personnel_updated_at": (
            m.personnel_updated_at.isoformat() if m.personnel_updated_at else None
        ),
        "personnel_discord_message_id": m.personnel_discord_message_id or "",
        # Kurz-Snippet vom Auftragstext (für Kontext, kein Voll-Text)
        "content_snippet": (m.content_final or m.content_generated or "")[:140].strip(),
    }


def _format_slot_de(slot: datetime | None) -> str:
    if not slot:
        return "ohne Slot"
    return slot.strftime("%d.%m.%Y %H:%M") + " UTC"


def _hex_to_int(color_hex: str) -> int:
    """'#b91c1c' -> 12131356. Liefert Default-Rot bei ungültigem Input."""
    if not color_hex:
        return 0xB91C1C
    c = color_hex.strip().lstrip("#")
    try:
        return int(c, 16)
    except (ValueError, TypeError):
        return 0xB91C1C


@router.get("/personnel")
async def dashboard_personnel(
    response: Response,
    mode: str = "active",
    hours: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Liefert Missions mit Personal-Briefing.

    Modi:
      - mode='active' (Default): ALLE nicht-archivierten Missions
        (egal welches Datum). Sinnvoll für Vor-Event-Planung + laufenden
        Test, wenn noch keine zeitlich angesetzten Missions existieren.
      - mode='window': Zeitfenster-Modus (alte Logik). Mit `hours`
        (Default 24): nur Missions, deren Slot in [-1 h, +hours] liegt,
        plus aktive PENDING und kürzlich reagierte (~24 h).

    Response enthält ETag (Content-Hash) — Frontend nutzt das für
    effizientes Polling + Change-Detection für Notifications."""
    now = datetime.utcnow()

    # Alle nicht-archivierten Missions laden
    res = await session.execute(
        select(Mission).where(Mission.archived_at.is_(None))
    )
    candidates = list(res.scalars().all())

    items: list[dict] = []

    if mode == "active":
        # Default-Modus: alle aktiven Missions, egal welches Datum
        for m in candidates:
            slot = _slot_for(m)
            crew = await session.get(Crew, m.crew_id)
            items.append(_serialize_mission(m, crew, slot))
    else:
        # Zeitfenster-Modus
        h = max(1, min(hours or 24, 720))  # cap auf 30 Tage
        horizon = now + timedelta(hours=h)
        for m in candidates:
            slot = _slot_for(m)
            if slot is None:
                continue

            include = False
            if m.status == MissionStatus.PENDING:
                include = True
            elif m.status == MissionStatus.DRAFT and m.scheduled_send_at is not None:
                if now - timedelta(hours=1) <= m.scheduled_send_at <= horizon:
                    include = True
            elif m.status in (MissionStatus.APPROVED, MissionStatus.REJECTED):
                ref = m.reacted_at or m.sent_at
                if ref and (now - ref) <= timedelta(hours=24):
                    include = True

            if not include:
                continue

            crew = await session.get(Crew, m.crew_id)
            items.append(_serialize_mission(m, crew, slot))

    # Sortierung: erst Missions mit Slot (chronologisch), dann ohne Slot
    items.sort(key=lambda it: (it["slot"] is None, it["slot"] or ""))

    payload = {
        "items": items,
        "count": len(items),
        "mode": mode,
        "horizon_hours": hours if mode != "active" else None,
        "generated_at": now.isoformat(),
    }

    # ETag = Hash über die Personal-relevanten Felder. Stabil bei
    # gleichem Personal-Stand, ändert sich bei jeder Änderung.
    hash_basis = json.dumps(
        [
            {
                "id": it["mission_id"],
                "slot": it["slot"],
                "status": it["status"],
                "pb": it["personnel_brief"],
                "pu": it["personnel_updated_at"],
            }
            for it in items
        ],
        sort_keys=True,
    )
    etag = hashlib.sha256(hash_basis.encode("utf-8")).hexdigest()[:16]
    payload["etag"] = etag
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-store"

    return payload


@router.patch("/missions/{mission_id}/personnel")
async def update_personnel(
    mission_id: int,
    payload: PersonnelUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Setzt das personnel_brief einer Mission — funktioniert auch für
    Missions, die schon versandt sind (anders als der reguläre
    PATCH /missions/{id}, der nur DRAFT erlaubt). Stempelt
    personnel_updated_at, damit das Dashboard die Änderung erkennt."""
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    new_brief = (payload.personnel_brief or "").strip()
    if (m.personnel_brief or "") != new_brief:
        m.personnel_brief = new_brief
        m.personnel_updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(m)
    return {
        "ok": True,
        "mission_id": m.id,
        "personnel_brief": m.personnel_brief,
        "personnel_updated_at": (
            m.personnel_updated_at.isoformat() if m.personnel_updated_at else None
        ),
    }


@router.get("/personnel/templates")
async def list_personnel_templates():
    """Liefert die vordefinierten Personnel-Brief-Templates (Tag 2/4/7/9/10
    plus Leer-Vorlage) für den Quick-Pick-Dropdown im Edit-Modus."""
    return {"templates": TEMPLATES}


@router.post("/missions/{mission_id}/personnel/ai-suggest")
async def ai_suggest_personnel(
    mission_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Lässt die KI einen Personnel-Brief-Vorschlag für eine bestehende
    Mission generieren — überschreibt das Feld nicht direkt, sondern
    returnt den Vorschlag, damit der User ihn vorab prüfen kann."""
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    crew = await session.get(Crew, m.crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")

    keys = {
        "anthropic": await settings_get(session, "anthropic_api_key", app_settings.anthropic_api_key),
        "openai": await settings_get(session, "openai_api_key", app_settings.openai_api_key),
    }
    models = {
        "claude": await settings_get(session, "default_claude_model", app_settings.default_claude_model),
        "openai": await settings_get(session, "default_openai_model", app_settings.default_openai_model),
    }
    provider_name = await settings_get(session, "default_provider", app_settings.default_ai_provider)

    try:
        provider = await get_provider(provider_name, keys=keys, models=models)
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc

    mission_text = m.content_final or m.content_generated or ""
    suggestion = await ai_personnel_brief(
        provider, mission_text, crew.name, crew.district or ""
    )
    if not suggestion:
        raise HTTPException(502, "KI hat keinen Vorschlag generiert — bitte erneut versuchen")
    return {"suggestion": suggestion}


@router.post("/missions/{mission_id}/personnel/post")
async def post_personnel_to_discord(
    mission_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Postet das Personal-Briefing einer Mission als Discord-Embed im
    Admin-Channel (Settings: personnel_admin_channel_id). Falls bereits
    eine vorherige Message existiert (personnel_discord_message_id), wird
    sie zuerst gelöscht — so steht immer nur der aktuellste Brief im Channel
    (Replace-Previous-Pattern wie beim Ranking-Post)."""
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    crew = await session.get(Crew, m.crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")

    if not (m.personnel_brief or "").strip():
        raise HTTPException(400, "Mission hat keinen Personal-Brief. Erst speichern, dann posten.")

    # Idempotent: pro Mission GENAU EINMAL posten. Wenn bereits eine Message-ID
    # gesetzt ist, bleibt der vorhandene Embed unangetastet — erst Archivieren
    # löscht ihn. Re-Posting nach manuellen Discord-Aenderungen vermeidet
    # ungewollte Dopplungen im Admin-Channel.
    if m.personnel_discord_message_id:
        raise HTTPException(
            409,
            "Personal-Bedarf für diese Mission wurde bereits gepostet. "
            "Erst Auftrag archivieren wenn ein neuer Stand gepostet werden soll."
        )

    channel_id = (await settings_get(session, "personnel_admin_channel_id", "")).strip()
    if not channel_id:
        raise HTTPException(
            400,
            "Kein Admin-Channel für Personal-Posts gesetzt. "
            "Bitte in den Settings 'personnel_admin_channel_id' eintragen."
        )

    slot = _slot_for(m)
    status_label = {
        "draft": "📝 geplant",
        "pending": "🔴 live",
        "approved": "✅ erledigt",
        "rejected": "❌ abgelehnt",
        "cancelled": "⏹ abgebrochen",
    }.get(m.status.value, m.status.value)

    embed_payload = {
        "title": f"🎭 Personal-Bedarf — {crew.name}",
        "description": m.personnel_brief.strip()[:4000],  # Discord-Limit
        "color": _hex_to_int(crew.color_hex),
        "fields": [
            {"name": "Slot (wann)", "value": _format_slot_de(slot), "inline": True},
            {"name": "Status", "value": status_label, "inline": True},
            {"name": "Stadtteil", "value": crew.district or "—", "inline": True},
        ],
        "footer": {"text": f"Mission #{m.id} · Crew {crew.name}"},
        "timestamp": (m.personnel_updated_at or datetime.utcnow()).isoformat(),
    }

    # Optional: Auftrags-Snippet als zusätzliches Feld, gekürzt
    snippet = (m.content_final or m.content_generated or "").strip()
    if snippet:
        embed_payload["fields"].append({
            "name": "Auftrag (Auszug)",
            "value": (snippet[:300] + "…") if len(snippet) > 300 else snippet,
            "inline": False,
        })

    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(
                f"{app_settings.bot_api_url}/send_embed",
                json={"channel_id": channel_id, "embed": embed_payload},
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Bot-Fehler: {exc.response.text}") from exc
    except Exception as exc:
        raise HTTPException(502, f"Bot nicht erreichbar: {exc}") from exc

    new_msg_id = str(data.get("message_id") or "")
    if new_msg_id:
        m.personnel_discord_message_id = new_msg_id
        await session.commit()

    return {
        "ok": True,
        "mission_id": m.id,
        "channel_id": channel_id,
        "message_id": new_msg_id,
    }
