# -*- coding: utf-8 -*-
"""Konfiguration fuer die SEKTOR Personal-Boerse (Jobs-Dashboard).

Alle Werte kommen aus Env-Vars (Container-intern via docker-compose gesetzt).
Defaults nur dort, wo der Kontrakt sie definiert.
"""
import os
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
EVENT_START = _parse_event_dt(os.getenv("EVENT_START"), "2026-08-07T18:00")
EVENT_END = _parse_event_dt(os.getenv("EVENT_END"), "2026-08-16T23:50")
