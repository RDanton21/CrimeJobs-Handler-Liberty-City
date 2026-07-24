"""Personal-Slots: Spieler-NPC-Slots pro Mission.

Admin-Endpoints (Dashboard): KI-Parse des Personal-Briefs, Slots lesen /
ersetzen / loeschen, Slot-Counts fuer das Missions-Badge.

Public-Endpoints (/api/public/*): read-only fuer das externe Jobs-Dashboard,
Auth ueber Header X-API-Key == Env-Var JOBS_API_KEY.
"""

import json
import logging
import os
import re
import secrets
from calendar import monthrange
from datetime import date, datetime, time as dtime, timedelta, timezone

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


async def _delete_announce_message(session: AsyncSession, message_id: str) -> None:
    """Loescht eine Ankuendigung im Jobs-Announce-Channel. Fehler werden nur
    geloggt — eine verwaiste Nachricht darf keinen Aufruf scheitern lassen."""
    if not message_id:
        return
    channel_id = (
        await settings_get_value(session, "jobs_announce_channel_id", "")
    ).strip()
    if not channel_id:
        return
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            await cli.post(
                f"{settings.bot_api_url}/delete_message",
                json={"channel_id": channel_id, "message_id": message_id},
            )
    except Exception as exc:
        log.warning("Announce-Message %s nicht loeschbar: %s", message_id, exc)


def _last_sunday(year: int, month: int) -> date:
    """Letzter Sonntag eines Monats (fuer die EU-Sommerzeit-Regel)."""
    d = date(year, month, monthrange(year, month)[1])
    return d - timedelta(days=(d.weekday() - 6) % 7)


def _berlin_offset(naive_local: datetime) -> timedelta:
    """UTC-Offset von Europe/Berlin fuer eine naive lokale Zeit.

    Bevorzugt zoneinfo; auf dem Dedicated (Windows ohne tzdata) faellt es
    auf die EU-Regel zurueck: Sommerzeit vom letzten Sonntag im Maerz 02:00
    bis zum letzten Sonntag im Oktober 03:00.
    """
    try:
        from zoneinfo import ZoneInfo

        off = naive_local.replace(tzinfo=ZoneInfo("Europe/Berlin")).utcoffset()
        if off is not None:
            return off
    except Exception:
        pass
    y = naive_local.year
    start = datetime.combine(_last_sunday(y, 3), dtime(2, 0))
    end = datetime.combine(_last_sunday(y, 10), dtime(3, 0))
    return timedelta(hours=2) if start <= naive_local < end else timedelta(hours=1)


def _slot_window_unix(mission: Mission, slot_window: str) -> tuple[int | None, int | None]:
    """(start, ende) des Einsatzfensters als Unix-Zeit.

    Aus "23:00-01:00" wird Start 23:00 und Ende 01:00 des Folgetags — ein
    Ende, das vor dem Start liegt, gilt also als ueber Mitternacht. Ohne
    zweite Uhrzeit endet das Fenster 2 Stunden nach dem Start (Annahme, damit
    das Board "laeuft gerade" ueberhaupt beenden kann).
    """
    start = _slot_start_unix(mission, slot_window)
    if start is None:
        return None, None
    times = re.findall(r"(\d{1,2})[:.](\d{2})", slot_window or "")
    if len(times) >= 2:
        h, m = int(times[1][0]), int(times[1][1])
        if h <= 23 and m <= 59:
            start_dt = datetime.fromtimestamp(start, timezone.utc).replace(tzinfo=None)
            start_local = start_dt + _berlin_offset(start_dt)
            end_local = start_local.replace(hour=h, minute=m, second=0, microsecond=0)
            # Ende rechnerisch vor dem Start -> das Fenster geht ueber Mitternacht
            if end_local <= start_local:
                end_local += timedelta(days=1)
            end_dt = end_local - _berlin_offset(end_local)
            return start, int(end_dt.replace(tzinfo=timezone.utc).timestamp())
    # Ohne zweite Uhrzeit: 2 Stunden annehmen, damit das Fenster endlich ist
    return start, start + int(timedelta(hours=2).total_seconds())


def _slot_start_unix(mission: Mission, slot_window: str) -> int | None:
    """Unix-Timestamp fuer den Beginn des Einsatzes.

    Das Datum stammt aus dem Missions-Slot (geplanter/erfolgter Versand),
    die Uhrzeit aus dem Zeitfenster-Text ("21:30-23:00" -> 21:30). Beides
    wird als Europe/Berlin interpretiert (RP-Zeit) und nach UTC gerechnet.
    Liegt keine brauchbare Uhrzeit vor: None (dann ohne Countdown posten).
    """
    m = re.search(r"(\d{1,2})[:.](\d{2})", slot_window or "")
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None

    base_utc = mission.scheduled_send_at or mission.sent_at or datetime.utcnow()
    # Bezugstag in Berliner Zeit bestimmen (Versand um 23:30 UTC = naechster Tag lokal)
    base_local = base_utc + _berlin_offset(base_utc)
    start_local = base_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # Nacht-Fenster: Start deutlich vor dem Versand -> gilt der Folgetag
    if (base_local - start_local) > timedelta(hours=6):
        start_local += timedelta(days=1)
    start_utc = start_local - _berlin_offset(start_local)
    return int(start_utc.replace(tzinfo=timezone.utc).timestamp())


async def _announce_slot_change(
    session: AsyncSession,
    mission: Mission,
    old_total: int,
    new_total: int,
    slot_window: str,
) -> tuple[bool, str | None, str]:
    """Postet den Ankündigungs-Ping via Bot-HTTP-API (/post_announce).
    Nur aufrufen wenn die Kapazität gestiegen ist. Returns
    (announce_sent, announce_error, message_id) — wirft NIE, damit das
    Slot-Speichern nicht am Discord-Ping scheitern kann."""
    channel_id = (
        await settings_get_value(session, "jobs_announce_channel_id", "")
    ).strip()
    if not channel_id:
        return False, None, ""  # Ping deaktiviert (kein Channel konfiguriert)

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

    # Beginn als Discord-Timestamp: <t:X:F> = "Fr., 7. Aug. 2026 21:30",
    # <t:X:R> = Countdown ("in 3 Stunden"). Discord rendert beides in der
    # lokalen Zeitzone des jeweiligen Spielers.
    start_unix = _slot_start_unix(mission, slot_window)
    if start_unix:
        when_line = f"🕘 **Beginn:** <t:{start_unix}:F> (<t:{start_unix}:R>)"
    elif slot_window:
        when_line = f"🕘 **Zeitfenster:** {slot_window}"
    else:
        when_line = ""

    if old_total == 0:
        # Erstmal-Fall: Mission bekommt zum ersten Mal Spieler-Slots
        head = f"📋 **Neuer Auftrag mit Personal-Bedarf — {crew_name}**"
        info = f"{new_total} offene Plätze"
    else:
        # Erhöhungs-Fall: Gesamt-Kapazität ist gestiegen
        head = f"📋 **Personal-Update — {crew_name}**"
        info = f"Jetzt {new_total} statt {old_total} Plätze"

    lines = [f"{mention}{head}", info]
    if when_line:
        lines.append(when_line)
    lines.append(f"👉 {dashboard_url}")
    content = "\n".join(lines)

    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(
                f"{settings.bot_api_url}/post_announce",
                json={"channel_id": channel_id, "content": content},
            )
    except Exception as exc:
        return False, f"Bot nicht erreichbar: {exc}", ""
    if r.status_code >= 400:
        return False, f"Bot {r.status_code}: {r.text[:200]}", ""
    try:
        msg_id = str((r.json() or {}).get("message_id") or "")
    except Exception:
        msg_id = ""
    return True, None, msg_id


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
            announce_sent, announce_error, announce_msg_id = await _announce_slot_change(
                session, mission, old_total, new_total, announce_window
            )
            if announce_msg_id:
                # Vorherige Ankuendigung derselben Mission entfernen, damit im
                # Channel immer nur der aktuelle Stand steht
                old_msg_id = (mission.jobs_announce_message_id or "").strip()
                if old_msg_id and old_msg_id != announce_msg_id:
                    await _delete_announce_message(session, old_msg_id)
                mission.jobs_announce_message_id = announce_msg_id
                await session.commit()
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


#: Wie lange ein archivierter Auftrag noch auf dem Board bleibt — er wird
#: dort als "Erledigt" markiert und verschwindet danach von selbst.
ARCHIVED_GRACE = timedelta(hours=1)


@public_router.get("/active-missions")
async def public_active_missions(session: AsyncSession = Depends(get_session)):
    """Missions mit >= 1 Personal-Slot — inkl. Crew-Infos und Slot-Liste.

    Archivierte Auftraege werden nicht sofort ausgeblendet, sondern bleiben
    noch ARCHIVED_GRACE lang sichtbar (Board zeigt sie als "Erledigt").
    Datetimes sind naive UTC als ISO.
    """
    cutoff = datetime.utcnow() - ARCHIVED_GRACE
    res = await session.execute(
        select(Mission)
        .join(PersonnelSlot, PersonnelSlot.mission_id == Mission.id)
        .where(
            (Mission.archived_at.is_(None)) | (Mission.archived_at > cutoff)
        )
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
        # Der Auftragstext wird erst mit dem Discord-Versand freigegeben
        # (sent_at gesetzt). Vorher steht der Personalbedarf schon auf dem
        # Board, damit die Leute sich melden koennen — aber der kryptische
        # Auftrag bleibt verborgen, sonst waere die Spannung weg.
        released = m.sent_at is not None
        content = (m.content_final or m.content_generated or "") if released else ""
        # Mission-weites Slot-Fenster: erstes nicht-leeres slot_window der Slots
        slot_window = next((s.slot_window for s in slots if s.slot_window), "")
        # Einsatzfenster als Unix-Zeit, damit das Board "laeuft gerade"
        # zuverlaessig erkennt (Zeitzonen-frei vergleichbar).
        win_start, win_end = _slot_window_unix(m, slot_window)
        out.append({
            "id": m.id,
            "status": m.status.value,
            "sent_at": _iso(m.sent_at),
            "scheduled_send_at": _iso(m.scheduled_send_at),
            "deadline_at": _iso(m.deadline_at),
            "archived_at": _iso(m.archived_at),
            "window_start": win_start,
            "window_end": win_end,
            "crew": {
                "id": m.crew.id,
                "name": m.crew.name,
                "district": m.crew.district or "",
                "color_hex": m.crew.color_hex or "",
            },
            "slot_window": slot_window,
            # briefing_released: false = Auftrag noch nicht gesendet, Board
            # zeigt statt des Textes einen "folgt beim Einsatz"-Hinweis.
            "briefing_released": released,
            # content = kompletter Auftragstext (das Board zeigt ihn aufgeklappt
            # vollstaendig). content_excerpt bleibt als Kurzform erhalten, damit
            # aeltere Dashboard-Versionen weiter funktionieren.
            "content": content,
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
