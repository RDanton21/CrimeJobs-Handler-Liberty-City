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
intents.message_content = True  # Privileged Intent! Im Discord Developer Portal aktivieren.
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


async def http_read_channel(request: web.Request) -> web.Response:
    """POST /read_channel  body: {channel_id: str, after_iso: str|null, limit: int}"""
    data = await request.json()
    try:
        channel_id = int(data["channel_id"])
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "channel_id ungültig"}, status=400)
    after_iso = data.get("after_iso")
    limit = int(data.get("limit", 100))

    after_dt = None
    if after_iso:
        try:
            after_dt = datetime.fromisoformat(after_iso)
        except ValueError:
            after_dt = None

    try:
        channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
    except discord.NotFound:
        return web.json_response({"error": "channel not found"}, status=404)
    except discord.Forbidden:
        return web.json_response({"error": "forbidden - bot has no access to channel"}, status=403)
    except Exception as exc:
        return web.json_response({"error": f"channel: {exc}"}, status=500)

    messages: list[dict] = []
    try:
        async for m in channel.history(limit=limit, after=after_dt, oldest_first=True):
            if m.author.bot:
                continue
            messages.append({
                "message_id": str(m.id),
                "author": m.author.display_name or m.author.name,
                "content": m.content or "",
                "posted_at": m.created_at.replace(tzinfo=None).isoformat(),
            })
    except discord.Forbidden:
        return web.json_response(
            {"error": "forbidden - read message history permission?"}, status=403
        )
    except Exception as exc:
        log.exception("read_channel failed")
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response(messages)


async def http_delete_in_range(request: web.Request) -> web.Response:
    """POST /delete_in_range  body: {channel_id: str, after_iso: str|null, before_iso: str|null}

    Löscht alle Nicht-Bot-Nachrichten im Channel zwischen after und before (exclusive)."""
    data = await request.json()
    try:
        channel_id = int(data["channel_id"])
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "channel_id ungültig"}, status=400)

    after_iso = data.get("after_iso")
    before_iso = data.get("before_iso")
    after_dt = None
    before_dt = None
    if after_iso:
        try:
            after_dt = datetime.fromisoformat(after_iso)
        except ValueError:
            after_dt = None
    if before_iso:
        try:
            before_dt = datetime.fromisoformat(before_iso)
        except ValueError:
            before_dt = None

    try:
        channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
    except discord.NotFound:
        return web.json_response({"ok": True, "deleted": 0, "note": "channel not found"})
    except discord.Forbidden:
        return web.json_response({"error": "forbidden - channel access?"}, status=403)
    except Exception as exc:
        return web.json_response({"error": f"channel: {exc}"}, status=500)

    deleted = 0
    failed = 0
    try:
        async for m in channel.history(limit=200, after=after_dt, oldest_first=True):
            ts = m.created_at.replace(tzinfo=None)
            if before_dt and ts >= before_dt:
                break
            if m.author.bot:
                continue
            try:
                await m.delete()
                deleted += 1
            except discord.NotFound:
                pass
            except discord.Forbidden:
                failed += 1
            except Exception:
                failed += 1
    except discord.Forbidden:
        return web.json_response(
            {"error": "forbidden - manage messages permission?", "deleted": deleted},
            status=403,
        )
    except Exception as exc:
        log.exception("delete_in_range failed")
        return web.json_response(
            {"error": str(exc), "deleted": deleted, "failed": failed}, status=500
        )

    return web.json_response({"ok": True, "deleted": deleted, "failed": failed})


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
        web.post("/delete_in_range", http_delete_in_range),
        web.post("/read_channel", http_read_channel),
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
