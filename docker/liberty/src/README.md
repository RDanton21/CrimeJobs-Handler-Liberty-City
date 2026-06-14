# Liberty City Donations Relay (5EKTOR / StreamLedger)

Webhook-Relay-System für GTA-V-/FiveM-Stream-Donations. Aggregiert **Ko-fi**-Spenden + **Twitch**-Subs/Gifts/Bits, postet Events nach **Discord**, trackt Fundraising-Goal und liefert eine **OBS-Overlay-Progressbar**.

## Stack

- Python 3 · Flask · `twitchAPI` · `python-dotenv` · `requests`
- JSONL-Persistenz (`case_files.jsonl`)
- Windows-Service via `service_start.bat` / `service_stop.bat`

## Komponenten

| Datei | Zweck |
|---|---|
| `liberty_city_relay.py` | Haupt-Server: Ko-fi-Webhook + Twitch-EventSub + Discord-Post + Goal-Progress + Stats + OBS-Overlay + Admin-Panel |
| `leaderboard.py` | Aggregations-Modul für Top-Donatoren (liest `case_files.jsonl`) |
| `admin_routes.py` | Flask-Blueprint `/admin/*` mit Basic-Auth |
| `stream_relay.py` | Standalone Ko-fi-Endpoint (`POST /kofi`), Brutto/Netto |
| `twitch_to_discord.py` | Twitch-EventSub-Websocket-Client (Subs/Gifts/Bits) |
| `white_house_dashboard_server.py` + `WhiteHouseDashboard.html` | Dashboard/API für `case_files.jsonl` (`/api/cases`, `/api/leaderboard`) |
| `obs_overlay/` | Browser-Source-Overlays (Progress-Bar + Leaderboard) |
| `Liberty_City_Sprueche.txt` | Embed-Flavortext (Hot-Reload bei mtime-Änderung) |
| `*.bat` | Start/Stop + Windows-Service-Wrapper |

## Setup

```powershell
# Venv + Deps
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt

# Config
copy .env.example .env
# Werte in .env eintragen
```

### Pflichtfelder in `.env`
- `DISCORD_WEBHOOK_URL`
- `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, `TWITCH_EVENTSUB_SECRET`
- `TWITCH_BROADCASTER_LOGIN`, `TWITCH_BROADCASTER_ID`
- `KOFI_VERIFICATION_TOKEN`

## Run

**Direkt:**
```powershell
.\start_relays.bat
# oder:
.\venv\Scripts\python.exe liberty_city_relay.py
```

**Als Windows-Service** (`LibertyCityRelay`):
```powershell
.\service_start.bat
.\service_stop.bat
```

## OBS-Overlay

Zwei Browser-Sources verfügbar (gleicher Rechner; default `BIND_HOST=127.0.0.1`):

| URL | Inhalt |
|---|---|
| `http://127.0.0.1:8080/overlay/progress.html` | Fundraising-Progress-Bar |
| `http://127.0.0.1:8080/overlay/leaderboard.html?scope=current&limit=5` | Top-N Donatoren des aktuellen Streams |

Leaderboard-Params:
- `scope=current|all` — aktueller Stream vs. All-Time
- `limit=5` — Anzahl Plätze (max 20)
- `ms=10000` — Refresh-Intervall

**OBS-Empfehlung**: Breite 1000 / Höhe 140 (Progress) bzw. 600×400 (Leaderboard), *Shutdown when not visible* = AUS.

## Dashboard

`white_house_dashboard_server.py` (Port `5000`) serviert `WhiteHouseDashboard.html` mit Live-Case-Tabelle, Charts und neuem **Top-Donatoren-Card** (Tabs All-Time / Current Stream). API-Endpoints:
- `GET /api/cases` — alle Cases + Summary
- `GET /api/leaderboard?scope=all|current&limit=N` — Ranking

## Admin-Panel

`http://127.0.0.1:8080/admin/` — Basic-Auth via `ADMIN_USER` + `ADMIN_PASS` aus `.env`.

| Route | Funktion |
|---|---|
| `GET /admin/` | Übersicht + Aktionen |
| `GET/POST /admin/config` | Goal-Betrag + Goal-Title überschreiben (Runtime, ohne Neustart) |
| `POST /admin/stream/reset` | Marker für "aktueller Stream startet jetzt" |
| `POST /admin/stats/reset` | `stats.json` nullen (Backup mit Timestamp) |
| `GET/POST /admin/sprueche` | `Liberty_City_Sprueche.txt` im Browser editieren |

Goal/Title werden via mtime-Watch von `admin_config.json` heiß nachgeladen.

## Status-Embed Verhalten

- `STATUS_REPOST_TO_BOTTOM=1`: alter Status wird gelöscht und neu gepostet → bleibt immer unten
- `STATUS_REPOST_COOLDOWN_SEC=15`: Rate-Limit-Schutz bei vielen Events

## Daten-Persistenz (gitignored)

| Datei | Inhalt |
|---|---|
| `stats.json` | Kumulierte Summen (Ko-fi brutto/netto, Subs, Bits) |
| `case_files.jsonl` | Event-Log, eine Zeile pro Event |
| `goal_*.json`, `status_*.json` | Goal-Progress & Status-Message-State |
| `current_stream_start.json` | Reset-Marker für Current-Stream-Leaderboard |
| `admin_config.json` | Runtime-Override für Goal-Betrag + Title |
| `user_token.json` | Twitch-OAuth-Tokens |
