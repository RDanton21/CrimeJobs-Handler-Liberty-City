# -*- coding: utf-8 -*-
"""Eigene Bilanz + Historien-Festschreibung archivierter Auftraege."""
from sqlalchemy import select

from .conftest import mission, slot
from src.db import SessionLocal
from src.models import CompletedParticipation, SlotAssignment


async def test_me_stats_leer(player, crime_data):
    data = (await player.get("/api/me/stats")).json()
    assert data["missions_done"] == 0
    assert data["history"] == []
    assert data["open"] == 0


async def test_me_stats_mit_historie(player, crime_data):
    async with SessionLocal() as s:
        s.add(CompletedParticipation(slot_id=10, mission_id=1, player_discord_id="1",
                                     username="P", crew_name="Sindaccos",
                                     slot_name="Tankwart", attended=1))
        s.add(CompletedParticipation(slot_id=11, mission_id=1, player_discord_id="1",
                                     username="P", crew_name="Sindaccos",
                                     slot_name="Fahrer", attended=0))
        # fremder Spieler darf NICHT auftauchen
        s.add(CompletedParticipation(slot_id=10, mission_id=1, player_discord_id="2",
                                     username="Anderer"))
        s.add(SlotAssignment(slot_id=20, mission_id=2, player_discord_id="1", username="P"))
        await s.commit()
    data = (await player.get("/api/me/stats")).json()
    assert data["missions_done"] == 1
    assert data["slots_done"] == 2
    assert data["attended"] == 1
    assert data["no_show"] == 1
    assert data["open"] == 1
    assert len(data["history"]) == 2
    assert {h["slot_name"] for h in data["history"]} == {"Tankwart", "Fahrer"}


async def test_archivierter_auftrag_schreibt_historie(player, crime_data):
    """Board-Aufruf mit archivierter Mission uebernimmt Eintragungen in die
    Historie — inkl. live gesetzter Anwesenheit (Review-Fix Lost Update)."""
    crime_data["missions"] = [mission(1, [slot(10)], archived=True)]
    async with SessionLocal() as s:
        s.add(SlotAssignment(slot_id=10, mission_id=1, player_discord_id="1",
                             username="P", attended=1))
        await s.commit()
    await player.get("/api/board")
    async with SessionLocal() as s:
        hist = (await s.execute(select(CompletedParticipation))).scalars().all()
    assert len(hist) == 1
    assert hist[0].crew_name == "Sindaccos"
    assert hist[0].attended == 1  # live-Wert uebernommen


async def test_record_completed_liest_live_nicht_snapshot(crime_data):
    """Regression Lost-Update: _record_completed bekommt einen VERALTETEN
    Snapshot (attended=None), die DB hat aber schon attended=1. Die Historie
    muss den DB-Wert tragen, nicht den Snapshot — sonst revertiert ein
    spaeter Board-Refresh eine frische Admin-Bewertung. Erkennt den Revert
    des Fixes, weil direkt gegen _record_completed getestet wird."""
    from src.main import _record_completed
    from .conftest import mission, slot
    async with SessionLocal() as s:
        s.add(SlotAssignment(slot_id=10, mission_id=1, player_discord_id="1",
                             username="P", attended=1))
        await s.commit()
    # Snapshot wie ihn ein alter, in-flight Board-Request gelesen haette:
    stale = SlotAssignment(slot_id=10, mission_id=1, player_discord_id="1",
                           username="P", attended=None)
    missions = [mission(1, [slot(10)], archived=True)]

    # Erst-Anlage darf NICHT den stalen None-Wert schreiben
    await _record_completed(missions, {10: [stale]})
    async with SessionLocal() as s:
        hist = (await s.execute(select(CompletedParticipation))).scalars().one()
    assert hist.attended == 1

    # Live-Wert wechselt auf 0 -> naechster _record_completed zieht nach
    async with SessionLocal() as s:
        row = (await s.execute(select(SlotAssignment))).scalars().one()
        row.attended = 0
        await s.commit()
    await _record_completed(missions, {10: [stale]})
    async with SessionLocal() as s:
        hist = (await s.execute(select(CompletedParticipation))).scalars().one()
    assert hist.attended == 0


async def test_dismissed_mission_verschwindet(admin, crime_data):
    crime_data["missions"] = [mission(1, [slot(10)], archived=True)]
    r = await admin.post("/api/admin/clear-completed")
    assert r.json()["removed"] == 1
    board = (await admin.get("/api/board")).json()
    assert all(not d["missions"] for d in board["days"])
