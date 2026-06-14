import hmac
import json
import logging
import os
import random
from datetime import datetime, timezone
from typing import Dict, Any

import requests
from dotenv import load_dotenv

load_dotenv()
from flask import Flask, request, jsonify
tok = os.getenv("KOFI_VERIFICATION_TOKEN", "")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.info("Loaded KOFI_VERIFICATION_TOKEN (len=%s)", len(tok.strip()))

# ==========================
# KONFIG
# ==========================
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_USERNAME = os.getenv("DISCORD_USERNAME", "The Accountant")
DISCORD_AVATAR_URL = os.getenv("DISCORD_AVATAR_URL", "")

STATS_FILE = "stats.json"

# Goal (intern), Anzeige nur in %
GOAL_NETTO_EUR = float(os.getenv("GOAL_NETTO_EUR", "1650.00"))
PROGRESS_BAR_LENGTH = 20

# Ko-fi: PayPal Gebühren (Schätzung)
PAYPAL_FEE_PERCENT = float(os.getenv("PAYPAL_FEE_PERCENT", "0.0249"))
PAYPAL_FEE_FIXED = float(os.getenv("PAYPAL_FEE_FIXED", "0.35"))

FOOTER_QUOTES = [
    "Was vergangen ist, beginnt in Liberty City.",
    "Alles hat seinen Preis – besonders Loyalität.",
    "Niemand behält lange die Krone in Liberty City.",
    "Geld redet, aber in Liberty City schreit es.",
    "Vertraue niemandem, der zu schnell zustimmt.",
]

# ==========================
# STATS
# ==========================
def _defaults_stats() -> dict:
    # Gemeinsame Keys für Ko-fi + Twitch (eine stats.json)
    return {
        "kofi_brutto_eur": 0.0,
        "kofi_netto_eur": 0.0,
        "subs_brutto_eur": 0.0,
        "subs_netto_eur": 0.0,
        "gifted_subs_total": 0,
        "bits_total": 0,
        "bits_value_eur": 0.0,
    }

def load_stats() -> dict:
    if not os.path.exists(STATS_FILE):
        return _defaults_stats()
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        stats = _defaults_stats()
        if isinstance(data, dict):
            stats.update({k: data.get(k, v) for k, v in stats.items()})
            # Migration alter Keys (falls vorhanden)
            if "kofi_brutto" in data and stats["kofi_brutto_eur"] == 0.0:
                stats["kofi_brutto_eur"] = float(data.get("kofi_brutto", 0.0) or 0.0)
            if "kofi_netto" in data and stats["kofi_netto_eur"] == 0.0:
                stats["kofi_netto_eur"] = float(data.get("kofi_netto", 0.0) or 0.0)
            if "subs_brutto" in data and stats["subs_brutto_eur"] == 0.0:
                stats["subs_brutto_eur"] = float(data.get("subs_brutto", 0.0) or 0.0)
            if "subs_netto" in data and stats["subs_netto_eur"] == 0.0:
                stats["subs_netto_eur"] = float(data.get("subs_netto", 0.0) or 0.0)
            if "bits_netto" in data and stats["bits_value_eur"] == 0.0:
                stats["bits_value_eur"] = float(data.get("bits_netto", 0.0) or 0.0)
        return stats
    except Exception:
        return _defaults_stats()

def save_stats(stats: dict) -> None:
    base = _defaults_stats()
    for k, v in base.items():
        stats.setdefault(k, v)
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

def total_netto(stats: dict) -> float:
    # Maßgabe: NUR NETTO aus Ko-fi + Subs + Bits (Prime zählt in Subs)
    return float(
        stats.get("kofi_netto_eur", 0.0)
        + stats.get("subs_netto_eur", 0.0)
        + stats.get("bits_value_eur", 0.0)
    )

def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))

def _make_progress_bar(current: float, goal: float, length: int) -> str:
    if goal <= 0:
        return "—"
    ratio = _clamp(current / goal, 0.0, 1.0)
    filled = int(ratio * length)
    return "█" * filled + "░" * (length - filled)

def progress_block_percent_only(current_netto: float) -> str:
    percent = int(_clamp((current_netto / GOAL_NETTO_EUR) * 100, 0, 100))
    bar = _make_progress_bar(current_netto, GOAL_NETTO_EUR, PROGRESS_BAR_LENGTH)
    return f"🎯 **Fortschritt**\n{bar}  **{percent}%**"

# ==========================
# DISCORD
# ==========================
def send_discord_embed(donator: str, amount: float, currency: str) -> None:
    if not DISCORD_WEBHOOK_URL.startswith("https://discord.com/api/webhooks/"):
        logging.error("DISCORD_WEBHOOK_URL ist nicht gesetzt/ungültig.")
        return

    stats = load_stats()
    netto_sum = total_netto(stats)
    goal_progress = progress_block_percent_only(netto_sum)

    embed = {
        "author": {"name": "Liberty City White House • Level 5 Clearance"},
        "title": "🗽 WELCOME TO LIBERTY CITY 🗽",
        "description": "\n".join([
            "**Vielen Dank für deine Spende**",
            "*Du bist Liberty!*",
            "",
            f"👤 Donator: {donator}",
            f"💰 Betrag: {amount:.2f} €",
            "",
            "",  # größerer Abstand vor Gesamtstatus
            "",  # größerer Abstand vor Gesamtstatus
        ]),
        "color": 0xE94560,  # Ko-fi Streifenfarbe
        "fields": [
            {
                "name": "📊 Gesamtstatus",
                "value": (
                    f"💰 Ko-fi Spenden: {stats['kofi_brutto_eur']:.2f} € ({stats['kofi_netto_eur']:.2f} €)\n"
                    f"⭐ Subs: {stats['subs_brutto_eur']:.2f} € ({stats['subs_netto_eur']:.2f} €)\n"
                    f"🎁 Gifted Subs: {stats['gifted_subs_total']}\n"
                    f"💎 Bits: {stats['bits_value_eur']:.2f} €\n\n"
                    f"{goal_progress}\n\n"
                    f"**Spenden gesamt (netto): {netto_sum:.2f} €**"
                ),
                "inline": False,
            }
        ],
        "footer": {"text": random.choice(FOOTER_QUOTES)},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    payload = {
        "username": DISCORD_USERNAME,
        "avatar_url": DISCORD_AVATAR_URL or None,
        "embeds": [embed],
    }

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        logging.info(f"Discord Status: {resp.status_code}")
    except Exception as e:
        logging.error(f"Discord send failed: {e}")

# ==========================
# FLASK (KO-FI)
# ==========================
app = Flask(__name__)

@app.route("/kofi", methods=["POST"])
def handle_kofi():
    """
    Ko-fi kann Webhooks entweder als JSON (application/json) oder als Form-POST mit
    einem Feld "data" (JSON-String) senden. Wir akzeptieren beides.
    """
    payload = request.get_json(silent=True)
    if not payload:
        payload = {}
        # Ko-fi sendet häufig: data=<json>
        if request.form and "data" in request.form:
            try:
                payload = json.loads(request.form.get("data") or "{}")
            except Exception:
                payload = {}

    # Manche Integrationen verschachteln das eigentliche Event unter "data"
    data = payload.get("data", payload) if isinstance(payload, dict) else {}

    # Optional: Verification Token prüfen (empfohlen)
    expected_token = os.getenv("KOFI_VERIFICATION_TOKEN", "").strip()
    if expected_token:
        received_token = (
            (data.get("verification_token") if isinstance(data, dict) else None)
            or (payload.get("verification_token") if isinstance(payload, dict) else None)
        )
        if not hmac.compare_digest(str(received_token or ""), expected_token):
            logging.warning("Ko-fi Webhook abgelehnt: verification_token passt nicht.")
            return jsonify({"status": "forbidden"}), 403

    donator = (data.get("from_name") or data.get("username") or "Unbekannt") if isinstance(data, dict) else "Unbekannt"
    currency = "€"

    try:
        raw_amount = (data.get("amount", "0") if isinstance(data, dict) else "0")
        amount = float(str(raw_amount).replace(",", "."))
    except Exception:
        amount = 0.0

    paypal_fee = amount * PAYPAL_FEE_PERCENT + PAYPAL_FEE_FIXED
    netto = max(amount - paypal_fee, 0.0)

    stats = load_stats()
    stats["kofi_brutto_eur"] += amount
    stats["kofi_netto_eur"] += netto
    save_stats(stats)

    send_discord_embed(donator, amount, currency)
    return jsonify({"status": "ok"}), 200

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.info("Starte Ko-fi StreamRelay auf Port 8080 …")
    app.run(host=os.getenv("KOFI_LISTEN_HOST","127.0.0.1"), port=int(os.getenv("KOFI_LISTEN_PORT","8080")))

if __name__ == "__main__":
    main()
