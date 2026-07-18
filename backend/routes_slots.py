"""Personal-Slots: Spieler-NPC-Slots pro Mission.

Admin-Endpoints (Dashboard): KI-Parse des Personal-Briefs, Slots lesen /
ersetzen / loeschen, Slot-Counts fuer das Missions-Badge.

Public-Endpoints (/api/public/*): read-only fuer das externe Jobs-Dashboard,
Auth ueber Header X-API-Key == Env-Var JOBS_API_KEY.
"""

import json
import logging
import os
import secrets

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .ai import get_provider
from .auth import require_admin
from .config import settings
from .db import get_session
from .models import Crew, Mission, PersonnelSlot
from .prompts import (
    PERSONNEL_SLOT_PARSE_SYSTEM_PROMPT,
    build_personnel_slot_parse_prompt,
)
from .schemas import (
    PersonnelSlotIn,
    PersonnelSlotOut,
    SlotsParseSuggestion,
    SlotsSaveRequest,
    SlotsSaveResponse,
)
from .settings_store import get as settings_get_value

log = logging.getLogger("crime-slots")

router = APIRouter(tags=["slots"], dependencies=[Depends(require_admin)])


# ==================================================================
# Admin-Endpoints
# ==================================================================


@router.post("/api/missions/{mission_id}/parse-slots", response_model=SlotsParseSuggestion)
async def parse_slots(mission_id: int, session: AsyncSession = Depends(get_session)):
    """Parst den Personal-Brief der Mission per KI in strukturierte Slots.
    Reine Vorschau — es wird NICHTS gespeichert. Der Admin prueft/editiert
    das Ergebnis im Slot-Editor und speichert dann via PUT .../slots."""
    mission = await session.get(Mission, mission_id)
    if not mission:
        raise HTTPException(404, "Mission nicht gefunden")
    brief = (mission.personnel_brief or "").strip()
    if not brief:
        raise HTTPException(400, "Kein Personal-Brief hinterlegt")

    # AI-Provider aufbauen (gleiche Konfiguration wie Mission-Generator)
    keys = {
        "anthropic": await settings_get_value(session, "anthropic_api_key", settings.anthropic_api_key),
        "openai": await settings_get_value(session, "openai_api_key", settings.openai_api_key),
    }
    models = {
        "claude": await settings_get_value(session, "default_claude_model", settings.default_claude_model),
        "openai": await settings_get_value(session, "default_openai_model", settings.default_openai_model),
    }
    provider_name = await settings_get_value(
        session, "default_provider", settings.default_ai_provider
    )
    provider = await get_provider(provider_name, keys=keys, models=models)

    user_prompt = build_personnel_slot_parse_prompt(brief)
    try:
        text = await provider.generate(
            user_prompt, system_prompt=PERSONNEL_SLOT_PARSE_SYSTEM_PROMPT
        )
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc

    # JSON parsen — inkl. Markdown-Fence-Stripping (gleiche Heuristik wie
    # enrich_crew_preview: erstes '{' bis letztes '}')
    raw = (text or "").strip()
    parsed: dict | None = None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(raw[start:end+1])
            except json.JSONDecodeError:
                parsed = None

    if parsed is None or not isinstance(parsed, dict):
        # Parse-Fehler: leere Suggestion + Roh-Antwort fuer Debug-Anzeige
        return SlotsParseSuggestion(slot_window="", slots=[], raw=raw)

    slot_window = str(parsed.get("slot_window", "") or "").strip()
    slots_out: list[PersonnelSlotIn] = []
    items = parsed.get("slots", [])
    if isinstance(items, list):
        for it in items[:30]:
            if not isinstance(it, dict):
                continue
            npc = it.get("npc_number")
            if not isinstance(npc, int) or isinstance(npc, bool):
                npc = None
            try:
                req = int(it.get("required_count", 1))
            except (TypeError, ValueError):
                req = 1
            if req < 1:
                req = 1
            slots_out.append(PersonnelSlotIn(
                npc_number=npc,
                name=str(it.get("name", "") or "").strip(),
                function=str(it.get("function", "") or "").strip(),
                location=str(it.get("location", "") or "").strip(),
                costume=str(it.get("costume", "") or "").strip(),
                required_count=req,
                slot_window=str(it.get("slot_window", "") or "").strip() or slot_window,
                notes=str(it.get("notes", "") or "").strip(),
            ))

    return SlotsParseSuggestion(slot_window=slot_window, slots=slots_out, raw="")


@router.get("/api/missions/{mission_id}/slots", response_model=list[PersonnelSlotOut])
async def list_slots(mission_id: int, session: AsyncSession = Depends(get_session)):
    mission = await session.get(Mission, mission_id)
    if not mission:
        raise HTTPException(404, "Mission nicht gefunden")
    res = await session.execute(
        select(PersonnelSlot)
        .where(PersonnelSlot.mission_id == mission_id)
        .order_by(PersonnelSlot.id)
    )
    return res.scalars().all()


async def _announce_slot_change(
    session: AsyncSession,
    mission: Mission,
    old_total: int,
    new_total: int,
    slot_window: str,
) -> tuple[bool, str | None]:
    """Postet den Ankündigungs-Ping via Bot-HTTP-API (/post_announce).
    Nur aufrufen wenn die Kapazität gestiegen ist. Returns
    (announce_sent, announce_error) — wirft NIE, damit das Slot-Speichern
    nicht am Discord-Ping scheitern kann."""
    channel_id = (
        await settings_get_value(session, "jobs_announce_channel_id", "")
    ).strip()
    if not channel_id:
        return False, None  # Ping deaktiviert (kein Channel konfiguriert)

    role_id = (
        await settings_get_value(session, "jobs_ping_role_id", "1528099740649127977")
    ).strip()
    dashboard_url = (
        await settings_get_value(
            session, "jobs_dashboard_url", "https://jobs.bots.sektorrp.eu"
        )
    ).strip()

    crew = await session.get(Crew, mission.crew_id)
    crew_name = crew.name if crew else f"Crew #{mission.crew_id}"
    mention = f"<@&{role_id}> " if role_id else ""

    if old_total == 0:
        # Erstmal-Fall: Mission bekommt zum ersten Mal Spieler-Slots
        line2 = f"{new_total} offene Plätze"
        if slot_window:
            line2 += f" · {slot_window}"
        content = (
            f"{mention}📋 **Neuer Auftrag mit Personal-Bedarf — {crew_name}**\n"
            f"{line2}\n"
            f"👉 {dashboard_url}"
        )
    else:
        # Erhöhungs-Fall: Gesamt-Kapazität ist gestiegen
        content = (
            f"{mention}📋 **Personal-Update — {crew_name}**\n"
            f"Jetzt {new_total} statt {old_total} Plätze\n"
            f"👉 {dashboard_url}"
        )

    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(
                f"{settings.bot_api_url}/post_announce",
                json={"channel_id": channel_id, "content": content},
            )
    except Exception as exc:
        return False, f"Bot nicht erreichbar: {exc}"
    if r.status_code >= 400:
        return False, f"Bot {r.status_code}: {r.text[:200]}"
    return True, None


@router.put("/api/missions/{mission_id}/slots", response_model=SlotsSaveResponse)
async def save_slots(
    mission_id: int,
    payload: SlotsSaveRequest,
    session: AsyncSession = Depends(get_session),
):
    """Speichert die Slots der Mission als Upsert.

    Slots mit mitgeschickter id werden AKTUALISIERT (die Row behaelt ihre id),
    Slots ohne id neu angelegt, nicht mehr enthaltene Rows geloescht. Wichtig:
    das Jobs-Dashboard referenziert Spieler-Eintragungen ueber die Slot-id —
    ein delete+insert wuerde bei jeder Bearbeitung (z.B. Anzahl 3 -> 4) alle
    Anmeldungen verwaisen lassen.

    payload.slot_window wird auf jede Row geschrieben; ist es leer, bleibt
    das slot_window des einzelnen Slots erhalten.

    Discord-Ankündigung: wenn payload.announce UND jobs_announce_channel_id
    gesetzt UND die Gesamt-Kapazität (Summe required_count) steigt (inkl.
    Erstmal-Fall 0 -> N), pingt der Bot die Spieler-Rolle im konfigurierten
    Channel. Ping-Fehler blockieren das Speichern NIE."""
    mission = await session.get(Mission, mission_id)
    if not mission:
        raise HTTPException(404, "Mission nicht gefunden")

    res = await session.execute(
        select(PersonnelSlot).where(PersonnelSlot.mission_id == mission_id)
    )
    old_rows = list(res.scalars().all())
    by_id = {o.id: o for o in old_rows}
    # Alte Gesamt-Kapazität VOR dem Speichern (für die Announce-Entscheidung)
    old_total = sum(max(1, int(o.required_count or 1)) for o in old_rows)

    window = (payload.slot_window or "").strip()
    result_rows: list[PersonnelSlot] = []
    fresh_rows: list[PersonnelSlot] = []
    kept_ids: set[int] = set()

    for s in payload.slots:
        values = {
            "npc_number": s.npc_number,
            "name": (s.name or "").strip(),
            "function": (s.function or "").strip(),
            "location": (s.location or "").strip(),
            "costume": (s.costume or "").strip(),
            "required_count": max(1, int(s.required_count or 1)),
            "slot_window": window or (s.slot_window or "").strip(),
            "notes": (s.notes or "").strip(),
        }
        existing = by_id.get(s.id) if s.id else None
        if existing is not None:
            for key, val in values.items():
                setattr(existing, key, val)
            kept_ids.add(existing.id)
            result_rows.append(existing)
        else:
            row = PersonnelSlot(mission_id=mission_id, **values)
            session.add(row)
            fresh_rows.append(row)
            result_rows.append(row)

    # Nicht mehr enthaltene Slots entfernen
    for old in old_rows:
        if old.id not in kept_ids:
            await session.delete(old)

    await session.commit()
    for row in result_rows:
        await session.refresh(row)
    new_rows = result_rows

    # ---- Optionaler Discord-Ankündigungs-Ping (nie blockierend) ----
    new_total = sum(row.required_count or 1 for row in new_rows)
    announce_sent = False
    announce_error: str | None = None
    # Bedingung: (alt == 0 UND neu > 0) ODER neu > alt — beides deckt
    # "new_total > old_total" ab (Erstmal-Fall + Erhöhung).
    if payload.announce and new_total > old_total:
        try:
            announce_window = window or next(
                (row.slot_window for row in new_rows if row.slot_window), ""
            )
            announce_sent, announce_error = await _announce_slot_change(
                session, mission, old_total, new_total, announce_window
            )
        except Exception as exc:
            announce_error = str(exc)
        if announce_error:
            log.warning(
                "Slot-Announce fehlgeschlagen (Mission %s): %s",
                mission_id, announce_error,
            )

    return SlotsSaveResponse(
        slots=new_rows, announce_sent=announce_sent, announce_error=announce_error
    )


@router.delete("/api/slots/{slot_id}", status_code=204)
async def delete_slot(slot_id: int, session: AsyncSession = Depends(get_session)):
    slot = await session.get(PersonnelSlot, slot_id)
    if not slot:
        raise HTTPException(404, "Slot nicht gefunden")
    await session.delete(slot)
    await session.commit()


@router.get("/api/slots/counts")
async def slot_counts(
    crew_id: int | None = None, session: AsyncSession = Depends(get_session)
):
    """Slot-Anzahl pro Mission in EINEM Call (fuers 🧩-Badge im Frontend,
    kein N+1). Optional per crew_id gefiltert.
    Response: {"counts": {"<mission_id>": <anzahl_slot_rows>}}"""
    q = (
        select(PersonnelSlot.mission_id, func.count(PersonnelSlot.id))
        .group_by(PersonnelSlot.mission_id)
    )
    if crew_id is not None:
        q = q.join(Mission, Mission.id == PersonnelSlot.mission_id).where(
            Mission.crew_id == crew_id
        )
    res = await session.execute(q)
    return {"counts": {str(mid): cnt for mid, cnt in res.all()}}


# ==================================================================
# Public-API fuer das externe Jobs-Dashboard (X-API-Key-Auth)
# ==================================================================


async def require_jobs_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key")
) -> None:
    """Auth fuer die Public-API: Header X-API-Key muss exakt der Env-Var
    JOBS_API_KEY entsprechen. Env nicht gesetzt/leer -> 503, Header
    fehlt/falsch -> 401."""
    # Docker setzt die Env-Var direkt; auf dem Dedicated (NSSM) kommt der
    # Wert ueber die .env-Datei -> Fallback auf settings.jobs_api_key.
    expected = os.getenv("JOBS_API_KEY", "") or settings.jobs_api_key
    if not expected:
        raise HTTPException(503, "public api nicht konfiguriert")
    # compare_digest statt '==': konstante Laufzeit gegen Timing-Angriffe
    if not x_api_key or not secrets.compare_digest(
        x_api_key.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(401, "ungueltiger API-Key")


public_router = APIRouter(
    prefix="/api/public", tags=["public"], dependencies=[Depends(require_jobs_api_key)]
)


def _iso(dt) -> str | None:
    """Naive-UTC-datetime als ISO-String (oder None)."""
    return dt.isoformat() if dt else None


@public_router.get("/active-missions")
async def public_active_missions(session: AsyncSession = Depends(get_session)):
    """Alle nicht-archivierten Missions, die >= 1 Personal-Slot haben —
    inkl. Crew-Infos und Slot-Liste. Datetimes sind naive UTC als ISO."""
    res = await session.execute(
        select(Mission)
        .join(PersonnelSlot, PersonnelSlot.mission_id == Mission.id)
        .where(Mission.archived_at.is_(None))
        .options(selectinload(Mission.crew))
        .distinct()
        .order_by(Mission.id)
    )
    missions = list(res.scalars().all())
    if not missions:
        return {"missions": []}

    # Alle Slots der gefundenen Missions in EINEM Query laden und gruppieren
    slot_res = await session.execute(
        select(PersonnelSlot)
        .where(PersonnelSlot.mission_id.in_([m.id for m in missions]))
        .order_by(PersonnelSlot.id)
    )
    slots_by_mission: dict[int, list[PersonnelSlot]] = {}
    for s in slot_res.scalars().all():
        slots_by_mission.setdefault(s.mission_id, []).append(s)

    out: list[dict] = []
    for m in missions:
        slots = slots_by_mission.get(m.id, [])
        content = m.content_final or m.content_generated or ""
        # Mission-weites Slot-Fenster: erstes nicht-leeres slot_window der Slots
        slot_window = next((s.slot_window for s in slots if s.slot_window), "")
        out.append({
            "id": m.id,
            "status": m.status.value,
            "sent_at": _iso(m.sent_at),
            "scheduled_send_at": _iso(m.scheduled_send_at),
            "deadline_at": _iso(m.deadline_at),
            "crew": {
                "id": m.crew.id,
                "name": m.crew.name,
                "district": m.crew.district or "",
                "color_hex": m.crew.color_hex or "",
            },
            "slot_window": slot_window,
            "content_excerpt": content[:300],
            "personnel_brief": m.personnel_brief or "",
            "slots": [
                {
                    "id": s.id,
                    "npc_number": s.npc_number,
                    "name": s.name or "",
                    "function": s.function or "",
                    "location": s.location or "",
                    "costume": s.costume or "",
                    "required_count": s.required_count or 1,
                    "slot_window": s.slot_window or "",
                    "notes": s.notes or "",
                }
                for s in slots
            ],
        })

    return {"missions": out}


@public_router.get("/crews")
async def public_crews(session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(Crew).order_by(Crew.name))
    return {
        "crews": [
            {
                "id": c.id,
                "name": c.name,
                "district": c.district or "",
                "color_hex": c.color_hex or "",
            }
            for c in res.scalars().all()
        ]
    }
