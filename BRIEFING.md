# Crime Automation — Projekt-Briefing

> Kontext-Briefing zum schnellen Onboarding (für Claude-Sessions oder neue Mitarbeiter).

## Was es ist
Admin-Tool für GTA-V-Liberty-City-Roleplay (Server-Start September 2026).
KI generiert kryptische, atmosphärische Crime-Aufträge pro Gang, sendet sie über
Discord-Bot „Il Padrino" in Crew-spezifische Channels. Crime-Boss reagiert mit
👍 Erledigt / 👎 Fehlgeschlagen / ❌ nicht ausführbar — Status fließt automatisch
zurück in Admin-Dashboard. Pro Gang sequenzielle Storyline mit Berücksichtigung
der Beziehungen zwischen Gangs.

## Stack
- **Backend**: Python 3.14 / FastAPI / SQLAlchemy 2 (async) / SQLite
- **Bot**: discord.py 2.5+ (separater Prozess, interne HTTP-API auf 127.0.0.1:8001)
- **Frontend**: Vanilla HTML + Alpine.js + Tailwind (CDN, kein Build)
- **AI**: Anthropic (Claude) + OpenAI, im UI umschaltbar, Default `claude-sonnet-4-6`
- **Auth**: HTTP-Basic, lokal auf 127.0.0.1:8000

## Pfade
- **Dev-PC**: `J:\MSC5Projects\Crime-Automation\`
- **Dedicated**: `D:\Crime-Automation\`
- Code: `backend\`, `frontend\`, `scripts\`
- Daten (gitignored): `data\crime.db`, `data\images\`, `logs\`, `.env`, `.venv\`
- Git-Repo: https://github.com/RDanton21/CrimeJobs-Handler-Liberty-City

## Services (NSSM, Auto-Start beim Boot)
- `CrimeAutoBackend` → `uvicorn backend.main:app --host 127.0.0.1 --port 8000`
- `CrimeAutoBot` → `python -m backend.bot` (Discord-Connection + interne HTTP-API :8001)
- Logs: `D:\Crime-Automation\logs\backend.log` / `bot.log` / `*.err.log`
- Status: `Get-Service CrimeAutoBot, CrimeAutoBackend`

## Discord-Bot
- Application „Il Padrino" (Token in `.env` als `DISCORD_BOT_TOKEN`)
- Permissions in Crew-Channels: View Channels, Send Messages, Embed Links,
  Attach Files, Read Message History, Add Reactions, **Manage Messages**
  (für Reaktions-Cleanup + Discord-Message-Delete bei Archiv)
- Reaktions-Emojis: 👍 / 👎 / ❌ — alle anderen werden vom Bot entfernt
- Single-Vote: nach erster Reaktion verschwinden andere Bot-Emojis

## Datenmodell (SQLite)
- `crews` — Gangs (Name, Story, Discord-Channel-ID, Farbe)
- `crew_relations` — Beziehungen (allied/rival/hostile/business/neutral) zwischen Gangs
- `missions` — Aufträge mit Status (draft/pending/approved/rejected/cancelled),
  AI-Provider, Image-Path, Discord-Message-ID, `archived_at` für Soft-Delete
- `settings` — API-Keys + Default-Modelle (Override aus `.env`)

## Workflow
1. Dashboard → „+ Neue Gang" mit Channel-ID
2. Gang-Detail → Beziehungen zu anderen Gangs
3. Tab „KI generiert" → Provider wählen → Generate (Story + Beziehungen + Historie als Kontext)
   ODER Tab „Eigenen Text umschreiben" → Klartext-Roh-Input → KI verschlüsselt im Stil
4. Draft editieren, Bild hochladen
5. „An Discord senden" → Bot postet in Channel + setzt 3 Reaktions-Emojis
6. Boss reagiert → Bot updated DB → UI zeigt nach max 5 Sek (Polling)
7. Lock pro Gang: nächster Auftrag erst nach Reaktion oder Override
8. 📦-Button → Mission ins Archiv + Discord-Message wird gelöscht
9. „Archiv anzeigen" → archivierte Missionen mit Restore (↺) oder Purge (×)

## Deployment-Workflow (Updates)

Auf Dev-PC:
```bash
git add -A && git commit -m "..." && git push
```

Auf Dedicated:
```powershell
cd D:\Crime-Automation
git pull
Restart-Service CrimeAutoBackend, CrimeAutoBot
```

DB-Migrationen laufen automatisch in `backend/db.py` (`init_db()` → `_migrate_add_column_if_missing`).

## Desktop
- Icon „Crime Automation" mit Il-Padrino-Avatar (`frontend\il_padrino.ico`)
- Doppelklick → `scripts\launcher.bat` → Services starten falls down + Browser öffnen

## Wichtige Architektur-Entscheidungen
- Bot **separater Prozess** weil Discord-Gateway-Connection persistent sein muss
- Backend → Bot Kommunikation via interner HTTP-API (`POST /send`, `POST /delete_message`)
- Beide Prozesse lesen/schreiben gleiche SQLite (WAL kompatibel, low concurrency)
- API-Keys nur in DB/`.env`, Frontend bekommt nur `*_set: bool` zurück
- Server bindet **nur 127.0.0.1** — kein Port-Forward, lokal-only
- KI-Prompts in `backend/prompts.py`: kryptisch, deutsch, 3-4 Sätze, Code-Wörter statt
  Klartext, Verzweigung basierend auf letzter Reaktion (👍 Story fortführen,
  👎 Tonart wechseln)
