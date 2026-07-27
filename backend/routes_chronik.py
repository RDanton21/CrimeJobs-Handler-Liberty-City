"""Chronik-Karten: Galerie + Auto-Post-Konfiguration (Dashboard-Reiter)."""
import os
import subprocess
import sys

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from . import chronik
from .auth import require_admin
from .config import settings
from .db import get_session
from .settings_store import get as settings_get, set_value as settings_set

router = APIRouter(prefix="/api/chronik", tags=["chronik"],
                   dependencies=[Depends(require_admin)])

_SCRIPT = os.path.join(chronik._APP, "scripts", "chronik_render.py")


async def _config(session: AsyncSession) -> dict:
    enabled = (await settings_get(session, "chronik_enabled", "false")).lower() in ("1", "true", "yes", "on")
    return {
        "enabled": enabled,
        "channel_id": await settings_get(session, "chronik_channel_id", ""),
        "time": await settings_get(session, "chronik_time", "09:00"),
        "next_index": int(await settings_get(session, "chronik_next_index", "0") or "0"),
        "last_date": await settings_get(session, "chronik_last_date", ""),
    }


@router.get("/cards")
async def list_cards(session: AsyncSession = Depends(get_session)):
    cfg = await _config(session)
    ni = cfg["next_index"]
    cards = []
    for i, c in enumerate(chronik.ordered_cards()):
        cards.append({
            "index": i,
            "date": c["date"],
            "filename": c["filename"],
            "exists": c["exists"],
            "url": f"/api/chronik/card/{c['filename']}",
            "status": "posted" if i < ni else ("next" if i == ni else "queued"),
        })
    return {"cards": cards, "config": cfg, "total": len(cards)}


@router.get("/card/{filename}")
async def get_card(filename: str):
    p = chronik.card_path(filename)
    if not p:
        raise HTTPException(404, "Karte nicht gefunden")
    return FileResponse(p, media_type="image/png")


class ConfigIn(BaseModel):
    enabled: bool | None = None
    channel_id: str | None = None
    time: str | None = None


@router.post("/config")
async def save_config(payload: ConfigIn, session: AsyncSession = Depends(get_session)):
    if payload.enabled is not None:
        await settings_set(session, "chronik_enabled", "true" if payload.enabled else "false")
    if payload.channel_id is not None:
        await settings_set(session, "chronik_channel_id", payload.channel_id.strip())
    if payload.time is not None:
        await settings_set(session, "chronik_time", payload.time.strip())
    return await _config(session)


@router.post("/reset")
async def reset_progress(session: AsyncSession = Depends(get_session)):
    """Fortschritt auf Anfang (naechste Karte = erste)."""
    await settings_set(session, "chronik_next_index", "0")
    await settings_set(session, "chronik_last_date", "")
    return await _config(session)


@router.post("/regenerate")
async def regenerate():
    if not os.path.exists(_SCRIPT):
        raise HTTPException(500, "Renderer-Skript fehlt im Container")
    try:
        r = subprocess.run([sys.executable, _SCRIPT], capture_output=True, text=True, timeout=120)
    except Exception as exc:
        raise HTTPException(500, f"Renderer-Fehler: {exc}") from exc
    if r.returncode != 0:
        raise HTTPException(500, f"Renderer fehlgeschlagen: {(r.stderr or r.stdout)[-400:]}")
    return {"ok": True, "output": (r.stdout or "").strip(),
            "count": sum(1 for c in chronik.ordered_cards() if c["exists"])}


@router.post("/post-now")
async def post_now():
    """Postet die naechste Karte sofort (via Bot-API)."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as cli:
            resp = await cli.post(f"{settings.bot_api_url}/post_chronik_now")
    except httpx.RequestError as exc:
        raise HTTPException(502, f"Bot nicht erreichbar: {exc}") from exc
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, resp.text)
    return resp.json()
