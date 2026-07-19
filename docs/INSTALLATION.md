# 📦 Installation

Vollständige Setup-Anleitung für SEKT6R Crime Automation — von Voraussetzungen bis zum Production-Deployment.

## Inhalt

1. [Voraussetzungen](#voraussetzungen)
2. [Discord-Bot vorbereiten](#discord-bot-vorbereiten)
3. [Lokale Installation](#lokale-installation)
4. [Konfiguration](#konfiguration)
5. [Starten](#starten)
6. [Production-Setup (Windows-Services)](#production-setup-windows-services)
7. [Linux/macOS-Setup](#linuxmacos-setup)
8. [Updates](#updates)

## Voraussetzungen

### Software

| Komponente | Version | Notizen |
|---|---|---|
| **Python** | 3.11, 3.12, 3.13 oder 3.14 | Im PATH aufrufbar |
| **Git** | beliebig | Für Updates per `git pull` |
| **Discord-Account** | — | Für Bot-Erstellung |
| **NSSM** (optional) | 2.24+ | Nur für Windows-Auto-Start, [Download](https://nssm.cc/download) |

### Accounts

- **Discord Developer Portal**: <https://discord.com/developers/applications>
- **Anthropic Console** (für Claude): <https://console.anthropic.com>
- **OpenAI Platform** (optional, für GPT): <https://platform.openai.com>

### Hardware-Empfehlung

| Setup | RAM | CPU | Speicher |
|---|---|---|---|
| Dev/Test | 4 GB | 2 Cores | 2 GB |
| Production (1–5 Crews) | 4 GB | 2 Cores | 5 GB |
| Production (20+ Crews) | 8 GB | 4 Cores | 10 GB |

KI-Calls laufen extern — die KI-Provider tragen die Last, nicht dein Server.

## Discord-Bot vorbereiten

> 💡 **Komplette idiotensichere Schritt-für-Schritt-Anleitung:** **[DISCORD_BOT_SETUP.md](DISCORD_BOT_SETUP.md)** — empfohlen wenn du noch nie einen Discord-Bot eingerichtet hast.
>
> Die Kurzform unten ist nur eine Übersicht für erfahrene Nutzer.

### Quick-Setup

1. **Bot-Application erstellen** auf <https://discord.com/developers/applications>
   - „New Application" → Name eingeben → Create
   - Linke Sidebar → „Bot"
2. **Privileged Gateway Intents aktivieren** (Bot-Seite, unten)
   - ✅ **Message Content Intent** (zwingend für Boss-Feedback)
   - ✅ **Server Members Intent** (optional)
3. **Bot-Token kopieren** (Reset Token → Copy)
   - ⚠️ Token niemals committen, teilen oder in Screenshots zeigen
4. **OAuth2-URL generieren** (Sidebar → OAuth2 → URL Generator)
   - Scopes: `bot` + `applications.commands`
   - Bot Permissions: View Channels, Send Messages, Embed Links, Attach Files, Read Message History, Add Reactions, Manage Messages
5. **URL im Browser öffnen** → Server wählen → Authorize
6. **Channel-IDs sammeln** in Discord
   - Einstellungen → Erweitert → Entwicklermodus aktivieren
   - Rechtsklick auf Channel → ID kopieren

Du brauchst pro Crew typischerweise zwei Channels:
- **Auftrags-Channel** — Bot postet hier die Aufträge
- **Zusatzinfo-Channel** — Crew-Boss antwortet hier mit Klartext

Plus optional einen **Admin-Channel** für Personal-Bedarf-Posts (siehe [CONFIGURATION.md](CONFIGURATION.md)).

## Lokale Installation

### Repo clonen

```bash
git clone https://github.com/RDanton21/CrimeJobs-Handler-Liberty-City.git
cd CrimeJobs-Handler-Liberty-City
```

### Windows — automatisch

```cmd
scripts\setup.bat
```

Erstellt `.venv`, installiert Dependencies, kopiert `.env.example` zu `.env`.

### Manuelles Setup (alle Plattformen)

```bash
# Virtuelles Environment
python -m venv .venv

# Aktivieren (Windows)
.venv\Scripts\activate

# Aktivieren (Linux/macOS)
source .venv/bin/activate

# Dependencies installieren
pip install --upgrade pip
pip install -r requirements.txt

# Beispiel-Config kopieren
cp .env.example .env    # Linux/macOS
copy .env.example .env  # Windows
```

## Konfiguration

### `.env` befüllen

```env
# Discord Bot — PFLICHT
DISCORD_BOT_TOKEN=MTAwM...your...token...here

# Admin-Login — PFLICHT
ADMIN_USERNAME=admin
ADMIN_PASSWORD=ein_starkes_passwort_min_16_zeichen

# KI-Provider — mindestens einer empfohlen
ANTHROPIC_API_KEY=sk-ant-api03-...
OPENAI_API_KEY=sk-...

# Defaults (optional, mit Web-UI überschreibbar)
DEFAULT_AI_PROVIDER=anthropic
DEFAULT_CLAUDE_MODEL=claude-sonnet-4-5-20250929
DEFAULT_OPENAI_MODEL=gpt-4o

# Server-Bindings (optional, Defaults wie unten)
BACKEND_HOST=127.0.0.1
BACKEND_PORT=8000
BOT_API_HOST=127.0.0.1
BOT_API_PORT=8001

# Bilder + DB-Pfad (optional)
IMAGE_DIR=data/images
DB_PATH=data/crime.db
```

### Sicherheits-Hinweise

- **Backend lauscht nur auf 127.0.0.1** — von außen nicht erreichbar (gewollt!)
- **Niemals `.env` committen** — `.gitignore` schützt sie schon
- **Bot-Token niemals teilen** — bei Leak: im Developer Portal regenerieren
- Für Remote-Zugriff: **SSH-Tunnel** oder **Tailscale**, kein Port-Forward

## Starten

### Quick-Start (Dev)

```cmd
# Windows
scripts\run_all.bat
```

Startet beide Prozesse (Backend + Bot) in einem Fenster mit Logs.

### Manuelles Starten

In **zwei separaten Terminals** (beide mit aktiviertem venv):

**Terminal 1 — Backend:**
```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

**Terminal 2 — Discord-Bot:**
```bash
python -m backend.bot
```

### Verifikation

1. Browser öffnen: <http://127.0.0.1:8000>
2. HTTP-Basic-Login mit `ADMIN_USERNAME` + `ADMIN_PASSWORD` aus `.env`
3. Dashboard sollte erscheinen
4. Backend-Health: <http://127.0.0.1:8000/api/health> → `{"ok": true}`
5. Bot-Health: <http://127.0.0.1:8001/health> → `{"ok": true, "ready": true}`
6. Im Discord-Server sollte der Bot als **online** angezeigt werden

## Production-Setup (Windows-Services)

Für 24/7-Betrieb mit Auto-Start beim Boot.

### NSSM installieren

1. Download: <https://nssm.cc/download>
2. ZIP entpacken → `nssm.exe` aus `win64/` in `C:\Windows\System32\` kopieren (oder `nssm.exe` ins PATH legen)

### Services installieren

Als **Administrator** in PowerShell:

```powershell
cd D:\Crime-Automation
powershell -ExecutionPolicy Bypass -File scripts\install_services.ps1
```

Das Skript registriert zwei Services:
- **CrimeAutoBackend** — FastAPI auf 127.0.0.1:8000
- **CrimeAutoBot** — Discord-Bot mit interner HTTP-API auf 127.0.0.1:8001

### Services starten

```powershell
Start-Service CrimeAutoBackend
Start-Service CrimeAutoBot
```

### Status prüfen

```powershell
Get-Service CrimeAutoBackend, CrimeAutoBot
```

Erwartung: beide `Running`.

### Logs

Standardmäßig unter:
- `D:\Crime-Automation\logs\backend.log` (stdout)
- `D:\Crime-Automation\logs\backend.err.log` (stderr)
- `D:\Crime-Automation\logs\bot.log` (stdout)
- `D:\Crime-Automation\logs\bot.err.log` (stderr)

Live-View:
```powershell
Get-Content logs\backend.log -Wait -Tail 30
```

### Service-Befehle

```powershell
# Restart nach Code-Änderungen
Restart-Service CrimeAutoBackend
Restart-Service CrimeAutoBot

# Stoppen
Stop-Service CrimeAutoBackend, CrimeAutoBot

# Deinstallieren
nssm remove CrimeAutoBackend confirm
nssm remove CrimeAutoBot confirm
```

## Linux/macOS-Setup

### systemd-Unit (Linux)

`/etc/systemd/system/crime-backend.service`:

```ini
[Unit]
Description=Crime Automation Backend
After=network.target

[Service]
Type=simple
User=crimeauto
WorkingDirectory=/opt/crime-automation
Environment="PATH=/opt/crime-automation/.venv/bin"
ExecStart=/opt/crime-automation/.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/crime-bot.service`:

```ini
[Unit]
Description=Crime Automation Discord Bot
After=network.target crime-backend.service

[Service]
Type=simple
User=crimeauto
WorkingDirectory=/opt/crime-automation
Environment="PATH=/opt/crime-automation/.venv/bin"
ExecStart=/opt/crime-automation/.venv/bin/python -m backend.bot
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Aktivieren:

```bash
sudo systemctl daemon-reload
sudo systemctl enable crime-backend crime-bot
sudo systemctl start crime-backend crime-bot
sudo systemctl status crime-backend crime-bot
```

### macOS (launchd)

`~/Library/LaunchAgents/com.sekt6r.crime-backend.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.sekt6r.crime-backend</string>
    <key>WorkingDirectory</key><string>/Users/yourname/crime-automation</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/yourname/crime-automation/.venv/bin/python</string>
        <string>-m</string><string>uvicorn</string>
        <string>backend.main:app</string>
        <string>--host</string><string>127.0.0.1</string>
        <string>--port</string><string>8000</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardErrorPath</key><string>/Users/yourname/crime-automation/logs/backend.err.log</string>
    <key>StandardOutPath</key><string>/Users/yourname/crime-automation/logs/backend.log</string>
</dict>
</plist>
```

Laden:
```bash
launchctl load ~/Library/LaunchAgents/com.sekt6r.crime-backend.plist
```

## Updates

### Standard-Update

```bash
cd D:\Crime-Automation     # bzw. dein Installationspfad
git pull
```

Bei **Backend-Code-Änderungen**:
```powershell
Restart-Service CrimeAutoBackend
```

Bei **Bot-Code-Änderungen**:
```powershell
Restart-Service CrimeAutoBot
```

Bei **DB-Schema-Änderungen** — passiert automatisch über die `_migrate_add_column_if_missing()`-Helper in `backend/db.py`.

### Bei Konflikten

```bash
# Lokale Änderungen sichern
git stash

# Update holen
git pull

# Lokale Änderungen zurückspielen
git stash pop
```

### Dependencies updaten

Neue Python-Packages werden in `requirements.txt` deklariert. Nach Pull:

```bash
.venv\Scripts\activate
pip install -r requirements.txt --upgrade
```

Dann Services neu starten.

## Nächste Schritte

- **[CONFIGURATION.md](CONFIGURATION.md)** — Settings, KI-Provider, Channels detailliert
- **[ADMIN_GUIDE.md](ADMIN_GUIDE.md)** — Best Practices für Spielleiter
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** — Was tun bei Problemen
