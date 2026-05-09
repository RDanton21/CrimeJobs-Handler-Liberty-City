# SEKT6R — Crime-Jobs-Handler Liberty City

Admin-Tool für ein **GTA-V-Liberty-City-Roleplay-Projekt**. KI generiert kryptische,
atmosphärische Crime-Aufträge pro Gang, sendet sie über einen Discord-Bot
(„Il Padrino") in crew-spezifische Channels. Crime-Bosse reagieren mit
👍 / 👎 / ❌ — Status fließt automatisch zurück ins Admin-Dashboard. Pro Gang
sequenzielle Storyline mit Berücksichtigung der Beziehungen zwischen den Gangs.

> **Status:** Im Aufbau. RP-Server-Launch geplant für **September 2026**.

---

## Features

### Mission-Workflow
- **KI-generiert** — Aufträge entstehen aus Crew-Story, Beziehungen und Mission-Historie. Automatische Verzweigung nach letzter Reaktion (👍 → Story konsequent fortführen, 👎 → andere Richtung)
- **Roh-Input umschreiben** — Klartext-Briefing wird im RP-Stil verschlüsselt, Locations und Rollen in die Welt der Gang übersetzt
- **Manueller Versand** — Klartext direkt an Discord, ohne KI
- **Zusatzinfos** — werden 1:1 an den KI-Output gehängt (Adressen, GPS, Codes), nicht von der KI berührt
- **Bild-Anhang** — Bild zur Mission, wird mit dem Auftrag im Discord gepostet
- **Umformulieren** — neuer KI-Wurf des aktuellen Drafts mit Story-Kontext
- **Countdown** — Min/Std/Tage; Discord rendert `<t:UNIX:R>` live als „in 2 Stunden", aktualisiert sich client-seitig automatisch
- **Zeitversetzter Versand** — `scheduled_send_at`; Bot-Watcher (alle 30 s) sendet automatisch zum Zeitpunkt
- **Reaktions-Tracking** — Single-Vote: Bot entfernt andere Emojis nach erster Boss-Reaktion, fremde Reaktionen werden gelöscht
- **Versager-Sprüche** — Pool von Sprüchen, die der Bot nach abgelaufener Deadline (ohne Reaktion) zufällig postet
- **Reaktions-Antworten** — Pool von Antworten nach 👍/👎/❌, zufällig gewählt

### Bulk-Operationen
- **Massen-Auftrag** an alle Gangs / nach Stadtteil / manuelle Auswahl
- **Drei Modi** — Klartext direkt, KI-Roh-Input umschreiben, KI aus Story generieren
- **Vorschau bei KI-Modi** — einmaliger KI-Aufruf, editierbar, dann an alle gleichzeitig
- **Parallel-Dispatch** — `asyncio.Semaphore(5)` im Backend, 30 Crews in Sekunden statt Minuten
- **Alle aktiven Aufträge archivieren** — Top-Nav-Button, mit Discord-Cleanup

### Boss-Feedback aus Zusatzinfo-Channel
- Pro Crew zweiter Discord-Channel für Boss-Klartext-Antworten
- Bot pollt den Channel, ordnet Texte per Zeitfenster der jeweiligen Mission zu
- **Bilder/Attachments** werden inline im UI angezeigt
- **Notifications** — Crew-Karte auf Dashboard pulsiert gelb wenn neuer Boss-Text da ist (`localStorage`-Tracking pro Browser)

### Dashboard
- **Reaktions-Statistik** mit Filtern: Stadtteil / Gang / Zeitraum (Heute / 7 Tage / 30 Tage / Gesamt)
- **Klick auf Stats-Kachel** filtert die Card-Liste auf den gewählten Status
- **Stadtteil-Tags** auf den Crew-Karten (Algonquin / Bohan / Broker / Colony Island / Dukes)
- **Sortierung** nach Stadtteil, dann alphabetisch
- **Border-Farbe** der Karte zeigt letzten Reaktions-Status (grün/rot/gelb/neutral)
- **Auto-Refresh** alle 5 Sekunden (Stats, Notifications, Crew-Liste)

### Archiv
- **Globale Archive-Page** über alle Crews mit Crew-Filter
- **Snapshot beim Archivieren** — Boss-Texte aus Info-Channel + Versager-Reply + Reaktions-Antwort werden als JSON gespeichert, bevor sie aus Discord gelöscht werden
- **PDF-Export** pro Mission (reportlab) — Auftragstext, Bild, Boss-Feedback inkl. archivierter Bot-Replies
- **Mass-Purge** mit doppeltem Confirm
- **Restore** und endgültiges Löschen pro Mission

### KI-Konfiguration
- **Anthropic** (Claude) und **OpenAI** als Provider, im UI umschaltbar
- Default `claude-sonnet-4-6`
- **Multiple System-Prompts** — beliebig viele Varianten speicherbar, eine aktivierbar (z.B. „Default kryptisch", „Casual", „Hart-Boiled")
- **API-Keys** in DB oder `.env`, im UI nur als „gesetzt: ja/nein" sichtbar

---

## Tech-Stack

| Schicht | Stack |
|---|---|
| Backend | Python 3.11+/3.14, FastAPI, SQLAlchemy 2 (async), SQLite + aiosqlite |
| Bot | discord.py 2.5+ (eigener Prozess, interne HTTP-API auf `127.0.0.1:8001`) |
| Frontend | Vanilla HTML + Alpine.js + Tailwind (CDN, kein Build) |
| AI | Anthropic SDK + OpenAI SDK |
| PDF | reportlab |
| Auth | HTTP-Basic, lokal auf `127.0.0.1:8000` |
| Service-Mgmt | NSSM (Windows-Services, Auto-Start beim Boot) |

---

## Architektur

```
┌──────────────┐ HTTP-Basic  ┌─────────────────┐
│   Browser    │────────────▶│ FastAPI Backend │
└──────────────┘ :8000       │  (uvicorn)      │
                              └────────┬────────┘
                                       │ httpx
                                       ▼
                              ┌─────────────────┐
                              │   discord.py    │ Discord Gateway
                              │      Bot        │◀──────────────▶ Discord
                              │   (HTTP :8001)  │
                              └─────────────────┘
                                       ▲
                                       │ both processes
                                       ▼
                              ┌─────────────────┐
                              │ SQLite (WAL)    │
                              └─────────────────┘
```

- **Bot ist eigener Prozess** weil Discord-Gateway-Connection persistent sein muss
- **Backend ↔ Bot** Kommunikation: interne HTTP-API (`/send`, `/delete_message`,
  `/delete_in_range`, `/read_channel`)
- **Beide Prozesse** lesen/schreiben dieselbe SQLite (WAL-Mode, low concurrency)
- **API-Keys** nur in DB/`.env`, Frontend bekommt nur `*_set: bool` zurück
- **Server bindet nur auf 127.0.0.1** — kein Port-Forward, lokal-only

### Daten-Modell (SQLite, auto-migriert)
- `crews` — Gangs (Name, Story, Discord-Channel-IDs, Stadtteil, Farbe)
- `crew_relations` — Beziehungen zwischen Gangs (allied / rival / hostile / business / neutral)
- `missions` — Aufträge mit Status, AI-Provider, Image, Discord-Refs, Deadline,
  Schedule, archiviertes Boss-Feedback (JSON), Reply-IDs für Versager und
  Reaktion
- `expiry_messages` — Pool für Versager-Sprüche bei abgelaufener Deadline
- `reaction_messages` — Pool für Reaktions-Antworten nach 👍/👎/❌
- `system_prompts` — KI-System-Prompt-Varianten (eine aktiv)
- `settings` — KV-Store für API-Keys + Default-Modelle

---

## Setup

### Voraussetzungen
- **Python 3.11–3.14** im PATH
- **Discord-Bot-Application** (Token vorhanden)
  - Privileged Intent **„Message Content Intent"** im Developer Portal aktivieren
- **Discord-Bot-Permissions** im Server: Kanäle ansehen, Nachrichten senden, Embed Links,
  Dateien anhängen, Nachrichtenverlauf anzeigen, Reaktionen hinzufügen, Nachrichten verwalten
- **API-Keys** für Claude und/oder OpenAI

### Installation

```bash
git clone https://github.com/RDanton21/CrimeJobs-Handler-Liberty-City.git
cd CrimeJobs-Handler-Liberty-City

# Windows
scripts\setup.bat

# Linux/Mac (manuell)
python -m venv .venv
.venv\Scripts\activate    # Windows
source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
cp .env.example .env
```

### `.env` befüllen

```env
DISCORD_BOT_TOKEN=<dein bot token>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<starkes passwort>

# Optional (kann auch im UI gesetzt werden)
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
```

### Lokal starten

```bash
# Beide Prozesse parallel
scripts\run_all.bat
```

Browser öffnen: <http://127.0.0.1:8000> → Login → Crew anlegen → Mission generieren.

### Als Windows-Service (Auto-Start)

Als Administrator:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_services.ps1
nssm start CrimeAutoBot
nssm start CrimeAutoBackend
```

Logs: `logs\backend.log`, `logs\bot.log`

Status:
```powershell
Get-Service CrimeAutoBot, CrimeAutoBackend
```

Siehe **[DEPLOY.md](DEPLOY.md)** für vollständige Deploy-Doku.

---

## Workflow (UI)

1. **Dashboard** → „+ Neue Gang" mit Name, Discord-Channel-ID, Zusatzinfo-Channel-ID, Stadtteil
2. Auf Crew klicken → **Hintergrund-Story** + **Beziehungen** zu anderen Gangs anlegen
3. Tab **„KI generiert"** → Provider wählen → Generate
   ODER Tab **„Eigenen Text umschreiben"** → Klartext-Roh-Input → KI verschlüsselt im Stil
4. Optional: **Countdown** setzen, **Bild** anhängen, **Zusatzinfos** ergänzen, **Senden um** wählen
5. Draft editieren → **„An Discord senden"** (oder bei gesetztem Schedule: Bot übernimmt)
6. Boss reagiert → Bot postet Reaktions-Antwort → UI zeigt nach max. 5 Sek
7. Boss schreibt im **Zusatzinfo-Channel** Klartext-Antwort → Karte pulsiert auf Dashboard
8. **📦 Archivieren** → Snapshot + Discord-Cleanup → später auf Archive-Page einsehbar oder als PDF exportierbar

---

## Update-Workflow (Solo-Setup)

Auf Dev-PC:
```bash
git add -A && git commit -m "..." && git push
```

Auf Dedicated:
```powershell
cd D:\Crime-Automation
git pull
Restart-Service CrimeAutoBackend, CrimeAutoBot   # als Admin
```

DB-Migrationen laufen automatisch in `backend/db.py` (`init_db()` →
`_migrate_add_column_if_missing`).

---

## Sicherheits-Hinweise

- Backend lauscht **nur auf 127.0.0.1** — nicht von außen erreichbar
- Bot-API ebenfalls **nur auf 127.0.0.1:8001** — nicht von außen erreichbar
- Für Remote-Zugriff: SSH-Tunnel oder Tailscale empfohlen, **kein direktes Port-Forwarding**
- `.env` niemals committen — enthält Bot-Token und API-Keys

---

## Lizenz

Privat-Projekt für RP-Community. Keine offene Lizenz.
