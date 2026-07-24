# -*- coding: utf-8 -*-
"""Warteliste: Beitritt nur bei vollem Slot, FIFO-Nachruecken + DM."""
import asyncio

import httpx
from sqlalchemy import func, select

from .conftest import mission, slot, session_cookie
from src import main as app_main
from src.db import SessionLocal
from src.models import SlotAssignment


def as_user(client, uid, name):
    client.cookies.set(app_main.SESSION_COOKIE, session_cookie(uid, name))
    return client


def fresh_client(uid, name):
    """Eigener Client mit eigenem Cookie-Jar (fuer echte Parallelitaet)."""
    transport = httpx.ASGITransport(app=app_main.app)
    c = httpx.AsyncClient(transport=transport, base_url="http://test")
    c.cookies.set(app_main.SESSION_COOKIE, session_cookie(uid, name))
    return c


async def test_join_bei_freiem_slot_409(player, crime_data):
    crime_data["missions"] = [mission(1, [slot(10, required=2)])]
    r = await player.post("/api/slots/10/waitlist", json={"mission_id": 1})
    assert r.status_code == 409


async def test_join_mission_id_ungueltig_422(player, crime_data):
    crime_data["missions"] = [mission(1, [slot(10, required=1)])]
    assert (await player.post("/api/slots/10/waitlist", json={})).status_code == 422


async def test_fifo_nachruecken_mit_dm(client, crime_data, sent_dms):
    crime_data["missions"] = [mission(1, [slot(10, required=1)])]
    as_user(client, "1", "Eins")
    assert (await client.post("/api/slots/10/assign", json={"mission_id": 1})).status_code == 201
    as_user(client, "2", "Zwei")
    assert (await client.post("/api/slots/10/waitlist", json={"mission_id": 1})).status_code == 201
    as_user(client, "3", "Drei")
    assert (await client.post("/api/slots/10/waitlist", json={"mission_id": 1})).status_code == 201

    # Board zeigt die Warteschlange in Reihenfolge
    board = (await client.get("/api/board")).json()
    s = [m for d in board["days"] for m in d["missions"]][0]["slots"][0]
    assert [w["username"] for w in s["waitlist"]] == ["Zwei", "Drei"]
    assert s["on_waitlist"] is True  # User 3

    # Eins traegt sich aus -> Zwei rueckt nach (FIFO), bekommt DM
    as_user(client, "1", "Eins")
    assert (await client.delete("/api/slots/10/assign")).status_code == 204
    board = (await client.get("/api/board")).json()
    s = [m for d in board["days"] for m in d["missions"]][0]["slots"][0]
    assert [a["username"] for a in s["assigned"]] == ["Zwei"]
    assert [w["username"] for w in s["waitlist"]] == ["Drei"]
    assert len(sent_dms) == 1 and sent_dms[0]["user_id"] == "2"
    assert "nachgerückt" in sent_dms[0]["content"]


async def test_join_doppelt_409(client, crime_data):
    crime_data["missions"] = [mission(1, [slot(10, required=1)])]
    as_user(client, "1", "Eins")
    await client.post("/api/slots/10/assign", json={"mission_id": 1})
    as_user(client, "2", "Zwei")
    assert (await client.post("/api/slots/10/waitlist", json={"mission_id": 1})).status_code == 201
    assert (await client.post("/api/slots/10/waitlist", json={"mission_id": 1})).status_code == 409


async def test_leave_waitlist(client, crime_data):
    crime_data["missions"] = [mission(1, [slot(10, required=1)])]
    as_user(client, "1", "Eins")
    await client.post("/api/slots/10/assign", json={"mission_id": 1})
    as_user(client, "2", "Zwei")
    await client.post("/api/slots/10/waitlist", json={"mission_id": 1})
    assert (await client.delete("/api/slots/10/waitlist")).status_code == 204
    assert (await client.delete("/api/slots/10/waitlist")).status_code == 404


async def test_promote_ueberbucht_nie(client, crime_data, sent_dms):
    """Kapazitaets-Invariante: auch mit Warteliste landen nie mehr als
    required_count Spieler im Slot (Fix aus dem Review)."""
    crime_data["missions"] = [mission(1, [slot(10, required=2)])]
    for uid, name in (("1", "Eins"), ("2", "Zwei")):
        as_user(client, uid, name)
        await client.post("/api/slots/10/assign", json={"mission_id": 1})
    for uid, name in (("3", "Drei"), ("4", "Vier"), ("5", "Fuenf")):
        as_user(client, uid, name)
        await client.post("/api/slots/10/waitlist", json={"mission_id": 1})

    as_user(client, "1", "Eins")
    await client.delete("/api/slots/10/assign")
    board = (await client.get("/api/board")).json()
    s = [m for d in board["days"] for m in d["missions"]][0]["slots"][0]
    assert s["assigned_count"] == 2  # nie > required
    assert [a["username"] for a in s["assigned"]] == ["Zwei", "Drei"]
    assert [w["username"] for w in s["waitlist"]] == ["Vier", "Fuenf"]


async def test_promote_gegen_parallel_assign_nie_ueberbucht(crime_data, sent_dms):
    """Kapazitaets-Race zwischen Nachruecken und Direkt-Eintragen: waehrend
    ein freiwerdender Platz per Warteliste nachrueckt, versucht parallel ein
    weiterer Spieler die Direkt-Buchung. Egal wie es sich verschraenkt: der
    Slot darf nie mehr als required_count halten (Review-Fix insert-then-count
    in _promote_waitlist). Auf korrektem Code immer gruen."""
    crime_data["missions"] = [mission(1, [slot(10, required=1)])]
    async with fresh_client("1", "Eins") as c1:
        assert (await c1.post("/api/slots/10/assign", json={"mission_id": 1})).status_code == 201
        async with fresh_client("2", "Zwei") as c2:
            await c2.post("/api/slots/10/waitlist", json={"mission_id": 1})
            async with fresh_client("3", "Drei") as c3:
                # Eins geht (loest Nachruecken von Zwei aus) — gleichzeitig
                # will Drei den Platz direkt
                await asyncio.gather(
                    c1.delete("/api/slots/10/assign"),
                    c3.post("/api/slots/10/assign", json={"mission_id": 1}),
                )
    async with SessionLocal() as s:
        n = await s.scalar(select(func.count()).select_from(SlotAssignment)
                           .where(SlotAssignment.slot_id == 10))
    assert n == 1  # nie ueberbucht, egal wer den Platz bekam
