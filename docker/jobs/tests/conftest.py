# -*- coding: utf-8 -*-
"""Test-Setup: Env MUSS vor dem ersten src-Import stehen (config liest beim
Import).

WICHTIG — sicherheitskritische Variablen werden HART gesetzt (nicht
setdefault): sonst wuerde eine in der Shell exportierte JOBS_DB_PATH von
`drop_all` geleert (echte Dev-/Prod-DB!) und ein exportierter
DISCORD_BOT_TOKEN wuerde den Rollen-Recheck live gegen Discord laufen lassen.
Beides bleibt unter Testkontrolle: die DB ist eine wegwerfbare Temp-Datei
pro Prozess, der Token ist leer (Recheck + Reminder-Loop damit aus)."""
import os
import tempfile
import uuid

# Wegwerf-DB pro Testprozess — nie eine echte jobs.db aus der Umgebung treffen
_TEST_DB = os.path.join(tempfile.gettempdir(), f"jobs-test-{uuid.uuid4().hex}.db")
os.environ["JOBS_DB_PATH"] = _TEST_DB
os.environ["DISCORD_BOT_TOKEN"] = ""  # Recheck + Reminder-Loop aus: kein Discord

os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("DISCORD_CLIENT_ID", "1")
os.environ.setdefault("DISCORD_CLIENT_SECRET", "x")
os.environ.setdefault("DISCORD_REDIRECT_URI", "http://localhost/auth/callback")
os.environ.setdefault("DISCORD_GUILD_ID", "42")
os.environ.setdefault("REQUIRED_ROLE_ID", "100")
os.environ.setdefault("ADMIN_ROLE_ID", "200")
os.environ.setdefault("ADMIN_USER_IDS", "999")
os.environ.setdefault("COOKIE_SECURE", "0")
os.environ.setdefault("EVENT_PERIODS", "2026-08-07T18:00~2026-08-16T23:50:Test-Event")

import httpx
import pytest

from src import main as app_main
from src.db import engine
from src.models import Base


def pytest_sessionfinish(session, exitstatus):
    """Wegwerf-DB nach dem Lauf entfernen (inkl. WAL/SHM-Nebendateien)."""
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(_TEST_DB + suffix)
        except OSError:
            pass


@pytest.fixture(autouse=True)
async def clean_db():
    """Pro Test frische Tabellen — die Engine haengt an der Wegwerf-DB."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
def crime_data(monkeypatch):
    """Crime-Backend faken: Tests befuellen state['missions']/state['crews'].
    Ersetzt auch den 15s-Cache — jeder Aufruf sieht den aktuellen Stand."""
    state = {"missions": [], "crews": []}

    async def fake_fetch():
        return state["missions"], state["crews"]

    monkeypatch.setattr(app_main, "_fetch_crime_data", fake_fetch)
    return state


@pytest.fixture
def sent_dms(monkeypatch):
    """DM-Versand abfangen (Warteliste nutzt send_single_dm_with_retry)."""
    calls = []

    async def fake_dm(user_id, content, attempts=3):
        calls.append({"user_id": user_id, "content": content})
        return "ok"

    monkeypatch.setattr(app_main.reminders, "send_single_dm_with_retry", fake_dm)
    monkeypatch.setattr(app_main.reminders, "send_single_dm", fake_dm)
    return calls


def session_cookie(user_id="1", username="Tester", is_admin=False):
    """Echtes signiertes Session-Cookie — testet den kompletten Auth-Pfad."""
    return app_main._session_serializer.dumps({
        "discord_user_id": user_id,
        "username": username,
        "avatar": "",
        "is_admin": is_admin,
    })


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app_main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def player(client):
    client.cookies.set(app_main.SESSION_COOKIE, session_cookie("1", "Player Eins"))
    return client


@pytest.fixture
async def admin(client):
    client.cookies.set(app_main.SESSION_COOKIE, session_cookie("999", "Admin", is_admin=True))
    return client


def mission(mid=1, slots=None, archived=False, crew="Sindaccos", **extra):
    """Kompakte Fake-Mission im Format der Crime-Public-API."""
    return {
        "id": mid,
        "status": "sent",
        "sent_at": "2026-08-08T10:00:00",
        "scheduled_send_at": None,
        "deadline_at": None,
        "archived_at": "2026-08-08T20:00:00" if archived else None,
        "window_start": None,
        "window_end": None,
        "crew": {"id": 1, "name": crew, "district": "Chinatown", "color_hex": "#b91c1c"},
        "slot_window": "21:00-23:00",
        "content": "Testauftrag",
        "content_excerpt": "Testauftrag",
        "personnel_brief": "",
        "slots": slots or [],
        **extra,
    }


def slot(sid=10, required=1, name="Tankwart", **extra):
    return {
        "id": sid,
        "npc_number": 6,
        "name": name,
        "function": "Ablenkung",
        "location": "Tanke",
        "costume": "Blaumann",
        "required_count": required,
        "slot_window": "",
        "notes": "",
        **extra,
    }
