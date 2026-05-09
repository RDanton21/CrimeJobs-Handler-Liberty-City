"""Discord-Bot. Eigener Prozess. Sendet Missionen, hört auf Reaktionen.

Kommuniziert mit Backend via interner HTTP-API auf 127.0.0.1:8001.

Start: python -m backend.bot
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

import discord
from aiohttp import web
from sqlalchemy import select

from .config import settings
from .db import SessionLocal, init_db
from .models import Mission, MissionStatus

log = logging.getLogger("crime-bot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

THUMB_UP = "👍"
THUMB_DOWN = "👎"
NOT_DOABLE = "❌"

REACT_EMOJIS = [THUMB_UP, THUMB_DOWN, NOT_DOABLE]


intents = discord.Intents.default()
intents.message_content = False
intents.reactions = True
intents.guilds = True

client = discord.Client(intents=intents)


async def _update_mission_from_reaction(message_id: int, emoji_str: str) -> bool:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Mission).where(Mission.discord_message_id == str(message_id))
        )
        mission = result.scalar_one_or_none()
        if mission is None:
            return False
        if mission.status != MissionStatus.PENDING:
            return False

        if emoji_str == THUMB_UP:
            mission.status = MissionStatus.APPROVED
        elif emoji_str == THUMB_DOWN:
            mission.status = MissionStatus.REJECTED
        elif emoji_str == NOT_DOABLE:
            mission.status = MissionStatus.CANCELLED
        else:
            return False

        mission.reacted_at = datetime.utcnow()
        await session.commit()
        log.info("Mission %s -> %s", mission.id, mission.status.value)
        return True


@client.event
async def on_ready():
    log.info("Bot ready as %s (id=%s)", client.user, client.user.id if client.user else "?")


async def _fetch_message(payload: discord.RawReactionActionEvent):
    channel = client.get_channel(payload.channel_id) or await client.fetch_channel(payload.channel_id)
    return await channel.fetch_message(payload.message_id)


@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if client.user and payload.user_id == client.user.id:
        return
    emoji_str = str(payload.emoji)

    # Fremd-Emoji: User-Reaktion entfernen (braucht Manage-Messages Permission)
    if emoji_str not in REACT_EMOJIS:
        try:
            message = await _fetch_message(payload)
            user = await client.fetch_user(payload.user_id)
            await message.remove_reaction(payload.emoji, user)
        except discord.Forbidden:
            log.warning("Manage-Messages Permission fehlt - Fremd-Emoji bleibt sichtbar")
        except Exception as exc:
            log.warning("cleanup foreign reaction failed: %s", exc)
        return

    changed = await _update_mission_from_reaction(payload.message_id, emoji_str)

    if not changed:
        # Mission war nicht mehr PENDING -> User-Reaktion entfernen (Single-Vote-Enforcement)
        try:
            message = await _fetch_message(payload)
            user = await client.fetch_user(payload.user_id)
            await message.remove_reaction(payload.emoji, user)
        except discord.Forbidden:
            log.warning("Manage-Messages Permission fehlt - Mehrfach-Reaktion bleibt sichtbar")
        except Exception as exc:
            log.warning("cleanup late reaction failed: %s", exc)
        return

    # Erfolg: andere Bot-Emojis entfernen (verhindert Anzeige der nicht-gewaehlten Optionen)
    try:
        message = await _fetch_message(payload)
        for other_emoji in REACT_EMOJIS:
            if other_emoji == emoji_str:
                continue
            try:
                await message.remove_reaction(other_emoji, client.user)
            except Exception:
                pass
    except Exception as exc:
        log.warning("cleanup other emojis failed: %s", exc)


# ---- Internal HTTP API (Backend → Bot) ----


async def http_send_mission(request: web.Request) -> web.Response:
    """POST /send  body: {mission_id: int}"""
    data = await request.json()
    mission_id = int(data["mission_id"])

    async with SessionLocal() as session:
        result = await session.execute(select(Mission).where(Mission.id == mission_id))
        mission = result.scalar_one_or_none()
        if mission is None:
            return web.json_response({"error": "mission not found"}, status=404)
        if not mission.discord_channel_id:
            return web.json_response({"error": "kein discord_channel_id"}, status=400)
        if mission.status != MissionStatus.DRAFT:
            return web.json_response({"error": f"status ist {mission.status.value}, nicht draft"}, status=400)

        channel = client.get_channel(int(mission.discord_channel_id))
        if channel is None:
            try:
                channel = await client.fetch_channel(int(mission.discord_channel_id))
            except Exception as exc:
                return web.json_response({"error": f"channel: {exc}"}, status=500)

        content = mission.content_final or mission.content_generated
        files: list[discord.File] = []
        if mission.image_path:
            p = Path(mission.image_path)
            if p.exists():
                files.append(discord.File(str(p), filename=p.name))

        try:
            msg = await channel.send(content=content, files=files)
        except Exception as exc:
            log.exception("send failed")
            return web.json_response({"error": str(exc)}, status=500)

        for emoji in REACT_EMOJIS:
            try:
                await msg.add_reaction(emoji)
            except Exception:
                log.warning("reaction failed for %s", emoji)

        mission.discord_message_id = str(msg.id)
        mission.status = MissionStatus.PENDING
        mission.sent_at = datetime.utcnow()
        await session.commit()

    return web.json_response({"ok": True, "message_id": str(msg.id)})


async def http_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "ready": client.is_ready()})


async def http_delete_message(request: web.Request) -> web.Response:
    """POST /delete_message  body: {channel_id: str, message_id: str}"""
    data = await request.json()
    channel_id = int(data["channel_id"])
    message_id = int(data["message_id"])
    try:
        channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
        message = await channel.fetch_message(message_id)
        await message.delete()
    except discord.NotFound:
        return web.json_response({"ok": True, "note": "already deleted"})
    except discord.Forbidden:
        return web.json_response({"error": "forbidden - manage messages permission?"}, status=403)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)
    return web.json_response({"ok": True})


def build_http_app() -> web.Application:
    app = web.Application()
    app.add_routes([
        web.post("/send", http_send_mission),
        web.post("/delete_message", http_delete_message),
        web.get("/health", http_health),
    ])
    return app


async def main():
    await init_db()
    if not settings.discord_bot_token:
        raise RuntimeError("DISCORD_BOT_TOKEN fehlt in .env")

    runner = web.AppRunner(build_http_app())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8001)
    await site.start()
    log.info("Bot HTTP API auf http://127.0.0.1:8001")

    try:
        await client.start(settings.discord_bot_token)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
