"""Discord-Bot. Eigener Prozess. Sendet Missionen, hört auf Reaktionen.

Kommuniziert mit Backend via interner HTTP-API auf 127.0.0.1:8001.

Start: python -m backend.bot
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from pathlib import Path

import discord
from aiohttp import web
from sqlalchemy import select

from .config import settings
from .db import SessionLocal, init_db
from .models import ExpiryMessage, Mission, MissionStatus, ReactionMessage

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


_watchers_started = False


@client.event
async def on_ready():
    global _watchers_started
    log.info("Bot ready as %s (id=%s)", client.user, client.user.id if client.user else "?")
    if not _watchers_started:
        _watchers_started = True
        client.loop.create_task(_deadline_watcher())
        client.loop.create_task(_scheduled_send_watcher())


async def _scheduled_send_watcher():
    """Background-Loop: alle 30 Sek alle DRAFT-Missions mit fälligem
    scheduled_send_at automatisch senden."""
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            await _check_scheduled_sends_once()
        except Exception:
            log.exception("scheduled send watcher tick failed")
        await asyncio.sleep(30)


async def _check_scheduled_sends_once() -> None:
    now = datetime.utcnow()
    async with SessionLocal() as session:
        result = await session.execute(
            select(Mission).where(
                Mission.status == MissionStatus.DRAFT,
                Mission.archived_at.is_(None),
                Mission.scheduled_send_at.is_not(None),
                Mission.scheduled_send_at <= now,
            )
        )
        for m in result.scalars().all():
            ok, err = await _post_mission_to_discord(session, m)
            if ok:
                log.info("scheduled mission %s sent", m.id)
            else:
                log.warning("scheduled send for mission %s failed: %s", m.id, err)
                # Reset, damit nicht endlos retry
                m.scheduled_send_at = None
                await session.commit()


async def _deadline_watcher():
    """Background-Loop: alle 30 Sek alle PENDING-Missions mit abgelaufener
    Deadline finden, im Auftrags-Channel 'Du hast versagt!' posten und Status
    auf REJECTED setzen."""
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            await _check_deadlines_once()
        except Exception:
            log.exception("deadline watcher tick failed")
        await asyncio.sleep(30)


async def _check_deadlines_once() -> None:
    now = datetime.utcnow()
    async with SessionLocal() as session:
        result = await session.execute(
            select(Mission).where(
                Mission.status == MissionStatus.PENDING,
                Mission.archived_at.is_(None),
                Mission.deadline_at.is_not(None),
                Mission.deadline_at < now,
            )
        )
        for m in result.scalars().all():
            await _expire_mission(m, session)


async def _pick_expiry_text(session) -> str:
    """Wählt zufällig einen Spruch aus dem Pool. Fallback: 'Du hast versagt!'."""
    res = await session.execute(select(ExpiryMessage))
    pool = list(res.scalars().all())
    if pool:
        return random.choice(pool).text
    return "**Du hast versagt!**"


async def _pick_reaction_text() -> str | None:
    """Reaktions-Reply zufällig aus Pool. Fallback: 'Alles klar, wir melden uns.'"""
    async with SessionLocal() as session:
        res = await session.execute(select(ReactionMessage))
        pool = list(res.scalars().all())
        if pool:
            return random.choice(pool).text
    return "Alles klar, wir melden uns."


async def _expire_mission(mission: Mission, session) -> None:
    posted_msg = None
    msg_text = await _pick_expiry_text(session)

    if mission.discord_channel_id:
        try:
            channel = client.get_channel(int(mission.discord_channel_id))
            if channel is None:
                channel = await client.fetch_channel(int(mission.discord_channel_id))

            reply_target = None
            if mission.discord_message_id:
                try:
                    reply_target = await channel.fetch_message(int(mission.discord_message_id))
                except Exception:
                    reply_target = None

            if reply_target:
                posted_msg = await reply_target.reply(msg_text)
                # Reaktions-Emojis von der Original-Message entfernen
                for emoji in REACT_EMOJIS:
                    try:
                        await reply_target.clear_reaction(emoji)
                    except Exception:
                        pass
            else:
                posted_msg = await channel.send(msg_text)
        except Exception as exc:
            log.warning("expiry post for mission %s failed: %s", mission.id, exc)

    if posted_msg:
        mission.expiry_message_id = str(posted_msg.id)
    mission.expiry_text = msg_text
    mission.status = MissionStatus.REJECTED
    mission.reacted_at = datetime.utcnow()
    await session.commit()
    log.info("Mission %s expired (deadline %s)", mission.id, mission.deadline_at)


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

    # Reaktions-Reply: zufällig aus Pool, Reply-ID + Text auf Mission speichern
    try:
        reply_text = await _pick_reaction_text()
        if reply_text:
            message = await _fetch_message(payload)
            posted_reply = await message.reply(reply_text)
            async with SessionLocal() as session:
                res = await session.execute(
                    select(Mission).where(Mission.discord_message_id == str(payload.message_id))
                )
                mission = res.scalar_one_or_none()
                if mission:
                    mission.reaction_reply_message_id = str(posted_reply.id)
                    mission.reaction_reply_text = reply_text
                    await session.commit()
    except Exception as exc:
        log.warning("reaction reply failed: %s", exc)


# ---- Internal HTTP API (Backend → Bot) ----


async def _post_mission_to_discord(session, mission: Mission) -> tuple[bool, str | None]:
    """Sendet eine DRAFT-Mission an Discord, setzt sent_at + status PENDING +
    discord_message_id, leert scheduled_send_at. Returns (ok, error)."""
    if not mission.discord_channel_id:
        return False, "kein discord_channel_id"
    if mission.status != MissionStatus.DRAFT:
        return False, f"status ist {mission.status.value}, nicht draft"

    channel = client.get_channel(int(mission.discord_channel_id))
    if channel is None:
        try:
            channel = await client.fetch_channel(int(mission.discord_channel_id))
        except Exception as exc:
            return False, f"channel: {exc}"

    content = mission.content_final or mission.content_generated
    if mission.deadline_at:
        unix_ts = int(mission.deadline_at.replace(tzinfo=timezone.utc).timestamp())
        content = f"{content}\n\n⏳ **Deadline:** <t:{unix_ts}:F> (<t:{unix_ts}:R>)"
    files: list[discord.File] = []
    if mission.image_path:
        p = Path(mission.image_path)
        if p.exists():
            files.append(discord.File(str(p), filename=p.name))

    try:
        msg = await channel.send(content=content, files=files)
    except Exception as exc:
        log.exception("send failed")
        return False, str(exc)

    for emoji in REACT_EMOJIS:
        try:
            await msg.add_reaction(emoji)
        except Exception:
            log.warning("reaction failed for %s", emoji)

    mission.discord_message_id = str(msg.id)
    mission.status = MissionStatus.PENDING
    mission.sent_at = datetime.utcnow()
    mission.scheduled_send_at = None
    await session.commit()
    return True, None


async def http_send_mission(request: web.Request) -> web.Response:
    """POST /send  body: {mission_id: int}"""
    data = await request.json()
    mission_id = int(data["mission_id"])

    async with SessionLocal() as session:
        result = await session.execute(select(Mission).where(Mission.id == mission_id))
        mission = result.scalar_one_or_none()
        if mission is None:
            return web.json_response({"error": "mission not found"}, status=404)

        ok, err = await _post_mission_to_discord(session, mission)
        if not ok:
            status_code = 400 if err and ("status" in err or "discord_channel_id" in err) else 500
            return web.json_response({"error": err}, status=status_code)

    return web.json_response({"ok": True, "message_id": mission.discord_message_id})


async def http_read_channel(request: web.Request) -> web.Response:
    """POST /read_channel  body: {channel_id: str, after_iso: str|null, limit: int}"""
    data = await request.json()
    try:
        channel_id = int(data["channel_id"])
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "channel_id ungültig"}, status=400)
    after_iso = data.get("after_iso")
    limit = int(data.get("limit", 100))
    oldest_first = bool(data.get("oldest_first", True))

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
        async for m in channel.history(limit=limit, after=after_dt, oldest_first=oldest_first):
            if m.author.bot:
                continue
            attachments = []
            for att in m.attachments:
                attachments.append({
                    "url": att.url,
                    "proxy_url": att.proxy_url,
                    "filename": att.filename,
                    "content_type": att.content_type or "",
                    "width": att.width,
                    "height": att.height,
                })
            messages.append({
                "message_id": str(m.id),
                "author": m.author.display_name or m.author.name,
                "content": m.content or "",
                "posted_at": m.created_at.replace(tzinfo=None).isoformat(),
                "attachments": attachments,
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
