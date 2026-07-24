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
import contextlib
import csv
import io
import logging
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

# Root-Logger fuer eigene Module (z.B. jobs.reminders) — uvicorn konfiguriert
# nur seine eigenen Logger, INFO-Meldungen gingen sonst verloren
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s — %(message)s")

import httpx
from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import case, delete, exists, func, select, update
from sqlalchemy.exc import IntegrityError

from . import config, discord_oauth, reminders
from .db import SessionLocal, init_db
from .models import (
    AdminAction,
    CompletedParticipation,
    DismissedMission,
    Player,
    SlotAssignment,
    WaitlistEntry,
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

#: Referenzen auf Fire-and-forget-Tasks (DM-Versand) — asyncio haelt selbst
#: nur schwache Referenzen, ohne dieses Set koennte der GC laufende Tasks
#: einsammeln.
_background_tasks: set = set()


def _spawn_background(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


#: Wie lange jemand nach dem letzten Board-Aufruf als "gerade aktiv" gilt.
#: Das Board laedt alle 30 Sekunden nach, 5 Minuten decken also auch eine
#: kurze Unterbrechung ab, ohne dass jemand faelschlich als online gilt.
ONLINE_WINDOW = timedelta(minutes=5)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    # Erinnerungs-DMs im Hintergrund (no-op ohne DISCORD_BOT_TOKEN)
    reminder_task = asyncio.create_task(reminders.reminder_loop(_fetch_crime_data))
    yield
    reminder_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await reminder_task


app = FastAPI(title="SEKTOR Personal-Boerse", lifespan=lifespan)


#: Strikte CSP — moeglich, seit alle Assets self-hosted sind (kein CDN,
#: keine Google Fonts, kein Inline-Skript). Ausnahmen:
#:   'unsafe-eval'   -> Alpine.js wertet x-*-Ausdruecke per new Function() aus
#:   style 'unsafe-inline' -> Alpines :style-Bindings + x-show setzen
#:                     Inline-Style-ATTRIBUTE (nicht hashbar)
#:   img cdn.discordapp.com -> Discord-Avatare
CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' https://cdn.discordapp.com; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "object-src 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Basis-Security-Header fuer alle Responses (oeffentlich erreichbares
    Dashboard hinter Traefik)."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Content-Security-Policy", CSP)
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


#: Bei Discord-API-Problemen Rechecks kurz aussetzen statt jeden Request
#: gegen die Wand laufen zu lassen (monotonic-Timestamp).
_recheck_backoff_until = 0.0


async def _recheck_roles(me: dict) -> dict:
    """Rolle + Admin-Status waehrend der Session periodisch neu pruefen.

    Der Login prueft die Rolle nur einmal; das Cookie lebt 7 Tage. Mit
    Bot-Token wird hier alle ROLE_RECHECK_MINUTES nachgeprueft (TTL in
    players.role_checked_at): Rolle weg -> 401, Admin-Rolle weg -> is_admin
    faellt sofort. Ohne Token oder mit 0 Minuten: Verhalten wie bisher.
    Discord-Ausfaelle sperren niemanden aus (Backoff, letzter Stand gilt).
    """
    global _recheck_backoff_until
    if not config.DISCORD_BOT_TOKEN or config.ROLE_RECHECK_MINUTES <= 0:
        return me
    user_id = me["discord_user_id"]
    jetzt = datetime.utcnow()
    ttl = timedelta(minutes=config.ROLE_RECHECK_MINUTES)

    async with SessionLocal() as session:
        player = await session.get(Player, user_id)

    def _stored_flags() -> dict:
        """Letzten bekannten DB-Stand anwenden — NIE auf rohe Cookie-Rechte
        zurueckfallen: ein gespeicherter Entzug bleibt auch dann wirksam,
        wenn Discord gerade nicht fragbar ist."""
        if player is not None and player.role_ok == 0:
            raise HTTPException(
                status_code=401, detail="Berechtigung entzogen — bitte neu anmelden"
            )
        if player is not None and player.admin_ok is not None:
            return {**me, "is_admin": bool(player.admin_ok)}
        return me

    if (
        player is not None
        and player.role_checked_at is not None
        and jetzt - player.role_checked_at < ttl
    ):
        # Frischer Check vorhanden -> gespeicherte Flags anwenden
        return _stored_flags()

    if time.monotonic() < _recheck_backoff_until:
        return _stored_flags()

    try:
        member = await discord_oauth.fetch_member_bot(config.DISCORD_GUILD_ID, user_id)
        roles = member.get("roles") or []
        role_ok = config.REQUIRED_ROLE_ID in roles
        admin_ok = config.ADMIN_ROLE_ID in roles or user_id in config.ADMIN_USER_IDS
    except discord_oauth.DiscordOAuthError as exc:
        if exc.status == 404:
            # Hat den Server verlassen / wurde gekickt
            role_ok, admin_ok = False, False
        else:
            _recheck_backoff_until = time.monotonic() + 60
            return _stored_flags()

    async with SessionLocal() as session:
        try:
            db_player = await session.get(Player, user_id)
            if db_player is None:  # Session aelter als die players-Row (z.B. DB neu)
                db_player = Player(
                    discord_user_id=user_id,
                    username=me.get("username", ""),
                    avatar=me.get("avatar", ""),
                )
                session.add(db_player)
            db_player.role_ok = 1 if role_ok else 0
            db_player.admin_ok = 1 if admin_ok else 0
            db_player.role_checked_at = jetzt
            await session.commit()
        except IntegrityError:
            pass  # paralleler Request hat dieselbe Row soeben angelegt

    if not role_ok:
        raise HTTPException(
            status_code=401, detail="Berechtigung entzogen — bitte neu anmelden"
        )
    return {**me, "is_admin": admin_ok}


async def require_session(request: Request) -> dict:
    """Dependency: 401 ohne gueltige Session; Rollen-Recheck wenn faellig."""
    session = _read_session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="nicht eingeloggt")
    return await _recheck_roles(session)


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


def _enrich_mission(
    mission: dict, assignments_by_slot: dict, waitlist_by_slot: dict, me: dict
) -> dict:
    """Mission-Kopie mit Belegungsdaten pro Slot anreichern (Cache nie mutieren!)."""
    enriched = dict(mission)
    slots_out = []
    for slot in mission.get("slots", []):
        s = dict(slot)
        assigned = assignments_by_slot.get(slot.get("id"), [])
        s["assigned"] = [
            {
                "player_discord_id": a.player_discord_id,
                "username": a.username,
                "attended": a.attended,  # None=offen, 1=erschienen, 0=No-Show
            }
            for a in assigned
        ]
        s["assigned_count"] = len(assigned)
        required = slot.get("required_count") or 1
        s["free"] = max(required - len(assigned), 0)
        s["mine"] = any(a.player_discord_id == me["discord_user_id"] for a in assigned)
        waiting = waitlist_by_slot.get(slot.get("id"), [])
        s["waitlist"] = [
            {"player_discord_id": w.player_discord_id, "username": w.username}
            for w in waiting
        ]
        s["on_waitlist"] = any(
            w.player_discord_id == me["discord_user_id"] for w in waiting
        )
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


#: Explizite Allowlist statt StaticFiles-Mount (Security-Review: nur bewusst
#: freigegebene Dateien werden ausgeliefert). filename -> (media_type, max_age).
#: css/js kuerzer gecacht (aendern sich bei Deploys), Fonts/Icons lange.
_STATIC_FILES: dict[str, tuple[str, int]] = {
    "bg.jpg": ("image/jpeg", 86400),
    "favicon.ico": ("image/x-icon", 604800),
    "favicon-32.png": ("image/png", 604800),
    "apple-touch-icon.png": ("image/png", 604800),
    "tailwind.css": ("text/css", 3600),
    "app.js": ("text/javascript", 3600),
    "alpine.min.js": ("text/javascript", 86400),
    "oswald-latin.woff2": ("font/woff2", 2592000),
    "oswald-latin-ext.woff2": ("font/woff2", 2592000),
}


@app.get("/static/{filename}")
async def static_file(filename: str):
    """Einzeldatei-Auslieferung; alles ausserhalb der Allowlist ist 404.
    filename ist ein einzelnes Pfadsegment (Route matcht kein '/'), die
    Allowlist verhindert zusaetzlich jede Traversal-Spielerei."""
    meta = _STATIC_FILES.get(filename)
    if meta is None:
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    media_type, max_age = meta
    return FileResponse(
        STATIC_DIR / filename,
        media_type=media_type,
        headers={"Cache-Control": f"public, max-age={max_age}"},
    )


@app.get("/favicon.ico")
async def favicon():
    return await static_file("favicon.ico")


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
        # Login-Check zaehlt als frischer Rollen-Recheck
        player.role_ok = 1
        player.admin_ok = 1 if is_admin else 0
        player.role_checked_at = datetime.utcnow()
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


@app.get("/api/me/stats")
async def my_stats(me: dict = Depends(require_session)):
    """Eigene Einsatz-Bilanz: Summen + Historie. Bewusst nur eigene Daten —
    die Gesamt-Auswertung aller Spieler bleibt Admin-only."""
    uid = me["discord_user_id"]
    async with SessionLocal() as session:
        agg = (
            await session.execute(
                select(
                    func.count(func.distinct(CompletedParticipation.mission_id)),
                    func.count(CompletedParticipation.id),
                    func.sum(case((CompletedParticipation.attended == 1, 1), else_=0)),
                    func.sum(case((CompletedParticipation.attended == 0, 1), else_=0)),
                ).where(CompletedParticipation.player_discord_id == uid)
            )
        ).one()
        rows = (
            await session.execute(
                select(CompletedParticipation)
                .where(CompletedParticipation.player_discord_id == uid)
                .order_by(CompletedParticipation.completed_at.desc(),
                          CompletedParticipation.id.desc())
                .limit(100)
            )
        ).scalars().all()
        # Offene Eintragungen: noch nicht als erledigt festgeschrieben
        noch_offen = ~exists().where(
            CompletedParticipation.slot_id == SlotAssignment.slot_id,
            CompletedParticipation.player_discord_id == SlotAssignment.player_discord_id,
        )
        open_count = await session.scalar(
            select(func.count())
            .select_from(SlotAssignment)
            .where(SlotAssignment.player_discord_id == uid, noch_offen)
        )
    return {
        "missions_done": agg[0] or 0,
        "slots_done": agg[1] or 0,
        "attended": agg[2] or 0,
        "no_show": agg[3] or 0,
        "open": open_count or 0,
        "history": [
            {
                "crew_name": r.crew_name or "",
                "slot_name": r.slot_name or "",
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "attended": r.attended,
            }
            for r in rows
        ],
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
                    attended=a.attended,
                ))
    if not neu:
        return

    async def _live_attended(session, row):
        """Aktuelle Anwesenheit frisch aus dem Live-Assignment (None = Row weg).
        Der Snapshot des Board-Requests kann veraltet sein und wuerde eine
        soeben gesetzte Admin-Bewertung wieder ueberschreiben (Lost Update)."""
        return (
            await session.execute(
                select(SlotAssignment.attended).where(
                    SlotAssignment.slot_id == row.slot_id,
                    SlotAssignment.player_discord_id == row.player_discord_id,
                )
            )
        ).one_or_none()

    async with SessionLocal() as session:
        for row in neu:
            # Einzeln, damit ein bereits vorhandener Eintrag die anderen
            # nicht mit zurueckrollt
            try:
                async with session.begin():
                    live = await _live_attended(session, row)
                    if live is not None:
                        row.attended = live[0]
                    session.add(row)
            except IntegrityError:
                # Historie existiert schon -> Anwesenheit vom Live-Assignment
                # nachziehen (nur solange es das Assignment noch gibt)
                async with session.begin():
                    live = await _live_attended(session, row)
                    if live is None:
                        continue
                    await session.execute(
                        update(CompletedParticipation)
                        .where(
                            CompletedParticipation.slot_id == row.slot_id,
                            CompletedParticipation.player_discord_id == row.player_discord_id,
                        )
                        .values(attended=live[0])
                    )


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
        res_wait = await session.execute(
            select(WaitlistEntry).order_by(WaitlistEntry.joined_at, WaitlistEntry.id)
        )
        waitlist = res_wait.scalars().all()
        dismissed = set(
            (await session.execute(select(DismissedMission.mission_id))).scalars().all()
        )
        # Eigene Aktivitaet festhalten (fuer die "gerade aktiv"-Liste)
        jetzt = datetime.utcnow()
        await session.execute(
            update(Player)
            .where(Player.discord_user_id == me["discord_user_id"])
            .values(last_seen=jetzt)
        )
        # Wer war in den letzten Minuten da?
        aktiv_ab = jetzt - ONLINE_WINDOW
        res_online = await session.execute(
            select(Player.discord_user_id, Player.username, Player.avatar, Player.last_seen)
            .where(Player.last_seen.isnot(None), Player.last_seen >= aktiv_ab)
            .order_by(Player.last_seen.desc())
        )
        online = [
            {
                "discord_user_id": row[0],
                "username": row[1] or "?",
                "avatar": row[2] or "",
                "is_me": row[0] == me["discord_user_id"],
            }
            for row in res_online.all()
        ]
        await session.commit()
    assignments_by_slot: dict[int, list[SlotAssignment]] = {}
    for a in assignments:
        assignments_by_slot.setdefault(a.slot_id, []).append(a)
    waitlist_by_slot: dict[int, list[WaitlistEntry]] = {}
    for w in waitlist:
        waitlist_by_slot.setdefault(w.slot_id, []).append(w)

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
        enriched = _enrich_mission(mission, assignments_by_slot, waitlist_by_slot, me)
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
        "online": online,
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

    # Falls der Spieler noch auf der Warteliste dieses Slots stand: aufraeumen
    async with SessionLocal() as session:
        await session.execute(
            delete(WaitlistEntry).where(
                WaitlistEntry.slot_id == slot_id,
                WaitlistEntry.player_discord_id == me["discord_user_id"],
            )
        )
        await session.commit()

    return {"detail": "Eingetragen"}


async def _mission_archived_for_slot(slot_id: int) -> bool:
    """Gehoert der Slot zu einem bereits abgeschlossenen Auftrag?"""
    missions, _ = await _fetch_crime_data()
    for mission in missions:
        for s in mission.get("slots", []):
            if s.get("id") == slot_id:
                return bool(mission.get("archived_at"))
    return False


def _find_slot(missions: list, slot_id: int) -> tuple[dict | None, dict | None]:
    """(mission, slot) zu einer Slot-ID aus den Board-Daten."""
    for mission in missions:
        for s in mission.get("slots", []):
            if s.get("id") == slot_id:
                return mission, s
    return None, None


async def _promote_waitlist(slot_id: int) -> None:
    """Freie Plaetze mit Wartelisten-Eintraegen fuellen (FIFO) + Nachrueck-DM.

    Wird nach jedem Austragen/Kick und nach jedem Wartelisten-Beitritt
    aufgerufen. Fehler (z.B. Crime-Backend kurz weg) werden geloggt, aber
    nie zum Aufrufer durchgereicht — das Austragen selbst war ja erfolgreich.
    """
    try:
        missions, _ = await _fetch_crime_data()
        mission, slot = _find_slot(missions, slot_id)
        if slot is None or (mission and mission.get("archived_at")):
            return
        required = slot.get("required_count") or 1

        promoted: list[tuple[str, str]] = []  # (discord_id, username)

        class _SlotVoll(Exception):
            """Slot ist (wieder) voll — Transaktion zurueckrollen, fertig."""

        async with SessionLocal() as session:
            while True:
                entry = None
                try:
                    async with session.begin():
                        entry = (
                            await session.execute(
                                select(WaitlistEntry)
                                .where(WaitlistEntry.slot_id == slot_id)
                                .order_by(WaitlistEntry.joined_at, WaitlistEntry.id)
                                .limit(1)
                            )
                        ).scalar_one_or_none()
                        if entry is None:
                            break
                        await session.execute(
                            delete(WaitlistEntry).where(WaitlistEntry.id == entry.id)
                        )
                        session.add(
                            SlotAssignment(
                                slot_id=slot_id,
                                mission_id=entry.mission_id,
                                player_discord_id=entry.player_discord_id,
                                username=entry.username,
                            )
                        )
                        # Race-sicher wie assign_slot: ERST einfuegen (flush nimmt
                        # den SQLite-Write-Lock), DANN zaehlen. Ein Count vor dem
                        # Insert waere ein ungeschuetzter Snapshot (aiosqlite
                        # startet die DB-Transaktion erst beim ersten Write) —
                        # ein paralleles Eintragen koennte den Slot ueberbuchen.
                        await session.flush()
                        count = await session.scalar(
                            select(func.count())
                            .select_from(SlotAssignment)
                            .where(SlotAssignment.slot_id == slot_id)
                        )
                        if (count or 0) > required:
                            # Rollt Insert UND Wartelisten-Delete zurueck — der
                            # Wartende bleibt fuer den naechsten freien Platz
                            raise _SlotVoll()
                except _SlotVoll:
                    break
                except IntegrityError:
                    # Nachruecker war schon (anders) eingetragen — der Rollback hat
                    # auch das Wartelisten-Delete zurueckgenommen, also gezielt
                    # nur den Wartelisten-Eintrag entfernen und weitermachen
                    if entry is not None:
                        async with session.begin():
                            await session.execute(
                                delete(WaitlistEntry).where(WaitlistEntry.id == entry.id)
                            )
                    continue
                promoted.append((entry.player_discord_id, entry.username))

        for discord_id, username in promoted:
            logging.getLogger("jobs.waitlist").info(
                "Nachgerueckt: %s in Slot %d", username, slot_id
            )
            # DM best effort im Hintergrund (mit Retry bei 429/5xx) —
            # der Request wartet nicht darauf
            _spawn_background(
                reminders.send_single_dm_with_retry(
                    discord_id, reminders.build_promotion_message(mission, slot)
                )
            )
    except Exception:
        logging.getLogger("jobs.waitlist").exception(
            "Nachruecken fuer Slot %d fehlgeschlagen", slot_id
        )


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
    # Freigewordenen Platz sofort von der Warteliste fuellen
    await _promote_waitlist(slot_id)
    return Response(status_code=204)


async def _log_admin_action(
    me: dict,
    action: str,
    *,
    slot_id: int | None = None,
    mission_id: int | None = None,
    target_id: str = "",
    target_name: str = "",
    details: str = "",
) -> None:
    """Admin-Eingriff im Audit-Log festhalten (best effort, blockiert nie)."""
    try:
        async with SessionLocal() as session:
            session.add(AdminAction(
                admin_discord_id=me["discord_user_id"],
                admin_username=me.get("username", ""),
                action=action,
                slot_id=slot_id,
                mission_id=mission_id,
                target_discord_id=target_id,
                target_username=target_name,
                details=details,
            ))
            await session.commit()
    except Exception:
        logging.getLogger("jobs.audit").exception("Audit-Eintrag fehlgeschlagen")


@app.delete("/api/admin/assignments/{slot_id}/{player_discord_id}", status_code=204)
async def admin_unassign(
    slot_id: int,
    player_discord_id: str,
    me: dict = Depends(require_session),
):
    """Admin-Kick: Eintragung eines beliebigen Spielers aus einem Slot entfernen.

    Autorisierung: is_admin aus der signierten Session (beim Login ermittelt,
    per Rollen-Recheck aktuell gehalten) — reicht hier als Nachweis.
    """
    if not me.get("is_admin"):
        raise HTTPException(status_code=403, detail="Nur für Admins")
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(SlotAssignment).where(
                    SlotAssignment.slot_id == slot_id,
                    SlotAssignment.player_discord_id == player_discord_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Kein Eintrag gefunden")
        await session.delete(row)
        await session.commit()
        target_name, mission_id = row.username, row.mission_id
    await _log_admin_action(
        me, "kick",
        slot_id=slot_id, mission_id=mission_id,
        target_id=player_discord_id, target_name=target_name,
    )
    # Freigewordenen Platz sofort von der Warteliste fuellen
    await _promote_waitlist(slot_id)
    return Response(status_code=204)


@app.post("/api/slots/{slot_id}/waitlist", status_code=201)
async def join_waitlist(
    slot_id: int,
    payload: dict = Body(...),
    me: dict = Depends(require_session),
):
    """Auf die Warteliste eines vollen Slots setzen (FIFO)."""
    mission_id = payload.get("mission_id")
    if not isinstance(mission_id, int):
        raise HTTPException(status_code=422, detail="mission_id fehlt oder ist ungültig")

    missions, _ = await _fetch_crime_data()
    mission, slot = _find_slot(missions, slot_id)
    if slot is None or (mission and mission.get("id") != mission_id):
        raise HTTPException(
            status_code=404, detail="Slot nicht gefunden oder Auftrag nicht mehr aktiv"
        )
    if mission and mission.get("archived_at"):
        raise HTTPException(
            status_code=409, detail="Dieser Auftrag ist bereits abgeschlossen"
        )
    required = slot.get("required_count") or 1

    async with SessionLocal() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(SlotAssignment)
            .where(SlotAssignment.slot_id == slot_id)
        )
        if (count or 0) < required:
            raise HTTPException(
                status_code=409, detail="Der Slot hat freie Plätze — trag dich direkt ein"
            )
        schon_drin = await session.scalar(
            select(func.count())
            .select_from(SlotAssignment)
            .where(
                SlotAssignment.slot_id == slot_id,
                SlotAssignment.player_discord_id == me["discord_user_id"],
            )
        )
        if schon_drin:
            raise HTTPException(
                status_code=409, detail="Du bist in diesem Slot bereits eingetragen"
            )
        try:
            session.add(
                WaitlistEntry(
                    slot_id=slot_id,
                    mission_id=mission_id,
                    player_discord_id=me["discord_user_id"],
                    username=me.get("username", ""),
                )
            )
            await session.commit()
        except IntegrityError:
            raise HTTPException(
                status_code=409, detail="Du stehst bereits auf der Warteliste"
            )

    # Race abfedern: wurde der Slot inzwischen frei, sofort nachruecken
    await _promote_waitlist(slot_id)
    return {"detail": "Auf der Warteliste"}


@app.delete("/api/slots/{slot_id}/waitlist", status_code=204)
async def leave_waitlist(slot_id: int, me: dict = Depends(require_session)):
    """Eigenen Wartelisten-Eintrag entfernen."""
    async with SessionLocal() as session:
        result = await session.execute(
            delete(WaitlistEntry).where(
                WaitlistEntry.slot_id == slot_id,
                WaitlistEntry.player_discord_id == me["discord_user_id"],
            )
        )
        await session.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Kein Wartelisten-Eintrag gefunden")
    return Response(status_code=204)


def _require_admin(me: dict) -> None:
    if not me.get("is_admin"):
        raise HTTPException(status_code=403, detail="Nur für Admins")


@app.post("/api/admin/attendance/{slot_id}/{player_discord_id}")
async def admin_set_attendance(
    slot_id: int,
    player_discord_id: str,
    payload: dict = Body(...),
    me: dict = Depends(require_session),
):
    """Anwesenheit eines Spielers in einem Slot setzen (nur Admins).

    Body: {"attended": true|false|null}
      true  -> erschienen (1)
      false -> No-Show (0)
      null  -> Bewertung zuruecknehmen (offen)

    Schreibt in beide Tabellen: das Live-Assignment (falls noch vorhanden) und
    — bei bereits archivierten Auftraegen — die Historie. So funktioniert das
    Markieren sowohl waehrend des Events als auch danach.
    """
    _require_admin(me)
    if "attended" not in payload:
        raise HTTPException(
            status_code=422, detail="attended fehlt (true, false oder null)"
        )
    raw = payload["attended"]
    if raw is None:
        attended = None
    elif isinstance(raw, bool):
        attended = 1 if raw else 0
    else:
        raise HTTPException(
            status_code=422, detail="attended muss true, false oder null sein"
        )

    async with SessionLocal() as session:
        r_live = await session.execute(
            update(SlotAssignment)
            .where(
                SlotAssignment.slot_id == slot_id,
                SlotAssignment.player_discord_id == player_discord_id,
            )
            .values(attended=attended)
        )
        r_done = await session.execute(
            update(CompletedParticipation)
            .where(
                CompletedParticipation.slot_id == slot_id,
                CompletedParticipation.player_discord_id == player_discord_id,
            )
            .values(attended=attended)
        )
        await session.commit()

    if r_live.rowcount == 0 and r_done.rowcount == 0:
        raise HTTPException(status_code=404, detail="Kein Eintrag gefunden")

    # Zielname fuers Audit-Log (Live-Eintrag, sonst Historie)
    async with SessionLocal() as session:
        target_name = await session.scalar(
            select(SlotAssignment.username).where(
                SlotAssignment.slot_id == slot_id,
                SlotAssignment.player_discord_id == player_discord_id,
            )
        ) or await session.scalar(
            select(CompletedParticipation.username).where(
                CompletedParticipation.slot_id == slot_id,
                CompletedParticipation.player_discord_id == player_discord_id,
            )
        ) or ""
    label = {None: "offen", 1: "erschienen", 0: "No-Show"}[attended]
    await _log_admin_action(
        me, "attendance",
        slot_id=slot_id, target_id=player_discord_id, target_name=target_name,
        details=label,
    )
    return {"detail": "Anwesenheit gespeichert", "attended": attended}


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
        # Wartelisten-Eintraege erledigter Auftraege sind tot -> mit aufraeumen
        async with session.begin():
            await session.execute(
                delete(WaitlistEntry).where(
                    WaitlistEntry.mission_id.in_([m["id"] for m in erledigt])
                )
            )
    if entfernt:
        await _log_admin_action(
            me, "clear_completed", details=f"{entfernt} erledigte Aufträge entfernt"
        )
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
                # Anwesenheit: 1=erschienen, 0=No-Show, NULL=unbewertet
                func.sum(case((CompletedParticipation.attended == 1, 1), else_=0)),
                func.sum(case((CompletedParticipation.attended == 0, 1), else_=0)),
            ).group_by(CompletedParticipation.player_discord_id)
        )
        fertig = {
            row[0]: {
                "player_discord_id": row[0],
                "username": row[1] or "?",
                "missions_done": row[2],
                "slots_done": row[3],
                "last_done": row[4].isoformat() if row[4] else None,
                "attended": row[5] or 0,
                "no_show": row[6] or 0,
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
                "attended": 0, "no_show": 0,
                "open": data["open"],
            }

    liste = sorted(
        spieler.values(),
        key=lambda p: (-p["attended"], -p["missions_done"], -p["open"], p["username"].lower()),
    )
    return {
        "players": liste,
        "total_players": len(liste),
        "total_completed": sum(p["slots_done"] for p in liste),
        "total_attended": sum(p["attended"] for p in liste),
        "total_no_show": sum(p["no_show"] for p in liste),
    }


@app.get("/api/admin/export.csv")
async def admin_export_csv(me: dict = Depends(require_session)):
    """Belegungs-Export fuers Event-Briefing: eine Zeile pro Eintragung bzw.
    Wartelisten-Platz, sortiert wie das Board. Semikolon + BOM = oeffnet
    sauber in deutschem Excel."""
    _require_admin(me)
    missions, _ = await _fetch_crime_data()
    async with SessionLocal() as session:
        assignments = (
            await session.execute(
                select(SlotAssignment).order_by(SlotAssignment.assigned_at)
            )
        ).scalars().all()
        waitlist = (
            await session.execute(
                select(WaitlistEntry).order_by(WaitlistEntry.joined_at, WaitlistEntry.id)
            )
        ).scalars().all()
        dismissed = set(
            (await session.execute(select(DismissedMission.mission_id))).scalars().all()
        )
    # Vom Admin ausgeblendete Auftraege gehoeren wie im Board nicht in den Export
    if dismissed:
        missions = [m for m in missions if m.get("id") not in dismissed]
    assignments_by_slot: dict[int, list[SlotAssignment]] = {}
    for a in assignments:
        assignments_by_slot.setdefault(a.slot_id, []).append(a)
    waitlist_by_slot: dict[int, list[WaitlistEntry]] = {}
    for w_ in waitlist:
        waitlist_by_slot.setdefault(w_.slot_id, []).append(w_)

    def _cell(v):
        """Excel-Formel-Injektion entschaerfen: Zellen, die mit =, +, - oder @
        beginnen, wuerden Excel als Formel ausfuehren — und Nutzernamen kommen
        von Discord, sind also fremdgesteuert."""
        if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
            return "'" + v
        return v

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([
        "Datum", "Zeitfenster", "Crew", "Stadtteil", "Auftrag-ID", "Slot-ID",
        "Rolle", "Funktion", "Treffpunkt", "Kostüm", "Status", "Spieler",
        "Discord-ID", "Anwesenheit",
    ])
    attended_label = {1: "erschienen", 0: "No-Show"}
    for mission in sorted(missions, key=_mission_sort_key):
        day = _mission_day(mission)
        datum = day.strftime("%d.%m.%Y") if day else ""
        crew = mission.get("crew") or {}
        for slot in mission.get("slots", []):
            base = [
                datum,
                slot.get("slot_window") or mission.get("slot_window") or "",
                crew.get("name") or "",
                crew.get("district") or "",
                mission.get("id"),
                slot.get("id"),
                slot.get("name") or (f"NPC #{slot.get('npc_number')}" if slot.get("npc_number") else ""),
                slot.get("function") or "",
                slot.get("location") or "",
                slot.get("costume") or "",
            ]
            rows_written = False
            for a in assignments_by_slot.get(slot.get("id"), []):
                w.writerow([_cell(c) for c in base + [
                    "eingetragen", a.username, a.player_discord_id,
                    attended_label.get(a.attended, ""),
                ]])
                rows_written = True
            for i, wl in enumerate(waitlist_by_slot.get(slot.get("id"), []), start=1):
                w.writerow([_cell(c) for c in base + [
                    f"Warteliste #{i}", wl.username, wl.player_discord_id, "",
                ]])
                rows_written = True
            if not rows_written:
                w.writerow([_cell(c) for c in base + ["offen", "", "", ""]])

    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="personal-boerse.csv"',
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/admin/audit")
async def admin_audit(me: dict = Depends(require_session), limit: int = 50):
    """Letzte Admin-Eingriffe (Kick, Anwesenheit, Erledigte entfernt)."""
    _require_admin(me)
    limit = max(1, min(limit, 200))
    async with SessionLocal() as session:
        res = await session.execute(
            select(AdminAction).order_by(AdminAction.id.desc()).limit(limit)
        )
        rows = res.scalars().all()
    return {
        "actions": [
            {
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "admin_username": r.admin_username or "?",
                "action": r.action,
                "slot_id": r.slot_id,
                "mission_id": r.mission_id,
                "target_username": r.target_username or "",
                "details": r.details or "",
            }
            for r in rows
        ]
    }
