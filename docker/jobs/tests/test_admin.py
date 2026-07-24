# -*- coding: utf-8 -*-
"""Admin-Funktionen: Kick, Anwesenheit, Audit-Log, CSV-Export."""
from sqlalchemy import select

from .conftest import mission, slot
from src import main as app_main
from src.db import SessionLocal
from src.models import AdminAction, CompletedParticipation, SlotAssignment


async def test_admin_kick_mit_audit(client, admin, crime_data, sent_dms):
    crime_data["missions"] = [mission(1, [slot(10)])]
    # Spieler eintragen (direkt in die DB, einfacher als Cookie-Wechsel)
    async with SessionLocal() as s:
        s.add(SlotAssignment(slot_id=10, mission_id=1, player_discord_id="5", username="Opfer"))
        await s.commit()

    r = await admin.delete("/api/admin/assignments/10/5")
    assert r.status_code == 204
    async with SessionLocal() as s:
        # Eintragung ist tatsaechlich geloescht
        assert (await s.execute(select(SlotAssignment))).scalars().all() == []
        rows = (await s.execute(select(AdminAction))).scalars().all()
    assert len(rows) == 1
    assert rows[0].action == "kick"
    assert rows[0].target_username == "Opfer"
    assert rows[0].admin_username == "Admin"
    # Zweiter Kick derselben (schon weg) -> 404
    assert (await admin.delete("/api/admin/assignments/10/5")).status_code == 404

    audit = (await admin.get("/api/admin/audit")).json()
    assert audit["actions"][0]["action"] == "kick"


async def test_attendance_validierung(admin, crime_data):
    r = await admin.post("/api/admin/attendance/10/5", json={})
    assert r.status_code == 422  # fehlender Key darf KEIN No-Show sein
    r = await admin.post("/api/admin/attendance/10/5", json={"attended": "ja"})
    assert r.status_code == 422
    r = await admin.post("/api/admin/attendance/10/5", json={"attended": True})
    assert r.status_code == 404  # kein Eintrag vorhanden


async def test_attendance_setzt_beide_tabellen(admin, crime_data):
    async with SessionLocal() as s:
        s.add(SlotAssignment(slot_id=10, mission_id=1, player_discord_id="5", username="P"))
        s.add(CompletedParticipation(slot_id=10, mission_id=1, player_discord_id="5", username="P"))
        await s.commit()
    r = await admin.post("/api/admin/attendance/10/5", json={"attended": True})
    assert r.status_code == 200
    async with SessionLocal() as s:
        live = (await s.execute(select(SlotAssignment))).scalars().one()
        hist = (await s.execute(select(CompletedParticipation))).scalars().one()
    assert live.attended == 1 and hist.attended == 1
    # Zuruecknehmen — beide Tabellen zurueck auf None
    await admin.post("/api/admin/attendance/10/5", json={"attended": None})
    async with SessionLocal() as s:
        live = (await s.execute(select(SlotAssignment))).scalars().one()
        hist = (await s.execute(select(CompletedParticipation))).scalars().one()
    assert live.attended is None
    assert hist.attended is None


async def test_csv_export(admin, crime_data):
    crime_data["missions"] = [mission(1, [slot(10, required=2)])]
    async with SessionLocal() as s:
        s.add(SlotAssignment(slot_id=10, mission_id=1, player_discord_id="5",
                             username="Spieler X", attended=1))
        await s.commit()
    r = await admin.get("/api/admin/export.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    text = r.text
    assert "Spieler X" in text
    assert "erschienen" in text
    assert "Sindaccos" in text


async def test_csv_formel_injektion_entschaerft(admin, crime_data):
    """Discord-Namen sind fremdgesteuert — fuehrende =,+,-,@ duerfen in
    Excel nie als Formel ankommen."""
    crime_data["missions"] = [mission(1, [slot(10)])]
    async with SessionLocal() as s:
        s.add(SlotAssignment(slot_id=10, mission_id=1, player_discord_id="6",
                             username="=HYPERLINK(evil)"))
        await s.commit()
    text = (await admin.get("/api/admin/export.csv")).text
    assert "'=HYPERLINK(evil)" in text
    assert ";=HYPERLINK" not in text
