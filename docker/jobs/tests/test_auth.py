# -*- coding: utf-8 -*-
"""Auth-Grundregeln: ohne Session 401, Admin-Endpoints nur fuer Admins."""


async def test_api_ohne_login_401(client):
    for path in ("/api/me", "/api/board", "/api/me/stats",
                 "/api/admin/stats", "/api/admin/audit", "/api/admin/export.csv"):
        r = await client.get(path)
        assert r.status_code == 401, path


async def test_admin_endpoints_403_fuer_spieler(player, crime_data):
    assert (await player.get("/api/admin/stats")).status_code == 403
    assert (await player.get("/api/admin/audit")).status_code == 403
    assert (await player.get("/api/admin/export.csv")).status_code == 403
    assert (await player.post("/api/admin/clear-completed")).status_code == 403
    r = await player.post("/api/admin/attendance/10/1", json={"attended": True})
    assert r.status_code == 403
    assert (await player.delete("/api/admin/assignments/10/1")).status_code == 403


async def test_me_liefert_session_daten(player):
    r = await player.get("/api/me")
    assert r.status_code == 200
    data = r.json()
    assert data["discord_user_id"] == "1"
    assert data["is_admin"] is False


async def test_manipuliertes_cookie_401(client):
    client.cookies.set("jobs_session", "kaputt.abc.def")
    assert (await client.get("/api/me")).status_code == 401
