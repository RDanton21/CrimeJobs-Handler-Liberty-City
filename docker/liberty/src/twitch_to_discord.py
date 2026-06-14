import os
import json
import logging
import asyncio
from dotenv import load_dotenv
from twitchAPI.twitch import Twitch
from twitchAPI.helper import first

load_dotenv()

# ==========================
# KONFIG
# ==========================
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
TWITCH_EVENTSUB_SECRET = os.getenv("TWITCH_EVENTSUB_SECRET")
TWITCH_BROADCASTER_ID = os.getenv("TWITCH_BROADCASTER_ID")

STATS_FILE = "stats.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ==========================
# HILFSFUNKTIONEN
# ==========================
def load_stats():
    if not os.path.exists(STATS_FILE):
        return {
            "subs_brutto_eur": 0.0,
            "subs_netto_eur": 0.0,
            "gifted_subs_total": 0,
            "bits_total": 0,
            "bits_value_eur": 0.0,
        }
    with open(STATS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_stats(stats: dict):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)


# ==========================
# TWITCH RELAY
# ==========================
class TwitchRelay:
    def __init__(self):
        if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
            raise RuntimeError("TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET fehlen")

        if not TWITCH_BROADCASTER_ID:
            raise RuntimeError("TWITCH_BROADCASTER_ID fehlt")

        self.broadcaster_id = TWITCH_BROADCASTER_ID
        self.broadcaster_login = None
        self.broadcaster_user = None
        self.twitch = None

    async def setup_auth_and_user(self):
        logging.info("Initialisiere Twitch API …")

        self.twitch = await Twitch(
            TWITCH_CLIENT_ID,
            TWITCH_CLIENT_SECRET
        )

        # OAuth (User-Auth)
        await self.twitch.authenticate_app([])

        # ==========================
        # 🔧 HIER WAR DEIN FEHLER
        # Broadcaster sauber über ID laden
        # ==========================
        user = await first(
            self.twitch.get_users(user_ids=[str(self.broadcaster_id)])
        )


        if not user:
            raise RuntimeError("Broadcaster nicht gefunden – ID ungültig?")

        self.broadcaster_user = user
        self.broadcaster_login = user.login

        logging.info(
            "Broadcaster geladen: %s (ID %s)",
            self.broadcaster_login,
            self.broadcaster_id
        )

    async def run(self):
        await self.setup_auth_and_user()

        logging.info("Twitch Relay läuft – wartet auf Events …")

        # Placeholder: EventSub / Websocket kommt hier rein
        # Aktuell nur Verbindungs-Test
        while True:
            await asyncio.sleep(60)


# ==========================
# MAIN
# ==========================
async def main_async():
    relay = TwitchRelay()
    await relay.run()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
