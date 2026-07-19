# -*- coding: utf-8 -*-
"""SEKTOR Personal-Boerse — FastAPI-App.

Spieler loggen sich mit Discord ein (nur Guild-Mitglieder mit REQUIRED_ROLE_ID),
sehen das 10-Tage-Event-Board mit allen Crime-Auftraegen die Personal-Slots haben
und tragen sich selbst in Slots ein/aus.

Datenquellen:
- Crime-Backend Public-API (X-API-Key) -> Missions + Crews, 15s-Cache
- eigene jobs.db (SQLite async)        -> Player + Slot-Belegungen
"""
import asyncio
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import delete, exists, func, select
from sqlalchemy.exc import IntegrityError

from . import config, discord_oauth
from .db import SessionLocal, init_db
from .models import (
    CompletedParticipation,
    DismissedMission,
    Player,
    SlotAssignment,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

SESSION_COOKIE = "jobs_session"
SESSION_MAX_AGE = 7 * 24 * 3600  # 7 Tage
STATE_COOKIE = "jobs_oauth_state"
STATE_MAX_AGE = 300  # 5 Minuten fuer den OAuth-Roundtrip

_session_serializer = URLSafeTimedSerializer(config.SESSION_SECRET, salt="jobs-session")
_state_serializer = URLSafeTimedSerializer(config.SESSION_SECRET, salt="jobs-oauth-state")

# Deutsche Wochentags-Kuerzel (Montag=0)
WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="SEKTOR Personal-Boerse", lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Basis-Security-Header fuer alle Responses (oeffentlich erreichbares
    Dashboard hinter Traefik). CSP ist wegen Tailwind-CDN + Alpine (eval)
    aktuell nicht sinnvoll setzbar — siehe README, Abschnitt Sicherheit."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


# ---------------------------------------------------------------------------
# Session-Helpers
# ---------------------------------------------------------------------------

def _read_session(request: Request) -> dict | None:
    """Signiertes Session-Cookie lesen; None wenn fehlt/abgelaufen/manipuliert."""
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        data = _session_serializer.loads(raw, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict) or not data.get("discord_user_id"):
        return None
    return data


def require_session(request: Request) -> dict:
    """Dependency: 401 ohne gueltige Session."""
    session = _read_session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="nicht eingeloggt")
    return session


def _set_session_cookie(response: Response, payload: dict) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        _session_serializer.dumps(payload),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
    )


def _error_page(title: str, message: str, status: int) -> HTMLResponse:
    """Kleine deutsche Fehlerseite im Dashboard-Look (dunkel, roter Akzent)."""
    html = f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title} — SEKTOR Personal-Börse</title>
  <style>
    body {{ margin: 0; min-height: 100vh; display: flex; align-items: center;
           justify-content: center; background: #09090b; color: #f4f4f5;
           font-family: system-ui, -apple-system, sans-serif; }}
    .card {{ background: #18181b; border: 1px solid #b91c1c; border-radius: 12px;
            padding: 2rem; max-width: 26rem; margin: 1rem; text-align: center; }}
    h1 {{ font-size: 1.25rem; margin: 0 0 .75rem; }}
    p {{ color: #a1a1aa; font-size: .9rem; line-height: 1.5; margin: 0 0 1.5rem; }}
    a {{ display: inline-block; padding: .6rem 1.4rem; border-radius: 8px;
        background: #b91c1c; color: #fff; text-decoration: none; font-weight: 600;
        font-size: .9rem; }}
    a:hover {{ background: #dc2626; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{title}</h1>
    <p>{message}</p>
    <a href="/">Zurück zur Startseite</a>
  </div>
</body>
</html>"""
    return HTMLResponse(html, status_code=status)


# ---------------------------------------------------------------------------
# Crime-Backend-Anbindung (mit 15s-In-Memory-Cache)
# ---------------------------------------------------------------------------

CACHE_TTL = 15.0
_crime_cache: dict = {"ts": 0.0, "missions": None, "crews": None}
_cache_lock = asyncio.Lock()


async def _fetch_crime_data() -> tuple[list, list]:
    """Missions + Crews vom Crime-Backend holen; Antworten 15s cachen."""
    if _crime_cache["missions"] is not None and time.monotonic() - _crime_cache["ts"] < CACHE_TTL:
        return _crime_cache["missions"], _crime_cache["crews"]
    async with _cache_lock:
        # Double-Check: waehrend des Wartens kann ein anderer Request gefuellt haben
        if _crime_cache["missions"] is not None and time.monotonic() - _crime_cache["ts"] < CACHE_TTL:
            return _crime_cache["missions"], _crime_cache["crews"]
        headers = {"X-API-Key": config.CRIME_API_KEY}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r_missions = await client.get(
                    f"{config.CRIME_BACKEND_URL}/api/public/active-missions", headers=headers
                )
                r_crews = await client.get(
                    f"{config.CRIME_BACKEND_URL}/api/public/crews", headers=headers
                )
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail="Crime-Backend nicht erreichbar")
        if r_missions.status_code != 200 or r_crews.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Crime-Backend antwortet mit Fehler "
                    f"(HTTP {r_missions.status_code}/{r_crews.status_code})"
                ),
            )
        try:
            missions = r_missions.json().get("missions", [])
            crews = r_crews.json().get("crews", [])
        except ValueError:
            # z.B. HTML-Fehlerseite eines Proxys mit Status 200 -> sauberer 502
            raise HTTPException(
                status_code=502, detail="Crime-Backend liefert ungültige Antwort"
            )
        _crime_cache.update({"ts": time.monotonic(), "missions": missions, "crews": crews})
        return missions, crews


# ---------------------------------------------------------------------------
# Board-Aufbau
# ---------------------------------------------------------------------------

def _event_days() -> list[tuple[date, int, str]]:
    """Alle Kalendertage aller Event-Zeitraeume (Europe/Berlin), inklusiv.

    Rueckgabe je Tag: (datum, perioden_index, perioden_label). Der Index
    erlaubt dem Frontend, zwischen zwei Zeitraeumen einen Trenner zu setzen.
    Ueberlappende Zeitraeume erzeugen keine Doppel-Tage.
    """
    days: list[tuple[date, int, str]] = []
    seen: set[date] = set()
    for idx, period in enumerate(config.EVENT_PERIODS):
        label = period.get("label", "")
        d = period["start"].date()
        last = period["end"].date()
        while d <= last:
            if d not in seen:
                seen.add(d)
                days.append((d, idx, label))
            d += timedelta(days=1)
    days.sort(key=lambda item: item[0])
    return days


def _mission_day(mission: dict) -> date | None:
    """Berlin-Kalendertag einer Mission: scheduled_send_at > sent_at > deadline_at."""
    ts = (
        mission.get("scheduled_send_at")
        or mission.get("sent_at")
        or mission.get("deadline_at")
    )
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=config.UTC_TZ)  # Backend liefert naive UTC
    return dt.astimezone(config.BERLIN_TZ).date()


def _enrich_mission(mission: dict, assignments_by_slot: dict, me: dict) -> dict:
    """Mission-Kopie mit Belegungsdaten pro Slot anreichern (Cache nie mutieren!)."""
    enriched = dict(mission)
    slots_out = []
    for slot in mission.get("slots", []):
        s = dict(slot)
        assigned = assignments_by_slot.get(slot.get("id"), [])
        s["assigned"] = [
            {"player_discord_id": a.player_discord_id, "username": a.username}
            for a in assigned
        ]
        s["assigned_count"] = len(assigned)
        required = slot.get("required_count") or 1
        s["free"] = max(required - len(assigned), 0)
        s["mine"] = any(a.player_discord_id == me["discord_user_id"] for a in assigned)
        slots_out.append(s)
    enriched["slots"] = slots_out
    return enriched


def _mission_sort_key(mission: dict) -> str:
    return (
        mission.get("scheduled_send_at")
        or mission.get("sent_at")
        or mission.get("deadline_at")
        or ""
    )


# ---------------------------------------------------------------------------
# Routen: Seite + Auth
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/static/bg.jpg")
async def static_bg():
    """Kino-Hintergrundbild. Bewusst Einzeldatei-Endpoint statt generischem
    StaticFiles-Mount (Security-Review: nur explizit freigegebene Dateien)."""
    return FileResponse(
        STATIC_DIR / "bg.jpg",
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/auth/login")
async def auth_login():
    """CSRF-State erzeugen, in signiertem Kurzzeit-Cookie ablegen, zu Discord."""
    state = secrets.token_urlsafe(32)
    response = RedirectResponse(discord_oauth.authorize_url(state))
    response.set_cookie(
        STATE_COOKIE,
        _state_serializer.dumps(state),
        max_age=STATE_MAX_AGE,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
    )
    return response


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return _error_page(
            "Anmeldung abgebrochen",
            "Die Discord-Anmeldung wurde abgebrochen. Du kannst es jederzeit erneut versuchen.",
            400,
        )

    # CSRF-State pruefen
    raw_state = request.cookies.get(STATE_COOKIE)
    expected = None
    if raw_state:
        try:
            expected = _state_serializer.loads(raw_state, max_age=STATE_MAX_AGE)
        except (BadSignature, SignatureExpired):
            expected = None
    if not state or expected != state:
        return _error_page(
            "Sicherheitsprüfung fehlgeschlagen",
            "Der Anmeldevorgang ist abgelaufen oder ungültig. Bitte starte den Login neu.",
            403,
        )

    if not code:
        return _error_page(
            "Anmeldung fehlgeschlagen",
            "Discord hat keinen Anmelde-Code geliefert. Bitte versuche es erneut.",
            400,
        )

    # Code tauschen, User + Guild-Member holen
    try:
        token = await discord_oauth.exchange_code(code)
        access_token = token.get("access_token", "")
        user = await discord_oauth.fetch_user(access_token)
    except discord_oauth.DiscordOAuthError:
        return _error_page(
            "Discord-Fehler",
            "Discord ist gerade nicht erreichbar oder hat die Anmeldung abgelehnt. "
            "Bitte versuche es in ein paar Minuten erneut.",
            502,
        )

    try:
        member = await discord_oauth.fetch_member(access_token, config.DISCORD_GUILD_ID)
    except discord_oauth.DiscordOAuthError as exc:
        if exc.status == 404:
            # Nicht auf dem SEKTOR-Server -> gleiche Meldung wie fehlende Rolle
            return _error_page(
                "Kein Zugang",
                "Dir fehlt die Berechtigung — melde dich bei der Projektleitung.",
                403,
            )
        return _error_page(
            "Discord-Fehler",
            "Deine Server-Mitgliedschaft konnte nicht geprüft werden. "
            "Bitte versuche es in ein paar Minuten erneut.",
            502,
        )

    if config.REQUIRED_ROLE_ID not in (member.get("roles") or []):
        return _error_page(
            "Kein Zugang",
            "Dir fehlt die Berechtigung — melde dich bei der Projektleitung.",
            403,
        )

    # Player upserten
    user_id = str(user.get("id", ""))
    username = discord_oauth.display_name(user, member)
    avatar = discord_oauth.avatar_url(user)

    # Admin-Status: Admin-Rolle auf dem Server ODER explizit gelistete User-ID.
    # Wird (wie der Rollen-Check) nur beim Login ermittelt — gilt fuer die Session.
    is_admin = (
        config.ADMIN_ROLE_ID in (member.get("roles") or [])
        or user_id in config.ADMIN_USER_IDS
    )
    async with SessionLocal() as session:
        player = await session.get(Player, user_id)
        if player is None:
            player = Player(discord_user_id=user_id)
            session.add(player)
        player.username = username
        player.avatar = avatar
        player.last_login = datetime.utcnow()
        await session.commit()

    response = RedirectResponse("/")
    _set_session_cookie(
        response,
        {
            "discord_user_id": user_id,
            "username": username,
            "avatar": avatar,
            "is_admin": is_admin,
        },
    )
    response.delete_cookie(STATE_COOKIE)
    return response


@app.get("/auth/logout")
async def auth_logout():
    response = RedirectResponse("/")
    response.delete_cookie(SESSION_COOKIE)
    return response


# ---------------------------------------------------------------------------
# Routen: API
# ---------------------------------------------------------------------------

@app.get("/api/me")
async def api_me(me: dict = Depends(require_session)):
    return {
        "discord_user_id": me["discord_user_id"],
        "username": me.get("username", ""),
        "avatar": me.get("avatar", ""),
        "is_admin": bool(me.get("is_admin")),
    }


async def _record_completed(missions: list[dict], assignments_by_slot: dict) -> None:
    """Eintragungen archivierter Auftraege in die Historie uebernehmen.

    Laeuft bei jedem Board-Aufruf und ist idempotent (UNIQUE auf
    slot_id+player). Ohne diesen Schritt waere die Statistik leer, sobald
    ein Auftrag vom Board verschwindet.
    """
    neu: list[CompletedParticipation] = []
    for mission in missions:
        if not mission.get("archived_at"):
            continue
        crew_name = (mission.get("crew") or {}).get("name", "")
        for slot in mission.get("slots", []):
            for a in assignments_by_slot.get(slot.get("id"), []):
                neu.append(CompletedParticipation(
                    slot_id=a.slot_id,
                    mission_id=a.mission_id,
                    player_discord_id=a.player_discord_id,
                    username=a.username,
                    crew_name=crew_name,
                    slot_name=slot.get("name") or "",
                ))
    if not neu:
        return
    async with SessionLocal() as session:
        for row in neu:
            # Einzeln, damit ein bereits vorhandener Eintrag die anderen
            # nicht mit zurueckrollt
            try:
                async with session.begin():
                    session.add(row)
            except IntegrityError:
                pass


@app.get("/api/board")
async def api_board(me: dict = Depends(require_session)):
    """Event-Board: alle Tage aller Event-Zeitraeume (auch leere) +
    Pseudo-Tag 'Ausserhalb Event' fuer alles, was in keinen Zeitraum faellt."""
    missions, crews = await _fetch_crime_data()

    # Alle Belegungen laden und nach Slot gruppieren
    async with SessionLocal() as session:
        result = await session.execute(
            select(SlotAssignment).order_by(SlotAssignment.assigned_at)
        )
        assignments = result.scalars().all()
        dismissed = set(
            (await session.execute(select(DismissedMission.mission_id))).scalars().all()
        )
    assignments_by_slot: dict[int, list[SlotAssignment]] = {}
    for a in assignments:
        assignments_by_slot.setdefault(a.slot_id, []).append(a)

    # Erledigte Einsaetze festschreiben, bevor der Auftrag vom Board faellt
    await _record_completed(missions, assignments_by_slot)

    # Vom Admin ausgeblendete Auftraege gar nicht erst anzeigen
    if dismissed:
        missions = [m for m in missions if m.get("id") not in dismissed]

    # Missions auf Berlin-Kalendertage verteilen
    event_days = _event_days()
    buckets: dict[str, list[dict]] = {d.isoformat(): [] for d, _, _ in event_days}
    other: list[dict] = []
    for mission in sorted(missions, key=_mission_sort_key):
        enriched = _enrich_mission(mission, assignments_by_slot, me)
        day = _mission_day(mission)
        key = day.isoformat() if day else None
        if key is not None and key in buckets:
            buckets[key].append(enriched)
        else:
            other.append(enriched)

    days_out = []
    for d, period_idx, period_label in event_days:
        iso_year, iso_week, _ = d.isocalendar()
        days_out.append({
            "date": d.isoformat(),
            "label": f"{WEEKDAYS_DE[d.weekday()]} {d.strftime('%d.%m.')}",
            "period": period_idx,
            "period_label": period_label,
            # Kalenderwoche: das Frontend bricht pro Woche in eine eigene Zeile um
            "week": f"{iso_year}-W{iso_week:02d}",
            "week_label": f"KW {iso_week}",
            "missions": buckets[d.isoformat()],
        })
    if other:
        # Nichts verschwindet: Missions ausserhalb des Fensters als Pseudo-Tag
        days_out.append({
            "date": "other",
            "label": "Außerhalb Event",
            "period": -1,
            "period_label": "",
            "week": "other",
            "week_label": "",
            "missions": other,
        })

    return {
        "event": {
            "start": config.EVENT_START.isoformat(),
            "end": config.EVENT_END.isoformat(),
            "periods": [
                {
                    "start": p["start"].isoformat(),
                    "end": p["end"].isoformat(),
                    "label": p.get("label", ""),
                }
                for p in config.EVENT_PERIODS
            ],
        },
        "days": days_out,
        "crews": crews,
        # is_admin normalisieren: Sessions von vor dem Admin-Feature haben den
        # Key nicht — das UI soll trotzdem immer einen Bool sehen
        "me": {**me, "is_admin": bool(me.get("is_admin"))},
    }


@app.post("/api/slots/{slot_id}/assign", status_code=201)
async def assign_slot(
    slot_id: int,
    payload: dict = Body(...),
    me: dict = Depends(require_session),
):
    """Selbst in einen Slot eintragen — Kapazitaet + Unique in einer Transaktion."""
    mission_id = payload.get("mission_id")
    if not isinstance(mission_id, int):
        raise HTTPException(status_code=422, detail="mission_id fehlt oder ist ungültig")

    # Slot gegen frische Board-Daten validieren (Cache ok)
    missions, _ = await _fetch_crime_data()
    slot = None
    found_mission = None
    for mission in missions:
        if mission.get("id") != mission_id:
            continue
        for s in mission.get("slots", []):
            if s.get("id") == slot_id:
                slot = s
                found_mission = mission
                break
    if slot is None:
        raise HTTPException(
            status_code=404, detail="Slot nicht gefunden oder Auftrag nicht mehr aktiv"
        )
    # Abgeschlossene Auftraege sind zu — auch wenn das UI den Button noch zeigt
    if found_mission and found_mission.get("archived_at"):
        raise HTTPException(
            status_code=409, detail="Dieser Auftrag ist bereits abgeschlossen"
        )
    required = slot.get("required_count") or 1

    try:
        async with SessionLocal() as session:
            async with session.begin():
                # Race-sicher: ERST einfuegen (flush nimmt den SQLite-Write-Lock),
                # DANN zaehlen — parallele Eintragungen warten auf den Lock und
                # sehen beim eigenen Count die fremde Row bereits. Bei
                # Ueberbelegung rollt die Exception die Transaktion zurueck.
                session.add(
                    SlotAssignment(
                        slot_id=slot_id,
                        mission_id=mission_id,
                        player_discord_id=me["discord_user_id"],
                        username=me.get("username", ""),
                    )
                )
                await session.flush()
                count = await session.scalar(
                    select(func.count())
                    .select_from(SlotAssignment)
                    .where(SlotAssignment.slot_id == slot_id)
                )
                if (count or 0) > required:
                    raise HTTPException(
                        status_code=409, detail="Slot ist bereits voll belegt"
                    )
    except IntegrityError:
        raise HTTPException(
            status_code=409, detail="Du bist in diesem Slot bereits eingetragen"
        )

    return {"detail": "Eingetragen"}


async def _mission_archived_for_slot(slot_id: int) -> bool:
    """Gehoert der Slot zu einem bereits abgeschlossenen Auftrag?"""
    missions, _ = await _fetch_crime_data()
    for mission in missions:
        for s in mission.get("slots", []):
            if s.get("id") == slot_id:
                return bool(mission.get("archived_at"))
    return False


@app.delete("/api/slots/{slot_id}/assign", status_code=204)
async def unassign_slot(slot_id: int, me: dict = Depends(require_session)):
    """Eigenes Assignment loeschen."""
    if await _mission_archived_for_slot(slot_id):
        raise HTTPException(
            status_code=409, detail="Dieser Auftrag ist bereits abgeschlossen"
        )
    async with SessionLocal() as session:
        result = await session.execute(
            delete(SlotAssignment).where(
                SlotAssignment.slot_id == slot_id,
                SlotAssignment.player_discord_id == me["discord_user_id"],
            )
        )
        await session.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Kein Eintrag gefunden")
    return Response(status_code=204)


@app.delete("/api/admin/assignments/{slot_id}/{player_discord_id}", status_code=204)
async def admin_unassign(
    slot_id: int,
    player_discord_id: str,
    me: dict = Depends(require_session),
):
    """Admin-Kick: Eintragung eines beliebigen Spielers aus einem Slot entfernen.

    Autorisierung: is_admin aus der signierten Session (beim Login ermittelt,
    Admin-Rolle oder gelistete User-ID) — reicht hier als Nachweis.
    """
    if not me.get("is_admin"):
        raise HTTPException(status_code=403, detail="Nur für Admins")
    async with SessionLocal() as session:
        result = await session.execute(
            delete(SlotAssignment).where(
                SlotAssignment.slot_id == slot_id,
                SlotAssignment.player_discord_id == player_discord_id,
            )
        )
        await session.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Kein Eintrag gefunden")
    return Response(status_code=204)


def _require_admin(me: dict) -> None:
    if not me.get("is_admin"):
        raise HTTPException(status_code=403, detail="Nur für Admins")


@app.post("/api/admin/clear-completed")
async def admin_clear_completed(me: dict = Depends(require_session)):
    """Alle erledigten Auftraege sofort vom Board nehmen.

    Die Auftraege selbst bleiben im Crime-Dashboard unberuehrt — hier wird
    nur vermerkt, dass sie auf der Boerse nicht mehr erscheinen sollen. Die
    Teilnahme-Historie fuer die Statistik bleibt ebenfalls erhalten.
    """
    _require_admin(me)
    missions, _ = await _fetch_crime_data()

    # Vor dem Ausblenden die Teilnahmen sichern
    async with SessionLocal() as session:
        result = await session.execute(select(SlotAssignment))
        assignments_by_slot: dict[int, list[SlotAssignment]] = {}
        for a in result.scalars().all():
            assignments_by_slot.setdefault(a.slot_id, []).append(a)
    await _record_completed(missions, assignments_by_slot)

    erledigt = [m for m in missions if m.get("archived_at")]
    if not erledigt:
        return {"removed": 0, "detail": "Keine erledigten Aufträge vorhanden"}

    entfernt = 0
    async with SessionLocal() as session:
        for m in erledigt:
            try:
                async with session.begin():
                    session.add(DismissedMission(
                        mission_id=m["id"],
                        dismissed_by=me.get("username", ""),
                    ))
                entfernt += 1
            except IntegrityError:
                pass  # war schon ausgeblendet
    return {"removed": entfernt, "detail": f"{entfernt} erledigte Aufträge entfernt"}


@app.get("/api/admin/stats")
async def admin_stats(me: dict = Depends(require_session)):
    """Auswertung: wer hat wie viele Auftraege mitgemacht (nur fuer Admins)."""
    _require_admin(me)
    async with SessionLocal() as session:
        res = await session.execute(
            select(
                CompletedParticipation.player_discord_id,
                func.max(CompletedParticipation.username),
                func.count(func.distinct(CompletedParticipation.mission_id)),
                func.count(CompletedParticipation.id),
                func.max(CompletedParticipation.completed_at),
            ).group_by(CompletedParticipation.player_discord_id)
        )
        fertig = {
            row[0]: {
                "player_discord_id": row[0],
                "username": row[1] or "?",
                "missions_done": row[2],
                "slots_done": row[3],
                "last_done": row[4].isoformat() if row[4] else None,
            }
            for row in res.all()
        }
        # Aktuell offene Eintragungen — also solche, die noch NICHT als
        # erledigt festgeschrieben sind. Ohne diesen Ausschluss wuerden
        # abgeschlossene Einsaetze doppelt (als "offen") mitgezaehlt.
        noch_offen = ~exists().where(
            CompletedParticipation.slot_id == SlotAssignment.slot_id,
            CompletedParticipation.player_discord_id == SlotAssignment.player_discord_id,
        )
        res2 = await session.execute(
            select(
                SlotAssignment.player_discord_id,
                func.max(SlotAssignment.username),
                func.count(SlotAssignment.id),
            )
            .where(noch_offen)
            .group_by(SlotAssignment.player_discord_id)
        )
        offen = {row[0]: {"username": row[1] or "?", "open": row[2]} for row in res2.all()}

    spieler: dict[str, dict] = {}
    for pid, data in fertig.items():
        spieler[pid] = {**data, "open": 0}
    for pid, data in offen.items():
        if pid in spieler:
            spieler[pid]["open"] = data["open"]
        else:
            spieler[pid] = {
                "player_discord_id": pid, "username": data["username"],
                "missions_done": 0, "slots_done": 0, "last_done": None,
                "open": data["open"],
            }

    liste = sorted(
        spieler.values(),
        key=lambda p: (-p["missions_done"], -p["open"], p["username"].lower()),
    )
    return {
        "players": liste,
        "total_players": len(liste),
        "total_completed": sum(p["slots_done"] for p in liste),
    }
