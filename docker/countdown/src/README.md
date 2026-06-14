# Countdown

Discord-Bot, der einen Progress-Bar-Countdown bis **SEKTOR ANNOUNCEMENT II** (05.07.2026, 16:00 Uhr) als selbst-aktualisierendes Embed-Bild in einem Channel anzeigt.

## Features
- Pillow-gerenderter Progress-Bar (1200×400 PNG, Gradient, abgerundete Bar)
- Embed wird alle 60 s editiert (kein Spam)
- Zieldatum, Startdatum, Event-Name, Farben und Channel-ID konfigurierbar in `config.json`
- Stoppt sich automatisch, wenn das Zieldatum erreicht ist

## Setup

```bash
cd Countdown
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# DISCORD_TOKEN in .env eintragen
```

### Bot anlegen & einladen
1. https://discord.com/developers/applications → New Application → Bot anlegen.
2. Token kopieren → in `.env` als `DISCORD_TOKEN=...` eintragen.
3. OAuth2 → URL Generator: Scopes `bot`, Permissions `Send Messages`, `Embed Links`, `Attach Files`. Erzeugte URL öffnen und Bot auf den Server einladen.

### Channel-ID setzen
Discord → Einstellungen → Erweitert → Entwicklermodus aktivieren. Rechtsklick auf den Ziel-Channel → ID kopieren → in `config.json` unter `channel_id` eintragen.

## Start

```bash
source venv/bin/activate
python bot.py
```

Beim ersten Start postet der Bot eine neue Nachricht und merkt sich die `message_id` in `state.json`. Beim nächsten Start (oder im Loop) wird die bestehende Nachricht editiert.

## Konfiguration (`config.json`)

| Feld | Bedeutung |
|---|---|
| `event_name` | Anzeigename im Embed/Bild |
| `target_iso` | Zieldatum, ISO-8601 mit Zeitzone |
| `start_iso` | Nullpunkt der Progress-Bar |
| `channel_id` | Discord-Channel, in dem das Embed lebt |
| `update_seconds` | Update-Intervall (Default 60) |
| `colors.*` | Farben für Bild |
| `image_size` | `[width, height]` des PNGs |

## Vorschau ohne Discord

```bash
python renderer.py
# erzeugt preview.png
```

## Dateien

- `bot.py` – discord.py-Client + Update-Loop
- `renderer.py` – Pillow-Bildgenerator (`render_progress_bar(...)`)
- `config.json` – statische Konfiguration
- `state.json` – Bot-State (`message_id`); nicht committen
- `.env` – Bot-Token; nicht committen
