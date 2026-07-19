# 🛠 Troubleshooting

Häufige Probleme + Lösungen für Crime Automation.

## Inhalt

1. [Schnell-Diagnose](#schnell-diagnose)
2. [Setup-Probleme](#setup-probleme)
3. [Discord-Bot](#discord-bot)
4. [KI-Generierung](#ki-generierung)
5. [Personal-Bedarf](#personal-bedarf)
6. [Frontend / Browser](#frontend--browser)
7. [Database](#database)
8. [Logs analysieren](#logs-analysieren)
9. [Service-Restart-Reihenfolge](#service-restart-reihenfolge)

## Schnell-Diagnose

### Ist alles online?

```powershell
# Windows-Services
Get-Service CrimeAutoBackend, CrimeAutoBot

# Beide "Running" erwartet
```

```bash
# Health-Checks
curl http://127.0.0.1:8000/api/health
# {"ok": true}

curl http://127.0.0.1:8001/health
# {"ok": true, "ready": true}
```

### Prozess läuft, aber UI tot?

1. Browser-Cache leeren (**Strg + Shift + R**)
2. DevTools → Console-Tab → JS-Fehler suchen
3. DevTools → Network-Tab → 401/500-Errors finden

### Backend antwortet 500?

Logs prüfen:
```powershell
Get-Content logs\backend.err.log -Tail 50
```

Häufigste Ursache: fehlendes Settings-Mapping (siehe [Setup-Probleme](#setup-probleme)).

## Setup-Probleme

### `pip install -r requirements.txt` schlägt fehl

**Symptom:** Dependency-Konflikt, „failed building wheel"

**Lösung:**
```bash
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

Bei Python 3.14 manche Packages noch nicht stabil — auf 3.12 oder 3.13 downgraden.

### `ImportError: No module named backend`

**Symptom:** `python -m uvicorn backend.main:app` findet das Modul nicht

**Lösung:** Du bist im falschen Verzeichnis. Cd ins Projekt-Root (wo `backend/` liegt):
```bash
cd D:\Crime-Automation
.venv\Scripts\activate
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

### `.env`-Werte werden ignoriert

**Symptom:** Tool startet, aber Bot-Token wird nicht gefunden

**Lösungen:**
- `.env` im Projekt-Root, nicht in `backend/`
- Keine Anführungszeichen um Werte (`KEY=value`, nicht `KEY="value"`)
- Service-Restart nach Änderung

### NSSM-Services starten nicht

```powershell
nssm get CrimeAutoBackend AppDirectory
nssm get CrimeAutoBackend Application
nssm get CrimeAutoBackend AppParameters
```

Erwartung:
- `AppDirectory`: dein Projekt-Root
- `Application`: Pfad zu `python.exe` in `.venv\Scripts\`
- `AppParameters`: `-m uvicorn backend.main:app --host 127.0.0.1 --port 8000`

Fix:
```powershell
nssm set CrimeAutoBackend AppDirectory "D:\Crime-Automation"
nssm set CrimeAutoBackend Application "D:\Crime-Automation\.venv\Scripts\python.exe"
nssm set CrimeAutoBackend AppParameters "-m uvicorn backend.main:app --host 127.0.0.1 --port 8000"
nssm restart CrimeAutoBackend
```

### Settings: `500 Internal Server Error` beim Speichern

**Symptom:** Fehler bei `PATCH /api/settings` mit neuem Settings-Key

**Ursache:** `mapping`-Dict im `routes_settings.py` kennt das Feld nicht (war ein Bug)

**Lösung:** seit v2.0 defensiv — unbekannte Keys werden übersprungen. Bei älteren Versionen:
1. `backend/settings_store.py` → Key in `KEYS`-Set hinzufügen
2. `backend/schemas.py` → `SettingsUpdate` erweitern
3. `backend/routes_settings.py` → `mapping`-Dict erweitern
4. `Restart-Service CrimeAutoBackend`

## Discord-Bot

> 💡 **Bei jedem Bot-Setup-Problem**: prüfe die idiotensichere Anleitung **[DISCORD_BOT_SETUP.md](DISCORD_BOT_SETUP.md)** — die deckt 90% der Probleme ab.

### Bot ist offline

```bash
curl http://127.0.0.1:8001/health
```

Wenn keine Antwort → Bot-Prozess nicht aktiv:
```powershell
Get-Service CrimeAutoBot
Start-Service CrimeAutoBot
```

### Bot „ready=false" im Health-Check

Bot ist gestartet, aber noch nicht verbunden. Häufige Ursachen:
- **Ungültiger Token** → Logs prüfen (`logs/bot.err.log`)
- **Intent nicht aktiviert** im Developer Portal (Message Content Intent!)
- **Discord-API down** → <https://discordstatus.com>

Logs:
```powershell
Get-Content logs\bot.err.log -Tail 30
```

Erwartetes Log bei Erfolg:
```
2026-06-14 13:00:00 [crime-bot] Bot HTTP API auf http://127.0.0.1:8001
2026-06-14 13:00:01 [crime-bot] Bot ready as Il Padrino#4671 (id=...)
```

### Bot postet keine Aufträge

**Diagnose:**
1. Im Backend-Log: `POST /send` zum Bot wurde gemacht?
   ```powershell
   Select-String -Path logs\bot.err.log -Pattern "POST /send"
   ```
2. Im Bot-Log: Erfolg/Fehler?
   ```powershell
   Select-String -Path logs\bot.log -Pattern "mission.*sent|send failed"
   ```

**Häufige Ursachen:**
- **Channel-Permission fehlt** → in Discord: Server-Settings → Rollen → Bot-Rolle prüfen
- **Falsche Channel-ID** → Rechtsklick auf Channel in Discord → ID kopieren (Entwicklermodus aktiv?)
- **Bot nicht im Server** → erneut über OAuth2-URL einladen

### Reaktionen funktionieren nicht

**Symptom:** Bot setzt 👍/👎/❌, aber User-Reaktionen ändern den Status nicht

**Diagnose:**
- Hat der Bot **Read Message History**-Permission? Sonst sieht er keine Reaktion-Events
- Wird die Reaktion vom **richtigen User** gemacht? Aktuell akzeptiert der Bot jeden Boss-User — falls du auf bestimmte User filtern willst, in `bot.py` anpassen

### Auto-Post Personal-Bedarf landet nicht im Channel

**Diagnose:**
1. Channel-ID in Settings gesetzt? → `Settings → 🎭 Personal-Bedarf — Admin-Channel`
2. Bot hat **Embed Links + Send Messages** im Admin-Channel?
3. `personnel_brief` der Mission ist nicht leer?
4. Bot-Log:
   ```powershell
   Select-String -Path logs\bot.log -Pattern "personnel-auto-post"
   ```

## KI-Generierung

### `502 AI-Provider Fehler`

**Symptom:** KI-Generate schlägt mit 502 fehl

**Diagnose:**
- API-Key korrekt? → Settings → 🤖 KI-Konfiguration
- API-Key in `.env` UND in DB? → DB hat Vorrang (überschreibt `.env`)
- Quota beim Provider erschöpft?
  - Anthropic: <https://console.anthropic.com> → Usage
  - OpenAI: <https://platform.openai.com/usage>

### KI generiert immer das Gleiche

**Symptom:** Aufträge wiederholen sich, wenig Variation

**Ursachen + Fixes:**
- **Hintergrund-Story zu kurz** → KI hat zu wenig Kontext, mehr Details schreiben
- **Keine Beziehungen** → KI nutzt nichts als Story-Hook → 2–3 Beziehungen anlegen
- **Letzte Missions identisch** → KI verzweigt nicht → in 3+ Missions abwechselnd 👍/👎 reagieren

### Aktennummern erscheinen wieder am Anfang

**Symptom:** „Vorgang 091-23." steht am Anfang trotz Cleaner

**Fix:**
1. Backend neugestartet? → `Restart-Service CrimeAutoBackend`
2. Mission war **vor dem Restart** generiert → **🔁 Umformulieren** klicken (neuer Lauf durchläuft den Cleaner)
3. Pattern verschärfen in `backend/routes_missions.py` → `_CASE_NUMBER_PREFIX_RE`

### „👍 oder 👎." erscheint am Ende

Analog zu Aktennummer — Restart prüfen + Umformulieren. Pattern: `_REACTION_TAIL_RE`.

### Zahlen werden ausgeschrieben (statt Ziffern)

**Symptom:** „acht Minuten" statt „8 Minuten"

**Fix:**
1. Backend neugestartet?
2. Custom-System-Prompt aktiv? → Settings → System-Prompts → falls eigener Prompt aktiv ist, Regel ergänzen
3. Mini-Cleaner in `backend/routes_missions.py` → `_NUM_WORDS` Map erweitern, falls Wort fehlt

### KI nutzt Uhrzeiten außerhalb 17:00–02:00

**Fix:**
- Default-System-Prompt enthält die Regel — bei Custom-Prompts muss sie ergänzt werden
- Bei wiederholten Verstößen: KI-Modell wechseln (Sonnet > Opus für Strikt-Befolgung)

## Personal-Bedarf

### Widget zeigt nichts

**Diagnose:**
1. **Filter prüfen** → „Alle aktiven" gewählt? Bei `24h`-Filter siehst du nur Missions im 24-h-Fenster
2. **Sind aktive Missions vorhanden?** → DB hat `archived_at IS NULL`?
3. **Backend-Endpoint testen:**
   ```bash
   curl -u admin:pw "http://127.0.0.1:8000/api/dashboard/personnel?mode=active"
   ```

### Personal-Brief leer trotz KI

**Ursachen:**
- **API-Key fehlt** → KI-Call schlägt defensiv fehl, brief bleibt leer
- **Mission via `/manual` erstellt vor v2.0** → Hook war damals noch nicht eingebaut
- **KI-Call hängt** → Bot-Log checken

**Fix manuell:**
- Im Widget: **✎ bearbeiten** → **🤖 KI-Vorschlag** → speichern

### Mittler-Konsistenz-Check ohne Apply-Buttons

**Symptom:** Report kommt, aber keine 🤖-Buttons

**Diagnose:** Hat die KI Recommendations geliefert?
1. **F12** → **Network**-Tab → POST `consistency-check`
2. **Response**-Tab → `"recommendations": [...]` füllt sich?

Wenn leer (`[]`):
- Backend neugestartet nach dem v2.0-Update mit Bullet-Fallback?
- Falls ja: Im Report selbst „## Empfohlene nächste Schritte"-Sektion vorhanden? Falls nein, hat die KI nichts vorgeschlagen.

## Frontend / Browser

### Buttons reagieren nicht / `function not defined`

**Symptom:** Klick auf Button bewirkt nichts, in Console steht „X is not defined"

**Ursache:** Alter JS-Code im Cache.

**Fix:**
1. **Strg + Shift + R** (Hard-Reload)
2. **F12** → Network-Tab → Häkchen **„Disable cache"** → Seite neu laden
3. Wenn immer noch: **Strg + Shift + Entf** → Cookies/Site-Daten für `localhost:8000` löschen

### Markdown wird raw angezeigt (monospace, sichtbare `##`)

**Symptom:** Mittler-Tab oder Konsistenz-Check zeigt rohes Markdown

**Ursachen:**
- **marked.js CDN nicht geladen** → Frontend nutzt Fallback-Renderer (sieht ähnlich aus, aber weniger features)
- **KI hat in ```markdown ... ``` gewrappt** → Bot ab v2.0 strippt das automatisch, sonst Backend-Restart

### Modal/Dialog zu klein

Im **Mittler-Tab → Konsistenz-Check → 🤖 Anwenden** das Preview-Modal sollte fast Fullscreen sein.

Falls klein:
- Browser-Tab-Fenster groß genug (1024 px+)?
- Cache-Bust geprüft? URL des `app.js` sollte `?v=mittler6` oder höher haben

### Login-Prompt kommt wiederholt

**Ursache:** Browser akzeptiert die Basic-Auth-Credentials nicht persistent

**Fix:** Beim ersten Login das Passwort speichern lassen. Falls Edge/Chrome das blockiert: in Einstellungen → Passwörter → manuell für `127.0.0.1` hinzufügen.

## Database

### „database is locked"

**Symptom:** SQLite-Fehler bei Schreib-Operationen

**Ursache:** Zwei Prozesse versuchen gleichzeitig zu schreiben

**Fix:**
1. WAL-Mode prüfen:
   ```python
   import sqlite3
   conn = sqlite3.connect("data/crime.db")
   print(conn.execute("PRAGMA journal_mode").fetchone())  # sollte ('wal',) sein
   ```
2. Falls nicht WAL:
   ```sql
   PRAGMA journal_mode=WAL;
   ```

### DB-Schema veraltet nach Update

**Symptom:** Fehler wie „no such column: personnel_brief"

**Fix:** Backend-Restart triggert Auto-Migration:
```powershell
Restart-Service CrimeAutoBackend
```

Wenn das nicht reicht: manuell in `backend/db.py` die Migration prüfen. Im Notfall:
```bash
# DB-Backup machen
copy data\crime.db data\crime.db.bak

# Spalte manuell hinzufügen
sqlite3 data\crime.db "ALTER TABLE missions ADD COLUMN personnel_brief TEXT NOT NULL DEFAULT ''"
```

### DB-Backup

Vor Major-Updates oder Bulk-Operationen:
```powershell
Copy-Item data\crime.db "data\crime.db.bak.$(Get-Date -f yyyyMMdd-HHmm)"
```

### Restore aus Backup

```powershell
Stop-Service CrimeAutoBackend, CrimeAutoBot
Copy-Item data\crime.db.bak.20260814 data\crime.db -Force
Start-Service CrimeAutoBot, CrimeAutoBackend
```

## Logs analysieren

### Live-View

```powershell
# Backend
Get-Content logs\backend.log -Wait -Tail 30

# Bot
Get-Content logs\bot.log -Wait -Tail 30
```

### Suche nach Pattern

```powershell
# Alle 500er Fehler
Select-String -Path logs\backend.err.log -Pattern "Internal Server Error"

# Alle KI-Provider-Fehler
Select-String -Path logs\backend.err.log -Pattern "AI-Provider Fehler"

# Alle Mission-Sends im Bot
Select-String -Path logs\bot.log -Pattern "sent|send failed"
```

### Häufige Log-Indikatoren

| Pattern | Bedeutung |
|---|---|
| `INFO: 127.0.0.1:xxxxx - "POST /api/..." 200 OK` | Normaler Request |
| `INFO: 127.0.0.1:xxxxx - "POST /api/..." 500` | Backend-Crash → err.log prüfen |
| `Bot ready as Il Padrino` | Bot online (Bot-Log) |
| `scheduled mission X sent` | Schedule-Send erfolgreich |
| `personnel-auto-post: ...` | Personal-Auto-Post Aktion |
| `auto-post personnel failed` | Personal-Post fehlgeschlagen (defensive Fortsetzung) |

## Service-Restart-Reihenfolge

### Bei Backend-Code-Änderung

```powershell
Restart-Service CrimeAutoBackend
```

Bot muss nicht restartet werden.

### Bei Bot-Code-Änderung

```powershell
Restart-Service CrimeAutoBot
```

Backend muss nicht restartet werden.

### Bei DB-Schema-Änderung

Beide neu starten, Backend zuerst (führt Migration durch):
```powershell
Restart-Service CrimeAutoBackend
Start-Sleep -Seconds 3
Restart-Service CrimeAutoBot
```

### Bei `.env`-Änderung

Beide neu starten:
```powershell
Restart-Service CrimeAutoBackend, CrimeAutoBot
```

### Bei Frontend-Änderung

Kein Service-Restart nötig. **Strg + F5** im Browser reicht (oder Cache-Bust-Suffix erhöhen).

## Notfall-Recovery

### Tool komplett wiederherstellen

```powershell
# 1. Services stoppen
Stop-Service CrimeAutoBackend, CrimeAutoBot

# 2. DB-Backup wiederherstellen
Copy-Item data\crime.db.bak.LATEST data\crime.db -Force

# 3. Git auf letzten stabilen Stand
cd D:\Crime-Automation
git fetch
git reset --hard origin/main

# 4. Dependencies sicher installiert?
.venv\Scripts\activate
pip install -r requirements.txt

# 5. Services starten
Start-Service CrimeAutoBackend
Start-Sleep -Seconds 5
Start-Service CrimeAutoBot
```

### Bot-Token kompromittiert

1. **Sofort**: Discord Developer Portal → App → Bot → **Reset Token**
2. Neuer Token in `.env` eintragen
3. `Restart-Service CrimeAutoBot`
4. Bot-Permissions im Server prüfen (falls Angreifer Channels manipuliert hat)
5. Audit-Log in Discord prüfen für verdächtige Aktionen

### Wenn nichts mehr geht: Kontakt

- **GitHub-Issue**: <https://github.com/RDanton21/CrimeJobs-Handler-Liberty-City/issues>
- **Discord-Community**: über RP-Server-Owner

## Nächste Schritte

- **[INSTALLATION.md](INSTALLATION.md)** — bei Neuinstallation
- **[CONFIGURATION.md](CONFIGURATION.md)** — bei Settings-Problemen
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — bei tiefgreifenden Problemen
