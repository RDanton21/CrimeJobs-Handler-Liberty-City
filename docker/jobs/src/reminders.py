# -*- coding: utf-8 -*-
"""Discord-Erinnerungen: DM an Eingetragene vor dem Einsatzfenster.

Laeuft als Hintergrund-Task im Jobs-Dashboard und schickt jedem Spieler, der
in einem Slot eingetragen ist, REMINDER_LEAD_MINUTES vor window_start der
Mission eine DM — direkt ueber die Discord-REST-API mit dem Bot-Token von
"Il Padrino" (DMs brauchen kein Gateway, der Bot-Container bleibt unberuehrt).

Dedupe ueber die Tabelle sent_reminders (UNIQUE slot+player+kind), damit auch
nach einem Container-Neustart niemand doppelt erinnert wird. Spaete
Eintragungen (nach Beginn des Fensters) bekommen die DM ebenfalls, solange
das Fenster laeuft.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from . import config
from .db import SessionLocal
from .models import SentReminder, SlotAssignment

log = logging.getLogger("jobs.reminders")

DISCORD_API = "https://discord.com/api/v10"
CHECK_INTERVAL = 60  # Sekunden zwischen zwei Ticks

#: DM-Channel-Cache: user_id -> channel_id (aendert sich praktisch nie)
_dm_channels: dict[str, str] = {}


def _fmt_berlin(unix_ts: int) -> str:
    """Unix-Zeit als 'HH:MM' in Europe/Berlin."""
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc).astimezone(config.BERLIN_TZ)
    return dt.strftime("%H:%M")


def _detail_lines(mission: dict, slot: dict) -> list[str]:
    """Einsatz-Details fuer DMs; leere Felder werden weggelassen."""
    crew = mission.get("crew") or {}
    crew_name = crew.get("name") or "Unbekannte Crew"
    district = crew.get("district") or ""
    zeilen = [f"Crew: {crew_name}" + (f" ({district})" if district else "")]
    rolle = slot.get("name") or (
        f"NPC #{slot['npc_number']}" if slot.get("npc_number") else ""
    )
    if slot.get("function"):
        rolle = f"{rolle} — {slot['function']}" if rolle else slot["function"]
    if rolle:
        zeilen.append(f"Rolle: {rolle}")
    fenster = slot.get("slot_window") or mission.get("slot_window") or ""
    if fenster:
        zeilen.append(f"Zeit: {fenster}")
    if slot.get("location"):
        zeilen.append(f"Treffpunkt: {slot['location']}")
    if slot.get("costume"):
        zeilen.append(f"Kostüm: {slot['costume']}")
    if slot.get("notes"):
        zeilen.append(f"Hinweis: {slot['notes']}")
    return zeilen


def _build_message(mission: dict, slot: dict, now: float) -> str:
    """Deutsche Erinnerungs-DM."""
    start = mission.get("window_start")
    if start and now >= start:
        kopf = "🎬 Dein Einsatz läuft — jetzt zählt's!"
    elif start:
        minuten = max(1, round((start - now) / 60))
        kopf = (
            f"🎬 Erinnerung: Dein Einsatz startet um {_fmt_berlin(start)} Uhr "
            f"(in ca. {minuten} Min)."
        )
    else:
        kopf = "🎬 Erinnerung an deinen Einsatz."

    zeilen = [kopf, "", *_detail_lines(mission, slot), ""]
    zeilen.append(f"Alle Details: {config.PUBLIC_URL}")
    zeilen.append("Wenn du nicht kannst: bitte austragen, damit der Platz frei wird.")
    return "\n".join(zeilen)


def build_promotion_message(mission: dict, slot: dict) -> str:
    """DM fuer Nachruecker: von der Warteliste in den Slot uebernommen."""
    zeilen = [
        "🎬 Du bist nachgerückt! Ein Platz ist frei geworden — du bist jetzt fest eingetragen.",
        "",
        *_detail_lines(mission, slot),
        "",
        f"Alle Details: {config.PUBLIC_URL}",
        "Wenn du doch nicht kannst: bitte austragen, damit der Nächste nachrücken kann.",
    ]
    return "\n".join(zeilen)


async def send_single_dm(user_id: str, content: str) -> str:
    """Einzelne DM ausserhalb des Loops (z.B. Warteliste). Rueckgabe wie _send_dm."""
    if not config.DISCORD_BOT_TOKEN:
        return "closed"
    async with httpx.AsyncClient(timeout=15.0) as client:
        return await _send_dm(client, user_id, content)


async def send_single_dm_with_retry(user_id: str, content: str, attempts: int = 3) -> str:
    """DM mit Wiederholung bei temporaeren Fehlern (429/5xx/Netz/Token).

    Fuer Fire-and-forget-Aufrufer wie das Wartelisten-Nachruecken, bei denen
    es keinen naechsten Tick gibt, der es sonst erneut versuchen wuerde."""
    delays = (5.0, 30.0)
    for i in range(attempts):
        result = await send_single_dm(user_id, content)
        if result != "retry":
            return result
        if i < attempts - 1:
            await asyncio.sleep(delays[min(i, len(delays) - 1)])
    log.warning("DM an %s nach %d Versuchen aufgegeben", user_id, attempts)
    return "retry"


async def _send_dm(client: httpx.AsyncClient, user_id: str, content: str) -> str:
    """DM schicken. Rueckgabe:
    'ok'     -> zugestellt
    'closed' -> Nutzer nimmt keine DMs an (o.ae.) — nicht erneut versuchen
    'retry'  -> temporaerer Fehler — naechster Tick versucht es wieder
    """
    headers = {"Authorization": f"Bot {config.DISCORD_BOT_TOKEN}"}

    channel_id = _dm_channels.get(user_id)
    if channel_id is None:
        r = await client.post(
            f"{DISCORD_API}/users/@me/channels",
            headers=headers,
            json={"recipient_id": user_id},
        )
        if r.status_code == 429:
            await asyncio.sleep(float(r.headers.get("Retry-After", "2")))
            return "retry"
        if r.status_code >= 500:
            return "retry"
        if r.status_code == 401:
            # Unser Token ist kaputt (rotiert/entzogen) — das ist KEIN
            # Nutzer-Problem: retry statt closed, sonst wuerden Erinnerungen
            # als "verschickt" festgeschrieben und gingen dauerhaft verloren
            log.error("Bot-Token ungueltig (401) — DM-Versand pausiert bis zum Fix")
            return "retry"
        if r.status_code != 200:
            # 400/403: unbekannter Nutzer, Bot geblockt, ... -> aufgeben
            log.warning("DM-Channel fuer %s nicht erstellbar (HTTP %s)", user_id, r.status_code)
            return "closed"
        channel_id = r.json().get("id", "")
        if not channel_id:
            return "closed"
        _dm_channels[user_id] = channel_id

    r = await client.post(
        f"{DISCORD_API}/channels/{channel_id}/messages",
        headers=headers,
        json={"content": content},
    )
    if r.status_code == 429:
        await asyncio.sleep(float(r.headers.get("Retry-After", "2")))
        return "retry"
    if r.status_code >= 500:
        return "retry"
    if r.status_code in (200, 201):
        return "ok"
    if r.status_code == 401:
        log.error("Bot-Token ungueltig (401) — DM-Versand pausiert bis zum Fix")
        return "retry"
    # 403 code 50007 = "Cannot send messages to this user" (DMs deaktiviert)
    log.warning("DM an %s fehlgeschlagen (HTTP %s): %s", user_id, r.status_code, r.text[:200])
    return "closed"


async def _tick(fetch_crime_data) -> None:
    """Ein Durchlauf: faellige Erinnerungen ermitteln und verschicken."""
    missions, _crews = await fetch_crime_data()
    now = time.time()
    lead = config.REMINDER_LEAD_MINUTES * 60

    # Faellige Missions: Fenster bekannt, nicht archiviert, im Erinnerungs-
    # Zeitraum [start - lead, ende]
    slot_map: dict[int, tuple[dict, dict]] = {}
    for m in missions:
        if m.get("archived_at"):
            continue
        start = m.get("window_start")
        end = m.get("window_end") or start
        if not start or now < start - lead or now > end:
            continue
        for s in m.get("slots", []):
            if s.get("id") is not None:
                slot_map[s["id"]] = (m, s)
    if not slot_map:
        return

    async with SessionLocal() as session:
        res = await session.execute(
            select(SlotAssignment).where(SlotAssignment.slot_id.in_(slot_map.keys()))
        )
        assignments = res.scalars().all()
        res2 = await session.execute(
            select(SentReminder.slot_id, SentReminder.player_discord_id).where(
                SentReminder.slot_id.in_(slot_map.keys()),
                SentReminder.kind == "pre_start",
            )
        )
        schon = {(row[0], row[1]) for row in res2.all()}

    pending = [a for a in assignments if (a.slot_id, a.player_discord_id) not in schon]
    if not pending:
        return

    log.info("%d Erinnerung(en) faellig", len(pending))
    async with httpx.AsyncClient(timeout=15.0) as client:
        for a in pending:
            mission, slot = slot_map[a.slot_id]
            result = await _send_dm(
                client, a.player_discord_id, _build_message(mission, slot, now)
            )
            if result == "retry":
                continue  # naechster Tick probiert es erneut
            # 'ok' und 'closed' festschreiben — closed wuerde sonst jede
            # Minute erneut gegen die Wand laufen. Bewusst SENDEN vor
            # SCHREIBEN: stirbt der Container genau dazwischen, gibt es nach
            # dem Neustart schlimmstenfalls eine Doppel-DM — die umgekehrte
            # Reihenfolge wuerde die Erinnerung stattdessen still verlieren.
            async with SessionLocal() as session:
                try:
                    async with session.begin():
                        session.add(SentReminder(
                            slot_id=a.slot_id,
                            mission_id=a.mission_id,
                            player_discord_id=a.player_discord_id,
                            kind="pre_start",
                        ))
                except IntegrityError:
                    pass
            if result == "ok":
                log.info("Erinnerung an %s (Slot %d) verschickt", a.username, a.slot_id)


async def reminder_loop(fetch_crime_data) -> None:
    """Endlos-Loop; wird in der Lifespan der App gestartet.

    fetch_crime_data wird uebergeben (statt importiert), um einen
    Zirkel-Import mit main.py zu vermeiden.
    """
    if not config.DISCORD_BOT_TOKEN:
        log.info("Erinnerungen deaktiviert — kein DISCORD_BOT_TOKEN gesetzt")
        return
    log.info(
        "Erinnerungs-Loop aktiv (Vorlauf %d Min, Intervall %ds)",
        config.REMINDER_LEAD_MINUTES, CHECK_INTERVAL,
    )
    while True:
        try:
            await _tick(fetch_crime_data)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Auch HTTPException aus fetch_crime_data (Backend kurz weg) landet
            # hier — loggen und weiterlaufen, der naechste Tick kommt bestimmt
            log.exception("Erinnerungs-Tick fehlgeschlagen")
        await asyncio.sleep(CHECK_INTERVAL)
