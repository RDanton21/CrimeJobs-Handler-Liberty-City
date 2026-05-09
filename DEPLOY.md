# Deployment auf Dedicated Server (Windows)

Schritt-für-Schritt zum produktiven Betrieb.

## Voraussetzungen auf Dedicated

- Windows Server (oder Windows 10/11)
- **Python 3.11 oder 3.12** installiert + im PATH (`python --version` muss laufen)
  - Download: https://www.python.org/downloads/ — bei Installation **„Add to PATH"** anhaken
- **NSSM** (für Service-Mode) — https://nssm.cc/download → `nssm.exe` in `C:\Windows\System32\` legen oder PATH erweitern
- Discord-Bot-Application existiert (Token vorhanden)
- API-Keys (Claude und/oder OpenAI)

## Was kopieren — was nicht

**Kopieren** (z.B. via Robocopy, USB-Stick, Remote-Desktop):
```
Crime-Automation\
├── backend\          ← Code
├── frontend\         ← Code
├── scripts\          ← Code
├── .env.example      ← Vorlage
├── .gitignore
├── README.md
├── DEPLOY.md
└── requirements.txt
```

**NICHT kopieren** (oder vorher löschen):
- `.venv\` — wird auf Ziel neu erzeugt
- `data\crime.db` — frische DB auf Ziel (außer du willst Daten migrieren)
- `data\images\*` — leer lassen (außer Migration)
- `.env` — Secrets, separat eintragen

Schnell-Variante mit Robocopy:
```cmd
robocopy J:\MSC5Projects\Crime-Automation \\dedicated\C$\Apps\Crime-Automation /E /XD .venv data\images __pycache__ /XF .env data\crime.db data\crime.db-shm data\crime.db-wal
```

## Auf dem Dedicated

### 1. Erst-Setup

```cmd
cd C:\Apps\Crime-Automation
scripts\setup.bat
```

Legt `.venv` an, installiert alle Deps, kopiert `.env.example` → `.env`.

### 2. .env befüllen

`.env` öffnen und mindestens setzen:
```
DISCORD_BOT_TOKEN=<dein bot token>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<starkes passwort>
```

API-Keys können hier oder später im UI gesetzt werden.

### 3. Smoke-Test

```cmd
scripts\verify.bat
```

Prüft: Python, alle Imports, `.env`, DB-Init. Wenn alles `OK` → weiter.

### 4. Manueller Probelauf

```cmd
scripts\run_all.bat
```

- Bot-Fenster: Connection zu Discord (sollte „Bot ready as ..." zeigen)
- Backend-Fenster: uvicorn auf 127.0.0.1:8000

Browser öffnen → http://127.0.0.1:8000 → Login → Crew anlegen → Mission generieren → Senden testen.

Wenn alles läuft: beide Fenster schließen.

### 5. Als Service einrichten (Auto-Start mit Windows)

Als **Administrator** in PowerShell:
```powershell
cd C:\Apps\Crime-Automation
powershell -ExecutionPolicy Bypass -File scripts\install_services.ps1
nssm start CrimeAutoBot
nssm start CrimeAutoBackend
```

Status prüfen:
```cmd
sc query CrimeAutoBot
sc query CrimeAutoBackend
```

Logs in `logs\backend.log` / `logs\bot.log`.

## Updates später (Code-Änderung deployen)

```cmd
nssm stop CrimeAutoBackend
nssm stop CrimeAutoBot
REM Code-Files überschreiben (NICHT data\, NICHT .env, NICHT .venv)
nssm start CrimeAutoBot
nssm start CrimeAutoBackend
```

Wenn `requirements.txt` geändert wurde:
```cmd
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

## Backup

Nur diese Dateien sichern (Rest ist Code aus Repo):
- `data\crime.db`
- `data\images\*`
- `.env`

Empfehlung: Daily Robocopy-Job auf zweite Disk oder NAS:
```cmd
robocopy C:\Apps\Crime-Automation\data D:\Backups\CrimeAutomation\data /MIR /XD __pycache__
copy C:\Apps\Crime-Automation\.env D:\Backups\CrimeAutomation\.env
```

## Troubleshooting

| Symptom | Lösung |
|---|---|
| `python` nicht erkannt | Python neu installieren mit „Add to PATH" |
| `pip install` schlägt fehl | Visual C++ Build Tools fehlen — install via https://visualstudio.microsoft.com/de/visual-cpp-build-tools/ |
| Bot startet nicht: `Improper token` | Token in `.env` falsch oder leer |
| Backend 503 beim Senden | Bot-Service läuft nicht — `nssm start CrimeAutoBot` |
| 401 im Browser | falscher User/Passwort in `.env` (Browser-Cache leeren oder neuen Inkognito-Tab) |
| Reaktionen werden nicht erfasst | Bot-Permissions auf Discord-Server fehlen (Read Message History, Add Reactions) |
| Bot sieht eigene Reaktionen als User | egal — Code filtert eigene Reaktionen weg |

## Sicherheits-Hinweise

- Server lauscht **nur auf 127.0.0.1** — nicht von außen erreichbar (kein Port-Forward, keine Firewall-Regel nötig)
- Wenn du remote zugreifen willst: SSH-Tunnel oder Tailscale empfohlen, **kein direktes Port-Forwarding**
- `.env` niemals committen, niemals teilen — enthält Bot-Token und API-Keys
