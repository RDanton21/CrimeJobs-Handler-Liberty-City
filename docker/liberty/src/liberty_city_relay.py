import os
import time
import json
import hashlib
import hmac
import logging
import logging.handlers
import random
import threading
import asyncio
import queue
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional, Tuple

import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify, redirect

# Twitch (optional; enabled only if TWITCH_* env vars exist and twitchAPI is installed)
try:
    from twitchAPI.twitch import Twitch
    from twitchAPI.helper import first
    from twitchAPI.oauth import UserAuthenticationStorageHelper
    from twitchAPI.eventsub.websocket import EventSubWebsocket
    from twitchAPI.type import AuthScope
    from twitchAPI.object.eventsub import (
        ChannelSubscribeEvent,
        ChannelSubscriptionGiftEvent,
        ChannelCheerEvent,
        ChannelSubscriptionMessageEvent,
    )
    TWITCH_AVAILABLE = True
except Exception:
    TWITCH_AVAILABLE = False

# =====================================================
# INIT
# =====================================================
load_dotenv()

_log_file = os.getenv("LOG_FILE", "service.log").strip()
_log_max_bytes = int(os.getenv("LOG_MAX_BYTES", "10000000"))
_log_backup_count = int(os.getenv("LOG_BACKUP_COUNT", "5"))
_log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
_root_logger = logging.getLogger()
_root_logger.setLevel(logging.INFO)
if not _root_logger.handlers:
    _stream_handler = logging.StreamHandler()
    _stream_handler.setFormatter(_log_formatter)
    _root_logger.addHandler(_stream_handler)
    try:
        _file_handler = logging.handlers.RotatingFileHandler(
            _log_file, maxBytes=_log_max_bytes, backupCount=_log_backup_count, encoding="utf-8"
        )
        _file_handler.setFormatter(_log_formatter)
        _root_logger.addHandler(_file_handler)
    except Exception as _e:
        logging.warning("RotatingFileHandler init failed: %s", _e)

FILE_LOCK = threading.Lock()
STATUS_LOCK = threading.Lock()
GOAL_LOCK = threading.Lock()
DEDUPE_LOCK = threading.Lock()
CASE_LOG_LOCK = threading.Lock()

# =====================================================
# CONFIG
# =====================================================
# Discord
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
DISCORD_USERNAME = os.getenv("DISCORD_USERNAME", "The Accountant").strip()
DISCORD_AVATAR_URL = os.getenv("DISCORD_AVATAR_URL", "").strip()

# Goal + progress
GOAL_NETTO_EUR = float(os.getenv("GOAL_NETTO_EUR", "3000"))
PROGRESS_BAR_LENGTH = int(os.getenv("PROGRESS_BAR_LENGTH", "20"))
PROGRESS_TEXT = os.getenv(
    "PROGRESS_TEXT",
    "5EKTOR wird live gehen, wenn das Goal erreicht wurde.\n"
    "**Eventzeitraum: 07.08.2026 18:00 – 23.08.2026 23:59**"
).strip()

# Files
STATS_FILE = os.getenv("STATS_FILE", "stats.json").strip()
STATUS_MSG_FILE = os.getenv("STATUS_MSG_FILE", "status_message.json").strip()
GOAL_MSG_FILE = os.getenv("GOAL_MSG_FILE", "goal_message.json").strip()  # NEW: keep goal embed always last
DEDUPE_FILE = os.getenv("DEDUPE_FILE", "dedupe.json").strip()
DEDUPE_WINDOW_SEC = int(os.getenv("DEDUPE_WINDOW_SEC", "900"))
GOAL_STATE_FILE = os.getenv("GOAL_STATE_FILE", "goal_reached_state.json").strip()
CASE_FILE = os.getenv("CASE_FILE", "case_files.jsonl").strip()
STREAM_START_FILE = os.getenv("STREAM_START_FILE", "current_stream_start.json").strip()
ADMIN_CONFIG_FILE = os.getenv("ADMIN_CONFIG_FILE", "admin_config.json").strip()
SPRUECHE_FILE = os.getenv("SPRUECHE_FILE", "Liberty_City_Sprueche.txt").strip()

# Ko-fi webhook listener
KOFI_LISTEN_HOST = os.getenv("KOFI_LISTEN_HOST", "127.0.0.1").strip()
KOFI_LISTEN_PORT = int(os.getenv("KOFI_LISTEN_PORT", "8080"))
OBS_OVERLAY_ORIGIN = os.getenv("OBS_OVERLAY_ORIGIN", f"http://127.0.0.1:{KOFI_LISTEN_PORT}").strip()

# Ko-fi fees (optional; if not set in .env, they default to 0.0 => no behaviour change)
_raw_kofi_fee = os.getenv("KOFI_FEE_PERCENT")
KOFI_FEE_PERCENT = float(_raw_kofi_fee) if _raw_kofi_fee not in (None, "") else 0.0

_raw_paypal_percent = os.getenv("PAYPAL_FEE_PERCENT")
PAYPAL_FEE_PERCENT = float(_raw_paypal_percent) if _raw_paypal_percent not in (None, "") else 0.0

_raw_paypal_fixed = os.getenv("PAYPAL_FEE_FIXED")
PAYPAL_FEE_FIXED = float(_raw_paypal_fixed) if _raw_paypal_fixed not in (None, "") else 0.0

# Twitch auth
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "").strip()
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "").strip()
TWITCH_BROADCASTER_ID = os.getenv("TWITCH_BROADCASTER_ID", "").strip()

# Twitch € values (override via .env if needed)
SUB_T1_BRUTTO_EUR = float(os.getenv("SUB_T1_BRUTTO_EUR", "4.99"))
SUB_T1_NETTO_EUR = float(os.getenv("SUB_T1_NETTO_EUR", "2.50"))
SUB_T2_BRUTTO_EUR = float(os.getenv("SUB_T2_BRUTTO_EUR", "9.99"))
SUB_T2_NETTO_EUR = float(os.getenv("SUB_T2_NETTO_EUR", "5.00"))
SUB_T3_BRUTTO_EUR = float(os.getenv("SUB_T3_BRUTTO_EUR", "24.99"))
SUB_T3_NETTO_EUR = float(os.getenv("SUB_T3_NETTO_EUR", "12.50"))
SUB_PRIME_BRUTTO_EUR = float(os.getenv("SUB_PRIME_BRUTTO_EUR", "4.99"))
SUB_PRIME_NETTO_EUR = float(os.getenv("SUB_PRIME_NETTO_EUR", "2.50"))
BITS_EUR_PER_BIT = float(os.getenv("BITS_EUR_PER_BIT", "0.01"))

FOOTER_QUOTES = [
    "Was vergangen ist, beginnt in Liberty City.",
    "Alles hat seinen Preis – besonders Loyalität.",
    "Niemand behält lange die Krone in Liberty City.",
    "Geld redet, aber in Liberty City schreit es.",
    "Vertraue niemandem, der zu schnell zustimmt.",
    "In Liberty City gibt es keine Zufälle – nur schlechte Planung.",
    "Wer hier Freunde hat, hat sie noch nicht lange.",
    "Die Wahrheit kostet in Liberty City mehr als die Lüge.",
    "Jeder hat einen Plan, bis die erste Kugel fliegt.",
    "Macht korrumpiert – in Liberty City beschleunigt sie es nur.",
    "Wer nicht fragt, bekommt keine unbequemen Antworten.",
    "In Liberty City überleben die Klugen – die Ehrlichen selten.",
    "Träume sind billig. Schutzgeld nicht.",
    "Der beste Deal ist der, von dem die andere Seite nichts weiß.",
    "In Liberty City ist jeder Zeuge ein Risiko.",
    "Wer keine Feinde hat, hat noch nicht genug erreicht.",
    "Respekt kauft man nicht – man leiht ihn sich, bis man ihn erzwingt.",
    "Die Reichen schlafen gut. Die Klugen schlafen mit einem Auge offen.",
    "In Liberty City endet jede Geschichte dort, wo das Geld aufhört.",
    "Wer zu laut redet, hört bald gar nichts mehr.",
    "Jede Straße hier hat einen Namen – und jeder Name eine Schuld.",
    "Loyalität ist das teuerste Gut, das man nicht kaufen kann.",
    "In Liberty City ist Schweigen kein Zeichen von Schwäche – sondern von Erfahrung.",
    "Niemand verlässt Liberty City ohne Narben.",
    "Wer heute dein Verbündeter ist, kennt morgen deine Schwächen.",
    "Die Polizei schützt die Ordnung. Wer die Ordnung macht, schützt sich selbst.",
    "In Liberty City ist jeder Aufstieg mit dem Fall eines anderen gepflastert.",
    "Ein Handschlag bedeutet hier nichts. Ein Vertrag noch weniger.",
    "Wer Schulden hat, hat einen Chef, den er nicht gewählt hat.",
    "Das Gesetz gilt für alle – manche zahlen nur dafür, dass es für sie nicht gilt.",
    "In Liberty City stirbt man nicht an Alter.",
    "Hinter jedem Lächeln steckt eine Rechnung.",
    "Die gefährlichsten Männer hier sprechen am leisesten.",
    "Wer die Vergangenheit kennt, hat Macht. Wer sie vergisst, ist Opfer.",
    "In Liberty City wird aus Gier Strategie und aus Strategie Überleben.",
    "Niemand hier ist unersetzlich – nur schwer zu ersetzen.",
    "Eine zweite Chance ist in Liberty City ein Luxus, den sich wenige leisten.",
    "Jeder Verrat beginnt mit einer Gefälligkeit.",
    "Die Straße nimmt alles – und gibt nichts zurück.",
    "Wer anderen eine Grube gräbt, wohnt in Liberty City.",
    "In Liberty City sind Prinzipien das erste Opfer des Erfolgs.",
    "Wer hier anklopft, sollte wissen, wer aufmacht.",
    "Armut ist kein Unglück in Liberty City – Naivität schon.",
    "Die Stadt schläft nie. Aber sie vergisst auch nie.",
    "Wer in Liberty City nach Gerechtigkeit sucht, sucht lange.",
    "In Liberty City ist Vertrauen keine Tugend – es ist eine Schwäche.",
    "Wer hier lächelt, hat einen Grund dafür. Keinen guten.",
    "Die Waffe macht keinen Mann – die Adressliste schon.",
    "In Liberty City gibt es keine Opfer. Nur schlechte Verhandler.",
    "Wer schweigt, stimmt nicht zu – er plant.",
    "Jede Freundschaft hier hat einen Ablauftermin.",
    "Die Stadt gehört dem, der am längsten wach bleibt.",
    "In Liberty City ist Hunger der beste Motivator.",
    "Wer hier ankommt mit Träumen, geht mit Schulden.",
    "Ein Mann ohne Feinde ist ein Mann ohne Ambitionen.",
    "In Liberty City ist die Wahrheit das, was du beweisen kannst.",
    "Vergebung gibt es – aber erst nach der Quittung.",
    "Wer das Spiel nicht kennt, zahlt den vollen Preis.",
    "In Liberty City lebt man schnell und plant langsam.",
    "Niemand fragt woher das Geld kommt – nur wann es kommt.",
    "Der klügste Mann im Raum redet am wenigsten.",
    "In Liberty City sind Versprechen Währung – mit schlechtem Kurs.",
    "Wer hier aufsteigt, hat jemanden nach unten getreten.",
    "Jede Straße endet irgendwo – meistens schlecht.",
    "Wer die Regeln kennt, weiß auch wie man sie bricht.",
    "In Liberty City ist Mitgefühl teuer. Gleichgültigkeit umsonst.",
    "Wer zu viel weiß, schläft unruhig.",
    "Die größten Geschäfte werden ohne Zeugen gemacht.",
    "In Liberty City ist jeder auf der Durchreise – manche kommen nie an.",
    "Wer nichts zu verlieren hat, ist der gefährlichste Mann im Raum.",
    "Geduld ist in Liberty City keine Tugend – es ist Strategie.",
    "Jeder Aufstieg hinterlässt Feinde. Jeder Sturz hinterlässt Narben.",
    "In Liberty City ist Moral verhandelbar – der Preis nicht.",
    "Wer fragt, wer der Chef ist, ist es nicht.",
    "Die Stadt verzeiht nichts. Sie wartet nur.",
    "In Liberty City sind alle gleich – bis das Geld spricht.",
    "Wer hier ankert, geht früher oder später unter.",
    "Hinter jedem Erfolg steckt ein Geheimnis, das besser bleibt.",
    "In Liberty City ist Ehrlichkeit ein Luxus für Reiche.",
    "Wer rennt, gibt zu, dass er Schulden hat.",
    "Jeder kennt jeden – und jeder hat etwas auf jeden.",
    "In Liberty City ist Vergessen eine Kunst. Erinnern eine Waffe.",
    "Wer einen Deal macht, macht auch einen Feind.",
    "Die Nacht gehört denen, die tagsüber unsichtbar sind.",
    "In Liberty City ist jede Gunst ein Kredit mit Zinsen.",
    "Wer hier bleibt, hat sich entschieden. Oder keine Wahl mehr.",
    "Blut wäscht sich ab. Schulden nicht.",
    "In Liberty City ist der kürzeste Weg selten der sicherste.",
    "Wer lügt, muss sich erinnern. Wer schweigt, nicht.",
    "Die besten Geschäfte beginnen mit einer Lüge und enden mit einer Drohung.",
    "In Liberty City isst du, was du dir nimmst.",
    "Wer hier stirbt, hat irgendwo falsch abgebogen.",
    "Niemand gibt hier etwas ohne Gegenleistung – nicht mal Ratschläge.",
    "In Liberty City ist die Vergangenheit Munition.",
    "Wer Angst zeigt, lädt andere ein sie zu benutzen.",
    "Die Straße erkennt den Schwachen bevor er es selbst tut.",
    "In Liberty City ist Loyalität nicht gratis – sie wird abbezahlt.",
    "Wer heute gewinnt, hat morgen mehr zu verlieren.",
    "Hinter jedem ruhigen Gesicht steckt ein laufender Countdown.",
    "In Liberty City wird aus Zufällen keine Geschichte – aus Entscheidungen schon.",
    "Wer keine Schulden hat, hat noch keine echten Geschäfte gemacht.",
    "Die Stadt nimmt von allen – manche nennen es Steuern.",
    "In Liberty City ist Stärke nicht was du hast – sondern was andere glauben.",
    "Wer zu lange wartet, findet seinen Platz besetzt.",
    "Jeder hat hier eine Maske. Die Frage ist wann sie fällt.",
    "In Liberty City bedeutet Frieden nur, dass sich alle neu positionieren.",
    "Wer hier alles verloren hat, ist endlich frei – oder tot.",
    "Der gefährlichste Ort ist direkt hinter dem, dem du vertraust.",
    "In Liberty City ist jeder Deal ein Waffenstillstand.",
    "Wer zu viel erklärt, hat zu viel zu erklären.",
    "Die besten Informationen kommen von denen, die nichts ahnen.",
    "In Liberty City ist Naivität keine Entschuldigung – nur ein Einstiegspreis.",
    "Wer hier überlebt, hat gelernt wann er die Klappe hält.",
    "Jede Nacht in Liberty City beginnt mit einem Plan und endet mit einem anderen.",
    "Wer Macht will, muss erst lernen wie man Schulden macht.",
    "In Liberty City ist die gefährlichste Person die, die nichts zu beweisen hat.",
    "Wer das Falsche sieht, sieht meistens das Richtige.",
    "Die Klügsten in Liberty City haben keine Geschichte – nur eine Gegenwart.",
    "In Liberty City stirbt Vertrauen immer vor seinem Besitzer.",
    "Wer zu viele Fragen stellt, bekommt die falsche Antwort.",
    "Niemand hier hat den ersten Schuss gemacht – und trotzdem läuft jeder.",
    "In Liberty City ist Gier der Motor und Angst die Bremse.",
    "Wer hier schläft, träumt von dem was er verloren hat.",
    "Jede Allianz in Liberty City hat ein Verfallsdatum.",
    "In Liberty City ist Selbsterhaltung keine Schwäche – sie ist Kunst.",
    "Wer die Waffe zeigt, muss sie auch benutzen wollen.",
    "Die Stadt belohnt keine Träumer – nur Macher. Und auch die nur kurz.",
    "In Liberty City ist jede Stille vor einem Sturm nur kurze Pause.",
    "Wer Vertrauen schenkt, gibt dem anderen die Waffe.",
    "Hinter jedem Versprechen steckt ein Preis, der noch nicht genannt wurde.",
    "In Liberty City kennt man den Wert von allem – den Preis von nichts.",
    "Wer hier anfängt zu glauben, hört auf zu denken.",
    "Die Straße erinnert sich an alles – auch wenn du es vergisst.",
    "In Liberty City ist jeder Fall eine Lektion für die anderen.",
    "Wer seinen Feind kennt, schläft besser als wer seine Freunde kennt.",
    "Jede Stadt hat ihre Regeln. Liberty City hat nur Ausnahmen.",
    "In Liberty City ist der einzige Unterschied zwischen Freund und Feind der Zeitpunkt.",
    "Wer hier Wurzeln schlägt, gräbt sein eigenes Grab.",
    "Die mächtigsten Männer in Liberty City haben keine Titel – nur Nummern.",
    "In Liberty City läuft die Uhr immer – auch wenn man schläft.",
    "Wer glaubt er hat gewonnen, hat nur aufgehört zu zählen.",
    "Niemand verlässt Liberty City als derselbe Mensch, der ankam.",
    "In Liberty City ist die teuerste Lektion immer die erste.",
]

# =====================================================
# JSON HELPERS
# =====================================================
def _load_json(path: str, default: Any) -> Any:
    with FILE_LOCK:
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default


def _save_json(path: str, data: Any) -> None:
    # Atomic write: tmp file + rename. Prevents corruption on mid-write crash
    # and on concurrent writers (rename is atomic on POSIX/NTFS).
    with FILE_LOCK:
        tmp = f"{path}.tmp.{os.getpid()}"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            os.replace(tmp, path)
        except Exception as e:
            logging.warning("atomic save %s failed: %s", path, e)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass


# =====================================================
# STATS
# =====================================================
def _defaults_stats() -> Dict[str, Any]:
    return {
        "kofi_brutto_eur": 0.0,
        "kofi_netto_eur": 0.0,
        "tebex_brutto_eur": 0.0,
        "tebex_netto_eur": 0.0,
        "subs_brutto_eur": 0.0,
        "subs_netto_eur": 0.0,
        "gifted_subs_total": 0,
        "bits_total": 0,
        "bits_value_eur": 0.0,
    }


def load_stats() -> Dict[str, Any]:
    data = _load_json(STATS_FILE, {})
    stats = _defaults_stats()
    if isinstance(data, dict):
        for k in stats.keys():
            stats[k] = data.get(k, stats[k])
    return stats


def save_stats(stats: Dict[str, Any]) -> None:
    base = _defaults_stats()
    for k, v in base.items():
        stats.setdefault(k, v)
    _save_json(STATS_FILE, stats)


_MONEY_QUANT = Decimal("0.01")


def _to_dec(v: Any) -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


def money_add(*values: Any) -> float:
    """Add monetary values without float compounding errors.
    Uses Decimal internally, returns float rounded to cents."""
    total = Decimal("0")
    for v in values:
        total += _to_dec(v)
    return float(total.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP))


def money_mul(value: Any, factor: Any) -> float:
    """Multiply money * factor (factor can be int count or Decimal). Returns float."""
    result = _to_dec(value) * _to_dec(factor)
    return float(result.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP))


def total_netto(stats: Dict[str, Any]) -> float:
    return money_add(
        stats.get("kofi_netto_eur", 0.0),
        stats.get("tebex_netto_eur", 0.0),
        stats.get("subs_netto_eur", 0.0),
        stats.get("bits_value_eur", 0.0),
    )


# =====================================================
# DEDUPE
# =====================================================
def _dedupe_load() -> Dict[str, Any]:
    d = _load_json(DEDUPE_FILE, {"seen": {}})
    if not isinstance(d, dict):
        d = {"seen": {}}
    if "seen" not in d or not isinstance(d["seen"], dict):
        d["seen"] = {}
    return d


def _dedupe_save(d: Dict[str, Any]) -> None:
    _save_json(DEDUPE_FILE, d)


def is_duplicate(event_key: str) -> bool:
    if not event_key:
        return False
    # Single lock around read+check+write closes the race window where two
    # concurrent requests both observe a key as unseen and both fall through.
    with DEDUPE_LOCK:
        now = time.time()
        d = _dedupe_load()
        seen: Dict[str, Any] = d.get("seen", {})

        for k, ts in list(seen.items()):
            try:
                if not isinstance(ts, (int, float)) or (now - float(ts)) > DEDUPE_WINDOW_SEC:
                    seen.pop(k, None)
            except Exception:
                seen.pop(k, None)

        if event_key in seen:
            return True

        seen[event_key] = now
        d["seen"] = seen
        _dedupe_save(d)
        return False


# =====================================================
# DISCORD (basic 429 handling)
# =====================================================
def _discord_handle_response(r, label, on_message_id):
    logging.info("%s POST %s", label, r.status_code)
    if r.status_code >= 400 and r.status_code != 429:
        try:
            logging.warning("%s Discord error body: %s", label, r.text[:500])
        except Exception:
            pass
    if on_message_id and r.status_code == 200:
        try:
            mid = (r.json() or {}).get("id")
            if mid:
                on_message_id(mid)
        except Exception:
            logging.exception("%s on_message_id callback failed", label)


def _discord_background_retry(url, payload, retry_after, label, on_message_id):
    delay = min(max(retry_after, 0.5), 10.0)
    def _do_retry():
        try:
            r = requests.post(url, json=payload, timeout=10)
            _discord_handle_response(r, label + "(retry)", on_message_id)
        except Exception as e:
            logging.exception("%s retry failed: %s", label, e)
    threading.Timer(delay, _do_retry).start()


def discord_post(payload: Dict[str, Any], *, wait: bool = False, label: str = "DISCORD",
                  on_message_id=None):
    """Synchronous first attempt; on HTTP 429 the retry is scheduled on a
    background thread so the calling Flask request returns immediately.

    on_message_id: optional callback(message_id_str). Called when Discord
    accepts the post (status 200). Required when caller needs to persist
    the message id for later edit/delete, because the retry path runs
    after this function has already returned."""
    if not DISCORD_WEBHOOK_URL:
        logging.error("%s: DISCORD_WEBHOOK_URL fehlt.", label)
        return None

    url = DISCORD_WEBHOOK_URL + ("?wait=true" if wait else "")
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 429:
            try:
                retry_after = float((r.json() or {}).get("retry_after", 1.0))
            except Exception:
                retry_after = 1.0
            logging.warning(
                "%s rate-limited (429). Scheduling background retry in %.2fs.",
                label, retry_after,
            )
            _discord_background_retry(url, payload, retry_after, label, on_message_id)
            return None
        _discord_handle_response(r, label, on_message_id)
        return r
    except Exception as e:
        logging.exception("%s POST failed: %s", label, e)
        return None


def discord_delete(message_id: str, *, label: str = "DISCORD") -> None:
    if not message_id:
        return
    try:
        url = f"{DISCORD_WEBHOOK_URL}/messages/{message_id}"
        r = requests.delete(url, timeout=10)
        logging.info("%s DELETE %s", label, r.status_code)
    except Exception as e:
        logging.warning("%s DELETE failed: %s", label, e)


def _load_msg_id(path: str) -> Optional[str]:
    d = _load_json(path, {})
    if isinstance(d, dict):
        return d.get("id")
    return None


def _save_msg_id(path: str, message_id: str) -> None:
    _save_json(path, {"id": message_id})


# =====================================================
# EMBED DESIGN HELPERS (Icons Option 1)
# =====================================================
def platform_badge(platform: str) -> str:
    p = (platform or "").strip().upper()
    if p == "KOFI":
        return "💗 Ko-fi"
    if p == "TWITCH":
        return "🟪 Twitch"
    if p == "TEBEX":
        return "🛒 Tebex"
    return platform or "Unbekannt"


def category_badge(category: str) -> str:
    c = (category or "").strip().upper()
    return {
        "DONATION": "💸 Donation",
        "SUB": "⭐ Sub",
        "RESUB": "🔁 Resub",
        "GIFT": "🎁 Gift",
        "BITS": "💎 Bits",
    }.get(c, category or "Event")


def _make_case_id(prefix: str, raw_id: str = "") -> str:
    raw_id = (raw_id or "").strip()
    if raw_id and len(raw_id) >= 6:
        return f"{prefix}-{raw_id[:8]}"
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def _append_case_log(
    *,
    case_id: str,
    platform: str,
    category: str,
    donator: str,
    amount_eur: float,
) -> None:
    """Append one event to case_files.jsonl for the dashboard + leaderboard."""
    classification = "RESTRICTED" if (platform or "").upper() == "TWITCH" else "CONFIDENTIAL"
    record = {
        "case_id": case_id,
        "source": (platform or "").upper(),
        "category": (category or "").upper(),
        "classification": classification,
        "username": donator,
        "amount": float(amount_eur),
        "currency": "EUR",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    line = json.dumps(record, ensure_ascii=False)
    with CASE_LOG_LOCK:
        try:
            with open(CASE_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            logging.warning("case log append failed: %s", e)


def send_case_embed(
    *,
    platform: str,
    category: str,
    donator: str,
    amount_eur: float,
    oval_office: str,
    case_id: str,
) -> None:
    _append_case_log(
        case_id=case_id, platform=platform, category=category,
        donator=donator, amount_eur=amount_eur,
    )
    embed = {
        "author": {"name": "Liberty City White House • Level 5 Clearance"},
        "title": "WELCOME TO LIBERTY CITY",
        "description": "\n".join([
            f"👤 Donator: ✨ {donator} ✨",
            f"💰 Betrag: 💸 {amount_eur:.2f} EUR 💸",
            f"📄 Case ID: {case_id}",
            f"📄 Oval Office: {oval_office}",
            "",
        ]),
        "color": 0xE94560,
        "fields": [
            {"name": "Plattform", "value": platform_badge(platform), "inline": True},
            {"name": "Kategorie", "value": category_badge(category), "inline": True},
        ],
        "footer": {
            "text": "Liberty City White House • Level 5 Clearance\n"
                    "Classification: RESTRICTED\n"
                    + random.choice(current_sprueche())
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    payload = {
        "username": DISCORD_USERNAME,
        "avatar_url": DISCORD_AVATAR_URL or None,
        "embeds": [embed],
    }

    discord_post(payload, wait=False, label=f"FIRST({platform.upper()}/{category.upper()})")


# =====================================================
# PROGRESS EMBED (Legacy)
# =====================================================
def make_progress_bar(current_netto: float) -> str:
    goal = current_goal_eur()
    if goal <= 0:
        return "—  **0%**"

    ratio_unclamped = current_netto / goal
    percent = int(ratio_unclamped * 100)

    ratio_capped = max(0.0, min(ratio_unclamped, 1.0))
    filled = int(ratio_capped * PROGRESS_BAR_LENGTH)
    capped_percent = int(ratio_capped * 100)

    if capped_percent < 25:
        c = "🟪"
    elif capped_percent < 50:
        c = "🟥"
    elif capped_percent < 95:
        c = "🟨"
    else:
        c = "🟩"

    return f"{c * filled}{'⬛' * (PROGRESS_BAR_LENGTH - filled)}  **{percent}%**"


def upsert_status_embed() -> None:
    with STATUS_LOCK:
        stats = load_stats()
        netto_sum = total_netto(stats)

        old_id = _load_msg_id(STATUS_MSG_FILE)
        if old_id:
            discord_delete(old_id, label="STATUS")

        embed = {
            "author": {"name": current_embed_author()},
            "title": current_embed_title(),
            "description": "\n".join([
                current_progress_text(),
                "",
                make_progress_bar(netto_sum),
            ]),
            "color": 0xE94560,
            "footer": {"text": random.choice(current_sprueche())},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        payload = {
            "username": DISCORD_USERNAME,
            "avatar_url": DISCORD_AVATAR_URL or None,
            "embeds": [embed],
        }

        discord_post(
            payload, wait=True, label="STATUS",
            on_message_id=lambda mid: _save_msg_id(STATUS_MSG_FILE, mid),
        )


# =====================================================
# GOAL REACHED — ALWAYS LAST AFTER 100%
# =====================================================
def _goal_state() -> Dict[str, Any]:
    d = _load_json(GOAL_STATE_FILE, {})
    if not isinstance(d, dict):
        d = {}
    d.setdefault("posted", False)
    d.setdefault("posted_at", "")
    return d


def _save_goal_state(posted: bool) -> None:
    d = _goal_state()
    d["posted"] = bool(posted)
    if posted and not d.get("posted_at"):
        d["posted_at"] = datetime.now(timezone.utc).isoformat()
    _save_json(GOAL_STATE_FILE, d)


def _build_goal_embed() -> Dict[str, Any]:
    return {
        "author": {"name": "Liberty City White House • Level 5 Clearance"},
        "title": current_goal_title(),
        "description": "\n".join([
            "🇺🇸 **Dank euch erwacht Liberty City!** 🇺🇸",
            "",
            "Wir danken euch für die Unterstützung!",
            "",
            "Ich habe soeben das Präsidialdekret für den Start unterschrieben und an die Projektleitung weitergeleitet.",
            "",
            "🇺🇸 **Ihr Frank Underwood**",
        ]),
        "color": 0x1E3A8A,
        "footer": {"text": "🇺🇸 Liberty City White House • Final Order 🇺🇸"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def upsert_goal_embed_always_last() -> None:
    """Delete + repost goal embed (to keep it always the last message)."""
    with GOAL_LOCK:
        old_id = _load_msg_id(GOAL_MSG_FILE)
        if old_id:
            discord_delete(old_id, label="GOAL")

        payload = {
            "username": DISCORD_USERNAME,
            "avatar_url": DISCORD_AVATAR_URL or None,
            "embeds": [_build_goal_embed()],
        }

        discord_post(
            payload, wait=True, label="GOAL",
            on_message_id=lambda mid: _save_msg_id(GOAL_MSG_FILE, mid),
        )


def ensure_goal_embed_if_needed() -> None:
    """If goal is reached, make sure goal embed exists AND is always last."""
    stats = load_stats()
    netto_sum = total_netto(stats)

    goal = current_goal_eur()
    if goal <= 0:
        return

    if netto_sum < goal:
        return

    # Mark as reached once
    state = _goal_state()
    if not bool(state.get("posted", False)):
        _save_goal_state(True)

    # Always re-upsert goal embed so it stays last
    upsert_goal_embed_always_last()


def ensure_goal_embed_on_startup() -> None:
    """Like ensure_goal_embed_if_needed but suppresses a fresh post if the
    goal embed was already posted within the last hour. Prevents a duplicate
    GOAL ERREICHT message after a service restart."""
    state = _goal_state()
    if bool(state.get("posted", False)):
        posted_at = str(state.get("posted_at", "") or "").strip()
        if posted_at:
            try:
                ts = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
                age_sec = (datetime.now(timezone.utc) - ts).total_seconds()
                if 0 <= age_sec < 3600:
                    logging.info(
                        "Goal embed posted %.0fs ago; skipping startup re-post.",
                        age_sec,
                    )
                    return
            except Exception:
                pass
    ensure_goal_embed_if_needed()


# =====================================================
# KO-FI (Flask) — /kofi
# =====================================================
app = Flask(__name__)

# --------------------------
# CORS (für OBS/Web-Overlay)
# --------------------------
@app.after_request
def _add_cors_headers(resp):
    # Restricted to configured OBS overlay origin (default loopback).
    # Override via OBS_OVERLAY_ORIGIN env if overlay is served from another host.
    origin = request.headers.get("Origin", "")
    if origin and origin == OBS_OVERLAY_ORIGIN:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET,OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp



def _parse_kofi_payload() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    if (not payload) and request.form and "data" in request.form:
        try:
            payload = json.loads(request.form.get("data") or "{}")
        except Exception:
            payload = {}
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        data = {}
    return payload, data


import leaderboard
import admin_routes


def _load_sprueche() -> Tuple[float, list]:
    """Return (mtime, lines). Defaults to FOOTER_QUOTES if file missing."""
    path = SPRUECHE_FILE
    if os.path.exists(path):
        try:
            mtime = os.path.getmtime(path)
            with open(path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
            if lines:
                return mtime, lines
        except Exception:
            pass
    return 0.0, FOOTER_QUOTES


_sprueche_mtime, _sprueche_cache = _load_sprueche()


def current_sprueche() -> list:
    global _sprueche_mtime, _sprueche_cache
    try:
        if os.path.exists(SPRUECHE_FILE):
            m = os.path.getmtime(SPRUECHE_FILE)
            if m != _sprueche_mtime:
                _sprueche_mtime, _sprueche_cache = _load_sprueche()
    except Exception:
        pass
    return _sprueche_cache or FOOTER_QUOTES


def current_goal_eur() -> float:
    return admin_routes.goal_eur(default=float(GOAL_NETTO_EUR))


def current_goal_title() -> str:
    return admin_routes.goal_title(default="🇺🇸 GOAL ERREICHT!!! 🇺🇸")


def current_embed_title() -> str:
    return admin_routes.embed_title(default="🗽 WELCOME TO LIBERTY CITY 🗽")


def current_embed_author() -> str:
    return admin_routes.embed_author(default="Liberty City White House • Level 5 Clearance")


def current_progress_text() -> str:
    return admin_routes.embed_progress_text(default=PROGRESS_TEXT)


def _kofi_netto_from_amount(amount: float) -> float:
    a = _to_dec(amount)
    kofi_fee = a * _to_dec(max(KOFI_FEE_PERCENT, 0.0))
    paypal_pct_fee = a * _to_dec(max(PAYPAL_FEE_PERCENT, 0.0))
    paypal_fixed_fee = _to_dec(max(PAYPAL_FEE_FIXED, 0.0))
    net = a - kofi_fee - paypal_pct_fee - paypal_fixed_fee
    if net < 0:
        net = Decimal("0")
    return float(net.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP))


@app.route("/kofi", methods=["POST"])
def handle_kofi():
    payload, data = _parse_kofi_payload()

    expected_token = os.getenv("KOFI_VERIFICATION_TOKEN", "").strip().strip('"').strip("'")
    if expected_token:
        received_token = (data.get("verification_token") or payload.get("verification_token") or "")
        received_token = str(received_token).strip().strip('"').strip("'")
        if not hmac.compare_digest(received_token, expected_token):
            logging.warning("Ko-fi Webhook abgelehnt: verification_token passt nicht.")
            return jsonify({"status": "forbidden"}), 403

    kofi_id = (
        data.get("kofi_transaction_id")
        or data.get("transaction_id")
        or data.get("message_id")
        or data.get("id")
        or ""
    )
    kofi_id = str(kofi_id).strip()
    is_placeholder = kofi_id.startswith("00000000-") or kofi_id.lower() in {"test", "dummy", "none", "null", ""}

    if kofi_id and not is_placeholder:
        event_key = f"kofi:{kofi_id}"
    else:
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
        h = hashlib.sha1(raw.encode("utf-8")).hexdigest()
        bucket = int(time.time() // 2)
        event_key = f"kofi_hash:{h}:{bucket}"

    if is_duplicate(event_key):
        logging.info("Ko-fi duplicate ignored: %s", event_key)
        # keep order: status then goal (if reached)
        upsert_status_embed()
        ensure_goal_embed_if_needed()
        return jsonify({"status": "duplicate"}), 200

    donator = (data.get("from_name") or data.get("username") or "Unbekannt")
    raw_amount = data.get("amount") or data.get("amount_eur") or data.get("total") or "0"
    try:
        amount = float(str(raw_amount).replace(",", "."))
    except Exception:
        amount = 0.0

    netto = _kofi_netto_from_amount(amount)

    stats = load_stats()
    stats["kofi_brutto_eur"] = money_add(stats.get("kofi_brutto_eur", 0.0), amount)
    stats["kofi_netto_eur"] = money_add(stats.get("kofi_netto_eur", 0.0), netto)
    save_stats(stats)

    case_id = _make_case_id("K-DON", kofi_id if (kofi_id and not is_placeholder) else "")
    send_case_embed(
        platform="KOFI",
        category="DONATION",
        donator=donator,
        amount_eur=amount,
        oval_office="Ko-fi-Donation bestätigt.",
        case_id=case_id,
    )

    # Order: status, then goal (so goal stays last)
    upsert_status_embed()
    ensure_goal_embed_if_needed()
    return jsonify({"status": "ok"}), 200




# =====================================================
# TEBEX (FiveM Store) - Polling der Plugin-API
# =====================================================
# Tebex postet eigenstaendig in Discord. Wir wollen die Kaeufe NUR ins
# Goal/Leaderboard mitzaehlen, ohne zweiten Embed. Polling reicht voellig
# und braucht keine oeffentliche URL - nur den Server-Secret-Key aus dem
# Tebex-Panel (Integrations -> Game Server -> Server Secret).
TEBEX_SECRET = os.getenv("TEBEX_SECRET_KEY", "").strip()
TEBEX_POLL_INTERVAL_SEC = max(15, int(os.getenv("TEBEX_POLL_INTERVAL_SEC", "60")))
TEBEX_FEE_PERCENT = float(os.getenv("TEBEX_FEE_PERCENT", "0.0"))
TEBEX_API_URL = os.getenv("TEBEX_API_URL", "https://plugin.tebex.io/payments").strip()
TEBEX_SEEN_FILE = os.getenv("TEBEX_SEEN_FILE", "tebex_seen.json").strip()


def _tebex_seen_load() -> Dict[str, Any]:
    d = _load_json(TEBEX_SEEN_FILE, {"initialized": False, "seen_ids": []})
    if not isinstance(d, dict):
        d = {"initialized": False, "seen_ids": []}
    try:
        seen = set(int(x) for x in d.get("seen_ids", []))
    except Exception:
        seen = set()
    return {"initialized": bool(d.get("initialized")), "seen_ids": seen}


def _tebex_seen_save(state: Dict[str, Any]) -> None:
    _save_json(TEBEX_SEEN_FILE, {
        "initialized": bool(state.get("initialized")),
        "seen_ids": sorted(int(x) for x in state.get("seen_ids", set())),
    })


def _tebex_netto_from_amount(amount: float) -> float:
    a = _to_dec(amount)
    fee = a * _to_dec(max(TEBEX_FEE_PERCENT, 0.0))
    net = a - fee
    return float(net.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP))


def _tebex_fetch_payments() -> list:
    """Holt die letzten Payments von Tebex. Returns Liste oder []."""
    if not TEBEX_SECRET:
        return []
    try:
        r = requests.get(
            TEBEX_API_URL,
            headers={"X-Tebex-Secret": TEBEX_SECRET, "Accept": "application/json"},
            params={"limit": 100},
            timeout=15,
        )
        if r.status_code != 200:
            logging.warning("Tebex-API HTTP %s: %s", r.status_code, r.text[:200])
            return []
        try:
            data = r.json()
        except Exception as e:
            logging.warning("Tebex-API: ungueltiges JSON: %s", e)
            return []
        # Manche Tebex-Endpunkte wrappen die Payments in {"data": [...]}.
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            data = data["data"]
        return data if isinstance(data, list) else []
    except Exception as e:
        logging.warning("Tebex-API-Aufruf fehlgeschlagen: %s", e)
        return []


def _tebex_extract(p: Dict[str, Any]) -> Optional[Tuple[int, str, float, str, str, list]]:
    """Extrahiert (id, donator, amount, status, currency, packages) aus einem Tebex-Payment."""
    try:
        pid = int(p.get("id") or p.get("payment_id") or 0)
    except (TypeError, ValueError):
        pid = 0
    if not pid:
        return None
    status = str(p.get("status") or "").strip()
    raw_amount = p.get("amount") or p.get("price") or 0
    try:
        amount = float(str(raw_amount).replace(",", "."))
    except (TypeError, ValueError):
        amount = 0.0
    # Donator: bevorzugt player.name, sonst email-Local-Part, sonst Fallback.
    donator = ""
    player = p.get("player")
    if isinstance(player, dict):
        donator = (player.get("name") or "").strip()
    if not donator:
        email = (p.get("email") or "").strip()
        if "@" in email:
            donator = email.split("@", 1)[0]
        else:
            donator = email
    if not donator:
        donator = "Tebex-Kunde"
    currency = "EUR"
    cur = p.get("currency")
    if isinstance(cur, dict):
        currency = (cur.get("iso_4217") or "EUR").upper()
    elif isinstance(cur, str):
        currency = cur.upper()
    # Pakete (Name + Quantity) fuer Oval-Office-Zeile
    packages = []
    raw_pkgs = p.get("packages")
    if isinstance(raw_pkgs, list):
        for pkg in raw_pkgs:
            if not isinstance(pkg, dict):
                continue
            name = str(pkg.get("name") or "").strip()
            if not name:
                continue
            try:
                qty = int(pkg.get("quantity") or 1)
            except (TypeError, ValueError):
                qty = 1
            packages.append({"name": name, "quantity": max(1, qty)})
    return (pid, donator, amount, status, currency, packages)


def _tebex_oval_office(packages: list) -> str:
    """Baut die Oval-Office-Zeile fuer den Discord-Embed - nur das gekaufte Paket."""
    if not packages:
        return "—"
    parts = []
    for pkg in packages:
        name = pkg.get("name") or ""
        qty = pkg.get("quantity", 1)
        parts.append(f"{name} ×{qty}" if qty > 1 else name)
    joined = ", ".join(parts)
    if len(joined) > 80:
        joined = joined[:77] + "..."
    return f"({joined})"


def _tebex_poll_once() -> None:
    if not TEBEX_SECRET:
        return
    payments = _tebex_fetch_payments()
    state = _tebex_seen_load()
    first_run = not state["initialized"]
    new_ones = []
    for p in payments:
        ext = _tebex_extract(p)
        if not ext:
            continue
        pid, donator, amount, status, currency, packages = ext
        if pid in state["seen_ids"]:
            continue
        # Status: nur abgeschlossene Kaeufe zaehlen.
        if status and status.lower() not in {"complete", "completed", "paid"}:
            continue
        # Nicht-EUR-Payments uebernehmen wir konservativ nur als gesehen (kein
        # automatischer Kursumtausch - sonst koennte der Goal-Stand kippen).
        if currency != "EUR":
            logging.info("Tebex-Payment %s in %s uebersprungen (nur EUR wird verbucht).", pid, currency)
            state["seen_ids"].add(pid)
            continue
        if amount <= 0:
            state["seen_ids"].add(pid)
            continue
        new_ones.append((pid, donator, amount, packages))
        state["seen_ids"].add(pid)

    if first_run:
        # Beim ersten Lauf alle aktuellen Payments nur als "gesehen" markieren -
        # ohne sie zu verbuchen (sonst springt der Goal-Stand schlagartig hoch).
        state["initialized"] = True
        _tebex_seen_save(state)
        logging.info("Tebex-Polling initialisiert: %s Altdaten als gesehen markiert.",
                     len(state["seen_ids"]))
        return

    if not new_ones:
        _tebex_seen_save(state)
        return

    stats = load_stats()
    for pid, donator, amount, packages in new_ones:
        netto = _tebex_netto_from_amount(amount)
        stats["tebex_brutto_eur"] = money_add(stats.get("tebex_brutto_eur", 0.0), amount)
        stats["tebex_netto_eur"] = money_add(stats.get("tebex_netto_eur", 0.0), netto)
        case_id = _make_case_id("S-TBX", str(pid))
        oval = _tebex_oval_office(packages)
        # Postet das Embed UND haengt den Eintrag ans case_files.jsonl an
        # (send_case_embed ruft _append_case_log intern auf).
        try:
            send_case_embed(
                platform="TEBEX",
                category="DONATION",
                donator=donator,
                amount_eur=amount,
                oval_office=oval,
                case_id=case_id,
            )
        except Exception:
            logging.exception("Tebex send_case_embed fehlgeschlagen (id=%s) - logge nur ins case_files.jsonl", pid)
            _append_case_log(
                case_id=case_id, platform="TEBEX", category="DONATION",
                donator=donator, amount_eur=amount,
            )
        logging.info("Tebex-Kauf verbucht: id=%s donator=%r brutto=%.2f netto=%.2f pkgs=%s",
                     pid, donator, amount, netto,
                     ",".join(p["name"] for p in packages) or "-")
    save_stats(stats)
    _tebex_seen_save(state)

    # Goal-/Status-Embed aktualisieren - Tebex postet zwar selbst, aber der
    # Goal-Stand muss live nachgezogen werden.
    try:
        upsert_status_embed()
        ensure_goal_embed_if_needed()
    except Exception:
        logging.exception("Status-Embed-Update nach Tebex-Buchung fehlgeschlagen")


def run_tebex_poller() -> None:
    if not TEBEX_SECRET:
        logging.info("Tebex-Polling deaktiviert (kein TEBEX_SECRET_KEY in .env).")
        return
    logging.info("Tebex-Polling aktiv (Intervall %ss, Endpoint %s).",
                 TEBEX_POLL_INTERVAL_SEC, TEBEX_API_URL)
    while True:
        try:
            _tebex_poll_once()
        except Exception:
            logging.exception("Tebex-Poller-Fehler (mache nach Intervall weiter)")
        time.sleep(TEBEX_POLL_INTERVAL_SEC)


# --------------------------
# API (für OBS/Dashboard)
# --------------------------
@app.route("/api/stats", methods=["GET", "OPTIONS"])
def api_stats():
    # OPTIONS (Preflight) wird durch Flask automatisch geroutet; wir geben 204 zurück
    if request.method == "OPTIONS":
        return ("", 204)

    stats = load_stats()
    netto = float(total_netto(stats))
    # Ziel nicht verstecken im Overlay-API: Overlay braucht goal für Prozentrechnung
    return jsonify({
        "goal": float(current_goal_eur()),
        "netto_total": round(netto, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
    }), 200


@app.route("/api/leaderboard", methods=["GET", "OPTIONS"])
def api_leaderboard():
    if request.method == "OPTIONS":
        return ("", 204)
    scope = (request.args.get("scope") or "all").lower()
    if scope not in {"all", "current"}:
        scope = "all"
    try:
        limit = int(request.args.get("limit") or "10")
    except ValueError:
        limit = 10
    limit = max(1, min(limit, 100))
    donors = leaderboard.top_donors(
        scope=scope, limit=limit,
        case_file=CASE_FILE, stream_start_file=STREAM_START_FILE,
    )
    return jsonify({
        "scope": scope,
        "limit": limit,
        "donors": donors,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }), 200


@app.route("/overlay/<path:filename>", methods=["GET"])
def overlay_static(filename: str):
    from flask import send_from_directory, abort
    overlay_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "obs_overlay")
    safe = os.path.normpath(filename)
    if safe.startswith("..") or os.path.isabs(safe):
        abort(404)
    return send_from_directory(overlay_dir, safe)


# Root redirect zu /admin/ damit https://liberty-bot.../ nicht leer ist
@app.route("/", methods=["GET"])
def _root_redirect():
    return redirect("/admin/", code=302)


# Mount admin panel (Basic-Auth required via .env ADMIN_USER + ADMIN_PASS)
app.register_blueprint(admin_routes.admin_bp)
def run_kofi_server() -> None:
    logging.info("Starte Ko-fi Relay auf %s:%s …", KOFI_LISTEN_HOST, KOFI_LISTEN_PORT)
    app.run(host=KOFI_LISTEN_HOST, port=KOFI_LISTEN_PORT, debug=False, use_reloader=False)


# =====================================================
# TWITCH (EventSub WebSocket)
# =====================================================
def _tier_name(tier: str) -> str:
    t = (tier or "").strip()
    return {"1000": "Tier 1", "2000": "Tier 2", "3000": "Tier 3", "Prime": "Prime"}.get(t, t or "?")


def _sub_values(tier: str) -> Tuple[float, float]:
    t = (tier or "").strip()
    if t == "2000":
        return SUB_T2_BRUTTO_EUR, SUB_T2_NETTO_EUR
    if t == "3000":
        return SUB_T3_BRUTTO_EUR, SUB_T3_NETTO_EUR
    if t.lower() == "prime" or t == "Prime":
        return SUB_PRIME_BRUTTO_EUR, SUB_PRIME_NETTO_EUR
    return SUB_T1_BRUTTO_EUR, SUB_T1_NETTO_EUR


class TwitchRelay:
    def __init__(self) -> None:
        self.twitch: Optional["Twitch"] = None
        self.eventsub: Optional["EventSubWebsocket"] = None

    def enabled(self) -> bool:
        return (
            TWITCH_AVAILABLE
            and bool(TWITCH_CLIENT_ID)
            and bool(TWITCH_CLIENT_SECRET)
            and bool(TWITCH_BROADCASTER_ID)
        )

    async def setup(self) -> None:
        if not self.enabled():
            logging.warning("Twitch Relay deaktiviert (TWITCH_* ENV fehlt oder twitchAPI nicht verfügbar).")
            return

        logging.info("Initialisiere Twitch API …")
        self.twitch = await Twitch(TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET)

        scopes = [AuthScope.CHANNEL_READ_SUBSCRIPTIONS, AuthScope.BITS_READ]
        _token_path = os.environ.get("LIBERTY_USER_TOKEN_FILE", "/app/data/user_token.json")
        _token_data = _load_json(_token_path, None)
        if _token_data and _token_data.get("token") and _token_data.get("refresh"):
            logging.info("Twitch User-Token aus %s geladen (non-interactive)", _token_path)
            try:
                await self.twitch.set_user_authentication(
                    _token_data["token"], scopes, _token_data["refresh"]
                )
            except Exception as e:
                logging.error("set_user_authentication fehlgeschlagen: %s — versuche interaktiven Fallback", e)
                helper = UserAuthenticationStorageHelper(self.twitch, scopes)
                await helper.bind()
        else:
            logging.warning("Kein user_token.json bei %s — versuche interaktiven OAuth (nur mit Browser)", _token_path)
            helper = UserAuthenticationStorageHelper(self.twitch, scopes)
            await helper.bind()

        user = await first(self.twitch.get_users(user_ids=[str(TWITCH_BROADCASTER_ID)]))
        if not user:
            raise RuntimeError("Broadcaster nicht gefunden – TWITCH_BROADCASTER_ID prüfen.")
        logging.info("Broadcaster geladen: %s (ID %s)", user.login, TWITCH_BROADCASTER_ID)

        # EventSub-WebSocket transport authenticates via Twitch's session_id
        # handshake (the websocket URL is signed per-session). twitchAPI verifies
        # the session ownership on every message internally; there is no HMAC
        # header to validate manually here (that exists only for the webhook
        # HTTP transport, which we do not use).
        self.eventsub = EventSubWebsocket(self.twitch)
        self.eventsub.start()

        await self.eventsub.listen_channel_subscribe(str(TWITCH_BROADCASTER_ID), self.on_subscribe)
        await self.eventsub.listen_channel_subscription_message(str(TWITCH_BROADCASTER_ID), self.on_resub)
        await self.eventsub.listen_channel_subscription_gift(str(TWITCH_BROADCASTER_ID), self.on_gift)
        await self.eventsub.listen_channel_cheer(str(TWITCH_BROADCASTER_ID), self.on_cheer)

        logging.info("EventSub aktiv: subscribe, resub, gift, cheer")

    def _twitch_dedupe(self, data: Any) -> bool:
        try:
            mid = getattr(getattr(data, "metadata", None), "message_id", None)
            if mid:
                ek = f"twitch:{mid}"
                if is_duplicate(ek):
                    logging.info("Twitch duplicate ignored: %s", ek)
                    return True
        except Exception:
            pass
        return False

    async def on_subscribe(self, data: "ChannelSubscribeEvent") -> None:
        if self._twitch_dedupe(data):
            return

        ev = getattr(data, "event", None)
        username = getattr(ev, "user_name", None) or "Unbekannt"
        tier = getattr(ev, "tier", None) or "1000"
        is_gift = bool(getattr(ev, "is_gift", False))

        # Gifted subs are handled by the gift event to avoid double counting
        if is_gift:
            logging.info("Subscribe(is_gift=True) ignored (gift event handles it).")
            return

        brutto, netto = _sub_values(str(tier))

        stats = load_stats()
        stats["subs_brutto_eur"] = money_add(stats.get("subs_brutto_eur", 0.0), brutto)
        stats["subs_netto_eur"] = money_add(stats.get("subs_netto_eur", 0.0), netto)
        save_stats(stats)

        case_id = _make_case_id("T-SUB", getattr(ev, "user_id", "") or "")
        send_case_embed(
            platform="TWITCH",
            category="SUB",
            donator=username,
            amount_eur=brutto,
            oval_office=f"Twitch Sub bestätigt. ({_tier_name(str(tier))})",
            case_id=case_id,
        )

        upsert_status_embed()
        ensure_goal_embed_if_needed()

    async def on_resub(self, data: "ChannelSubscriptionMessageEvent") -> None:
        if self._twitch_dedupe(data):
            return

        ev = getattr(data, "event", None)
        username = getattr(ev, "user_name", None) or "Unbekannt"
        tier = getattr(ev, "tier", None) or "1000"
        months = getattr(ev, "cumulative_months", None)

        brutto, netto = _sub_values(str(tier))

        stats = load_stats()
        stats["subs_brutto_eur"] = money_add(stats.get("subs_brutto_eur", 0.0), brutto)
        stats["subs_netto_eur"] = money_add(stats.get("subs_netto_eur", 0.0), netto)
        save_stats(stats)

        detail = f"{_tier_name(str(tier))}"
        if months is not None:
            try:
                detail += f" • {int(months)} Monate"
            except Exception:
                pass

        case_id = _make_case_id("T-RSB", getattr(ev, "user_id", "") or "")
        send_case_embed(
            platform="TWITCH",
            category="RESUB",
            donator=username,
            amount_eur=brutto,
            oval_office=f"Twitch Resub bestätigt. ({detail})",
            case_id=case_id,
        )

        upsert_status_embed()
        ensure_goal_embed_if_needed()

    async def on_gift(self, data: "ChannelSubscriptionGiftEvent") -> None:
        if self._twitch_dedupe(data):
            return

        ev = getattr(data, "event", None)
        gifter = getattr(ev, "user_name", None) or "Anonym"
        total = int(getattr(ev, "total", 1) or 1)
        tier = getattr(ev, "tier", None) or "1000"

        brutto, netto = _sub_values(str(tier))

        stats = load_stats()
        stats["gifted_subs_total"] = int(stats.get("gifted_subs_total", 0)) + total
        stats["subs_brutto_eur"] = money_add(
            stats.get("subs_brutto_eur", 0.0), money_mul(brutto, total)
        )
        stats["subs_netto_eur"] = money_add(
            stats.get("subs_netto_eur", 0.0), money_mul(netto, total)
        )
        save_stats(stats)

        case_id = _make_case_id("T-GFT", getattr(ev, "user_id", "") or "")
        send_case_embed(
            platform="TWITCH",
            category="GIFT",
            donator=gifter,
            amount_eur=(brutto * total),
            oval_office=f"Twitch Gift Subs bestätigt. (x{total} • {_tier_name(str(tier))})",
            case_id=case_id,
        )

        upsert_status_embed()
        ensure_goal_embed_if_needed()

    async def on_cheer(self, data: "ChannelCheerEvent") -> None:
        if self._twitch_dedupe(data):
            return

        ev = getattr(data, "event", None)
        username = getattr(ev, "user_name", None) or "Unbekannt"
        bits = int(getattr(ev, "bits", 0) or 0)
        value = money_mul(BITS_EUR_PER_BIT, bits)

        stats = load_stats()
        stats["bits_total"] = int(stats.get("bits_total", 0)) + bits
        stats["bits_value_eur"] = money_add(stats.get("bits_value_eur", 0.0), value)
        save_stats(stats)

        case_id = _make_case_id("T-BIT", getattr(ev, "user_id", "") or "")
        send_case_embed(
            platform="TWITCH",
            category="BITS",
            donator=username,
            amount_eur=value,
            oval_office=f"Twitch Bits bestätigt. ({bits} Bits)",
            case_id=case_id,
        )

        upsert_status_embed()
        ensure_goal_embed_if_needed()

    async def run(self) -> None:
        if not self.enabled():
            return
        await self.setup()
        logging.info("Twitch Relay läuft – wartet auf Events …")
        try:
            while True:
                await asyncio.sleep(60)
        finally:
            try:
                if self.eventsub is not None:
                    await self.eventsub.stop()
            except Exception:
                pass
            try:
                if self.twitch is not None:
                    await self.twitch.close()
            except Exception:
                pass


# =====================================================
# MAIN
# =====================================================
def main() -> None:
    # Ensure status exists (and goal if already reached) on startup
    try:
        upsert_status_embed()
    except Exception:
        pass

    try:
        ensure_goal_embed_on_startup()
    except Exception:
        pass

    t = threading.Thread(target=run_kofi_server, daemon=True)
    t.start()

    if TEBEX_SECRET:
        threading.Thread(target=run_tebex_poller, daemon=True).start()

    relay = TwitchRelay()
    if relay.enabled():
        asyncio.run(relay.run())
    else:
        logging.info("Relay läuft (nur Ko-fi). Warte auf Webhooks …")
        while True:
            time.sleep(60)


if __name__ == "__main__":
    main()
