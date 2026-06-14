"""SEKTOR Countdown-Bot — verwaltet mehrere Countdowns parallel.

Liest countdowns.json (Hot-Reload), rendert pro Countdown eine Karte und
postet/aktualisiert sie im jeweiligen Channel. Bei Ablauf: frische Nachricht
mit @everyone-Ping + YouTube-Link. countdowns.json wird vom Admin-Panel
(admin.py) gepflegt.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord.ext import tasks
from dotenv import load_dotenv

from renderer import render_card

ROOT = Path(__file__).parent
COUNTDOWNS_PATH = ROOT / "countdowns.json"
STATE_PATH = ROOT / "state.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("countdown")


# ── Persistenz ───────────────────────────────────────────
def load_countdowns() -> dict:
    """countdowns.json lesen (Hot-Reload bei jedem Loop-Tick)."""
    try:
        data = json.loads(COUNTDOWNS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("kein Objekt")
        data.setdefault("update_seconds", 60)
        data.setdefault("countdowns", [])
        return data
    except FileNotFoundError:
        return {"update_seconds": 60, "countdowns": []}
    except Exception as e:
        log.warning("countdowns.json Lesefehler: %s", e)
        return {"update_seconds": 60, "countdowns": []}


def load_state() -> dict:
    """state.json lesen. Alt-Format {'message_id': N} wird migriert."""
    if not STATE_PATH.exists():
        return {}
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    if "message_id" in raw:   # Alt-Format -> erster Countdown adoptiert die ID
        return {"__legacy_mid__": raw.get("message_id")}
    return raw


def save_state(st: dict) -> None:
    try:
        STATE_PATH.write_text(json.dumps(st, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("state.json Schreibfehler: %s", e)


state = load_state()

intents = discord.Intents.default()
client = discord.Client(intents=intents)

UPDATE_SECONDS = int(load_countdowns().get("update_seconds", 60))


# ── Helpers ──────────────────────────────────────────────
def _fmt_card_date(dt: datetime) -> str:
    off = dt.utcoffset()
    tz = ""
    if off is not None:
        tz = {2: "MESZ", 1: "MEZ"}.get(int(off.total_seconds() // 3600),
                                       dt.tzname() or "")
    return f"{dt.strftime('%d.%m.%Y')}  ·  {dt.strftime('%H:%M')} {tz}".rstrip()


def build_embed(expired: bool) -> discord.Embed:
    emb = discord.Embed(color=0x02EAFF if expired else 0xE64560)
    emb.set_image(url="attachment://countdown.png")
    emb.set_footer(text="Aktualisiert automatisch · 5ektor.de")
    return emb


async def _get_channel(channel_id: int):
    ch = client.get_channel(channel_id)
    if ch is None:
        try:
            ch = await client.fetch_channel(channel_id)
        except Exception as exc:
            log.error("Channel %s nicht erreichbar: %s", channel_id, exc)
            return None
    return ch


# ── Ein Countdown verarbeiten ────────────────────────────
async def process_countdown(cd: dict) -> None:
    cid = cd.get("id")
    if not cid:
        return
    try:
        channel_id = int(cd["channel_id"])
        target = datetime.fromisoformat(cd["target_iso"])
    except (KeyError, ValueError, TypeError) as e:
        log.warning("Countdown %s ungueltig: %s", cid, e)
        return

    st = state.get(cid)
    if st is None:
        legacy = state.pop("__legacy_mid__", None)   # erster Countdown adoptiert Alt-ID
        st = {"message_id": legacy, "live_posted": False} if legacy else {}
        state[cid] = st

    if st.get("live_posted"):
        return   # Countdown abgelaufen + Live-Nachricht bereits gepostet

    channel = await _get_channel(channel_id)
    if channel is None:
        return

    now = datetime.now(timezone.utc)
    expired = now >= target
    youtube = str(cd.get("youtube_url", "")).strip()

    buf = render_card(now, target, badge=cd.get("badge", ""),
                      title=cd.get("title", ""), subtitle=cd.get("subtitle", ""),
                      date_str=_fmt_card_date(target))
    file = discord.File(buf, filename="countdown.png")
    embed = build_embed(expired)

    message = None
    mid = st.get("message_id")
    if mid:
        try:
            message = await channel.fetch_message(int(mid))
        except discord.NotFound:
            message = None
        except discord.HTTPException as exc:
            log.warning("fetch_message (%s) Fehler: %s", cid, exc)
            return

    # ── Live: einmalig frische Nachricht mit @everyone-Ping ──
    if expired and youtube:
        if message is not None:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
        message = await channel.send(
            content=f"@everyone {youtube}",
            embed=embed, file=file,
            allowed_mentions=discord.AllowedMentions(everyone=True),
        )
        st.update(message_id=message.id, channel_id=channel_id, live_posted=True)
        save_state(state)
        log.info("Countdown %s LIVE (@everyone): %s", cid, message.id)
        return

    # ── Normaler Update ──
    if message is None:
        message = await channel.send(embed=embed, file=file)
        st.update(message_id=message.id, channel_id=channel_id, live_posted=False)
        save_state(state)
        log.info("Countdown %s gepostet: %s", cid, message.id)
    else:
        await message.edit(embed=embed, attachments=[file])
        st.update(message_id=message.id, channel_id=channel_id)
        log.info("Countdown %s aktualisiert: %s", cid, message.id)


async def cleanup_removed(active_ids: set) -> None:
    """Aus countdowns.json entfernte Countdowns: Discord-Nachricht loeschen."""
    changed = False
    for cid in list(state.keys()):
        if cid == "__legacy_mid__" or cid in active_ids:
            continue
        st = state.get(cid) or {}
        mid, ch_id = st.get("message_id"), st.get("channel_id")
        if mid and ch_id:
            ch = await _get_channel(int(ch_id))
            if ch is not None:
                try:
                    msg = await ch.fetch_message(int(mid))
                    await msg.delete()
                except discord.HTTPException:
                    pass
        del state[cid]
        changed = True
        log.info("Countdown %s entfernt, Nachricht geloescht", cid)
    if changed:
        save_state(state)


# ── Update-Loop ──────────────────────────────────────────
@tasks.loop(seconds=UPDATE_SECONDS)
async def update_loop():
    try:
        cfg = load_countdowns()
        all_cds = cfg.get("countdowns", [])
        active_ids = {c.get("id") for c in all_cds if c.get("id")}
        for cd in all_cds:
            if not cd.get("enabled", True):
                continue
            try:
                await process_countdown(cd)
            except Exception:
                log.exception("Fehler bei Countdown %s", cd.get("id"))
        await cleanup_removed(active_ids)
    except Exception:
        log.exception("Fehler im Update-Loop")


@update_loop.before_loop
async def before_loop():
    await client.wait_until_ready()


@client.event
async def on_ready():
    log.info("Eingeloggt als %s (id=%s)", client.user, client.user.id)
    if not update_loop.is_running():
        update_loop.start()


def main() -> None:
    load_dotenv(ROOT / ".env")
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN fehlt – siehe .env.example")
    client.run(token)


if __name__ == "__main__":
    main()
