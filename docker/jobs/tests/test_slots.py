# -*- coding: utf-8 -*-
"""Eintragen/Austragen: Kapazitaet, Duplikate, archivierte Auftraege."""
import asyncio

import httpx
from sqlalchemy import func, select

from .conftest import mission, slot, session_cookie
from src import main as app_main
from src.db import SessionLocal
from src.models import SlotAssignment


async def test_assign_und_board(player, crime_data):
    crime_data["missions"] = [mission(1, [slot(10, required=2)])]
    r = await player.post("/api/slots/10/assign", json={"mission_id": 1})
    assert r.status_code == 201

    board = (await player.get("/api/board")).json()
    alle_missions = [m for d in board["days"] for m in d["missions"]]
    assert len(alle_missions) == 1
    s = alle_missions[0]["slots"][0]
    assert s["assigned_count"] == 1
    assert s["free"] == 1
    assert s["mine"] is True
    assert s["assigned"][0]["username"] == "Player Eins"


async def test_assign_doppelt_409(player, crime_data):
    crime_data["missions"] = [mission(1, [slot(10, required=2)])]
    await player.post("/api/slots/10/assign", json={"mission_id": 1})
    r = await player.post("/api/slots/10/assign", json={"mission_id": 1})
    assert r.status_code == 409


async def test_assign_voll_409(client, crime_data):
    crime_data["missions"] = [mission(1, [slot(10, required=1)])]
    client.cookies.set(app_main.SESSION_COOKIE, session_cookie("1", "Eins"))
    assert (await client.post("/api/slots/10/assign", json={"mission_id": 1})).status_code == 201
    client.cookies.set(app_main.SESSION_COOKIE, session_cookie("2", "Zwei"))
    r = await client.post("/api/slots/10/assign", json={"mission_id": 1})
    assert r.status_code == 409
    assert r.json()["detail"] == "Slot ist bereits voll belegt"


async def test_assign_mission_id_ungueltig_422(player, crime_data):
    crime_data["missions"] = [mission(1, [slot(10)])]
    assert (await player.post("/api/slots/10/assign", json={})).status_code == 422
    r = await player.post("/api/slots/10/assign", json={"mission_id": "x"})
    assert r.status_code == 422


async def test_assign_parallel_nie_ueberbucht(crime_data):
    """Kapazitaets-Race: fuenf Spieler stuermen gleichzeitig denselben
    required=1-Slot (getrennte Cookie-Jars, asyncio.gather). Es darf genau
    ein 201 geben und die DB genau eine Row halten — nie eine Ueberbuchung.
    Auf korrektem insert-then-count-Code immer gruen; ein Revert auf
    count-then-insert kann hier ueberbuchen."""
    crime_data["missions"] = [mission(1, [slot(10, required=1)])]

    async def versuch(uid):
        transport = httpx.ASGITransport(app=app_main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.cookies.set(app_main.SESSION_COOKIE, session_cookie(str(uid), f"U{uid}"))
            r = await c.post("/api/slots/10/assign", json={"mission_id": 1})
            return r.status_code

    codes = await asyncio.gather(*(versuch(i) for i in range(1, 6)))
    assert codes.count(201) == 1
    assert all(c in (201, 409) for c in codes)
    async with SessionLocal() as s:
        n = await s.scalar(select(func.count()).select_from(SlotAssignment)
                           .where(SlotAssignment.slot_id == 10))
    assert n == 1


async def test_assign_archiviert_409(player, crime_data):
    crime_data["missions"] = [mission(1, [slot(10)], archived=True)]
    r = await player.post("/api/slots/10/assign", json={"mission_id": 1})
    assert r.status_code == 409


async def test_assign_unbekannter_slot_404(player, crime_data):
    crime_data["missions"] = []
    r = await player.post("/api/slots/77/assign", json={"mission_id": 1})
    assert r.status_code == 404


async def test_unassign(player, crime_data):
    crime_data["missions"] = [mission(1, [slot(10)])]
    await player.post("/api/slots/10/assign", json={"mission_id": 1})
    assert (await player.delete("/api/slots/10/assign")).status_code == 204
    assert (await player.delete("/api/slots/10/assign")).status_code == 404
