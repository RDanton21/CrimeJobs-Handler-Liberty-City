# -*- coding: utf-8 -*-
"""Konfiguration fuer die SEKTOR Personal-Boerse (Jobs-Dashboard).

Alle Werte kommen aus Env-Vars (Container-intern via docker-compose gesetzt).
Defaults nur dort, wo der Kontrakt sie definiert.
"""
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

# Zeitzonen: Crime-Backend liefert naive UTC, das Board gruppiert nach Berlin-Zeit
BERLIN_TZ = ZoneInfo("Europe/Berlin")
UTC_TZ = ZoneInfo("UTC")

# --- Discord OAuth2 ---
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "")
REQUIRED_ROLE_ID = os.getenv("REQUIRED_ROLE_ID", "")

# --- Admin (darf fremde Slot-Eintragungen entfernen) ---
# Wer die Admin-Rolle traegt ODER in der User-ID-Liste steht, bekommt is_admin=true
ADMIN_ROLE_ID = os.getenv("ADMIN_ROLE_ID", "1431562679545364582")
ADMIN_USER_IDS = {
    part.strip()
    for part in os.getenv("ADMIN_USER_IDS", "584086760284487697").split(",")
    if part.strip()
}

# --- Session ---
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
# Fuer lokale Tests ohne HTTPS: COOKIE_SECURE=0 setzen (Default: an)
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "1").strip().lower() in ("1", "true", "yes")

# --- Crime-Backend (Public-API) ---
CRIME_BACKEND_URL = os.getenv("CRIME_BACKEND_URL", "http://sekt6r-crime-backend:8000").rstrip("/")
CRIME_API_KEY = os.getenv("CRIME_API_KEY", "")

# --- Datenbank ---
JOBS_DB_PATH = os.getenv("JOBS_DB_PATH", "/app/data/jobs.db")


def _parse_event_dt(value: str | None, fallback: str) -> datetime:
    """ISO-String -> aware datetime in Europe/Berlin. Bei Muell greift der Fallback."""
    try:
        dt = datetime.fromisoformat(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        dt = datetime.fromisoformat(fallback)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BERLIN_TZ)
    return dt


# --- Event-Fenster (Europe/Berlin) ---
# Mehrere Zeitraeume moeglich. Format von EVENT_PERIODS:
#   "<start>~<ende>[:<Label>],<start>~<ende>[:<Label>]"
# Beispiel:
#   2026-07-19T00:00~2026-07-26T23:59:Testphase,2026-08-07T18:00~2026-08-16T23:50:Das Probespiel
# Ohne EVENT_PERIODS greifen die Defaults unten; EVENT_START/EVENT_END werden
# weiterhin unterstuetzt und ueberschreiben dann den ersten Zeitraum.
_DEFAULT_PERIODS = (
    "2026-07-19T00:00~2026-07-26T23:59:Testphase,"
    "2026-08-07T18:00~2026-08-16T23:50:Das Probespiel"
)


def _parse_periods(raw: str) -> list[dict]:
    """'start~ende[:Label],...' -> [{'start': dt, 'end': dt, 'label': str}]."""
    out: list[dict] = []
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk or "~" not in chunk:
            continue
        start_raw, rest = chunk.split("~", 1)
        # Label ist optional und steht nach dem Datum — der ISO-Teil enthaelt
        # selbst Doppelpunkte (T18:00), daher von rechts nach dem Datum trennen.
        m = re.match(r"\s*(\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?)\s*(?::\s*(.*))?$", rest)
        if not m:
            continue
        end_raw, label = m.group(1), (m.group(2) or "").strip()
        try:
            start = _parse_event_dt(start_raw.strip(), start_raw.strip())
            end = _parse_event_dt(end_raw.strip(), end_raw.strip())
        except ValueError:
            continue
        if end < start:
            continue
        out.append({"start": start, "end": end, "label": label})
    out.sort(key=lambda p: p["start"])
    return out


EVENT_PERIODS = _parse_periods(os.getenv("EVENT_PERIODS") or _DEFAULT_PERIODS)
if not EVENT_PERIODS:  # Fallback, falls die Konfiguration unbrauchbar ist
    EVENT_PERIODS = _parse_periods(_DEFAULT_PERIODS)

# Explizite EVENT_START/EVENT_END uebersteuern den ersten Zeitraum (Alt-Setup).
# Leere Werte ignorieren — docker-compose setzt die Variablen immer, ggf. leer.
if (os.getenv("EVENT_START") or "").strip() or (os.getenv("EVENT_END") or "").strip():
    EVENT_PERIODS[0] = {
        "start": _parse_event_dt(os.getenv("EVENT_START"), "2026-08-07T18:00"),
        "end": _parse_event_dt(os.getenv("EVENT_END"), "2026-08-16T23:50"),
        "label": EVENT_PERIODS[0].get("label", ""),
    }
    EVENT_PERIODS.sort(key=lambda p: p["start"])

# Gesamtspanne — weiterhin fuer die /api/board-Response und Alt-Code
EVENT_START = EVENT_PERIODS[0]["start"]
EVENT_END = EVENT_PERIODS[-1]["end"]
