# SEKTOR Personal-Börse (Jobs-Dashboard)

Eigenständiger Docker-Service: GTA-RP-Spieler loggen sich mit Discord ein
(nur SEKTOR-Guild-Mitglieder mit der Freischalt-Rolle), sehen das
10-Tage-Event-Board (07.08.2026 18:00 – 16.08.2026 23:50, Europe/Berlin)
mit allen Crime-Aufträgen die Personal-Slots haben, und tragen sich selbst
in Slots ein/aus.

- Mehrfachbuchung über **verschiedene** Slots: erlaubt
- Derselbe Slot pro Spieler: nur 1x (DB-Unique-Constraint)
- Slot voll (`assignments >= required_count`): keine weitere Buchung
- Alle eingeloggten Spieler sehen, **wer** wo eingetragen ist (gewollt, Koordination)
- **Admin-Kick**: Admins (Admin-Rolle `ADMIN_ROLE_ID` oder User-ID in
  `ADMIN_USER_IDS`) können jeden Spieler per ✕ am Namen aus einem Slot
  austragen (`DELETE /api/admin/assignments/{slot_id}/{player_discord_id}`,
  serverseitig per Session-`is_admin` geprüft)

## Architektur

```
Browser (Alpine.js + Tailwind, mobile-first)
   |
   v
Jobs-Dashboard (FastAPI, Port 8080, eigene jobs.db: players + slot_assignments)
   |  GET /api/public/active-missions + /api/public/crews
   |  Header: X-API-Key = CRIME_API_KEY  (15s In-Memory-Cache)
   v
Crime-Backend (Il Padrino, Public-API mit JOBS_API_KEY)
```

## Discord-App einrichten (Il Padrino)

1. [Discord Developer Portal](https://discord.com/developers/applications) →
   Application **Il Padrino** öffnen
2. **OAuth2 → General → Redirects** hinzufügen:
   - Produktion: `https://<jobs-domain>/auth/callback`
   - Lokaler Test: `http://localhost:8090/auth/callback`
3. `CLIENT ID` und `CLIENT SECRET` von derselben Seite in die Env-Vars übernehmen
4. Genutzte OAuth2-Scopes: `identify` + `guilds.members.read` (kein Bot-Scope nötig)

## Env-Vars

| Variable                | Pflicht | Default                            | Beschreibung                                             |
| ----------------------- | ------- | ---------------------------------- | -------------------------------------------------------- |
| `DISCORD_CLIENT_ID`     | ja      | —                                  | OAuth2 Client-ID der Discord-App                         |
| `DISCORD_CLIENT_SECRET` | ja      | —                                  | OAuth2 Client-Secret                                     |
| `DISCORD_REDIRECT_URI`  | ja      | —                                  | Muss **exakt** einem Redirect im Dev-Portal entsprechen  |
| `DISCORD_GUILD_ID`      | ja      | —                                  | SEKTOR-Guild, in der die Rolle geprüft wird              |
| `REQUIRED_ROLE_ID`      | ja      | —                                  | Rollen-ID, die zum Login berechtigt                      |
| `ADMIN_ROLE_ID`         | nein    | `1431562679545364582`              | Rollen-ID: darf fremde Spieler aus Slots austragen       |
| `ADMIN_USER_IDS`        | nein    | `584086760284487697`               | Zusätzliche Admin-User-IDs (kommagetrennt)               |
| `SESSION_SECRET`        | ja      | —                                  | Zufälliger String (z.B. `openssl rand -hex 32`)          |
| `CRIME_BACKEND_URL`     | ja      | `http://sekt6r-crime-backend:8000` | Basis-URL des Crime-Backends (Container-Name im Netz)    |
| `CRIME_API_KEY`         | ja      | —                                  | Gleicher Wert wie `JOBS_API_KEY` im Crime-Backend        |
| `EVENT_START`           | nein    | `2026-08-07T18:00`                 | Event-Beginn (ISO, Europe/Berlin)                        |
| `EVENT_END`             | nein    | `2026-08-16T23:50`                 | Event-Ende (ISO, Europe/Berlin)                          |
| `JOBS_DB_PATH`          | nein    | `/app/data/jobs.db`                | SQLite-Pfad (im Compose als Volume mounten!)             |
| `COOKIE_SECURE`         | nein    | `1`                                | `0` für lokalen Test ohne HTTPS                          |

## Sicherheit

- **Rollen-Check nur beim Login**: Die Discord-Rolle (`REQUIRED_ROLE_ID`) wird
  ausschließlich im OAuth-Callback geprüft. Der User-Access-Token wird danach
  **bewusst nicht gespeichert** — ein erneuter Rollen-Check während der Session
  ist damit technisch nicht möglich. Konsequenz: Wird einem Spieler die Rolle
  entzogen, bleibt seine bestehende Session bis zu **7 Tage** (Cookie-Max-Age)
  gültig. Akzeptiertes Risiko für ein Event-Board; wer alle Sessions sofort
  invalidieren will, rotiert `JOBS_SESSION_SECRET` und startet den Container
  neu (loggt **alle** Spieler aus).
- **Session-Cookie**: signiert (itsdangerous, `SESSION_SECRET`), `HttpOnly`,
  `Secure` (Default), `SameSite=Lax` (schützt die POST/DELETE-Endpoints vor
  CSRF), Verifikation mit `max_age`. Inhalt nur `discord_user_id`, `username`,
  `avatar`, `is_admin` — keine Tokens, keine Secrets. `is_admin` wird (wie der
  Rollen-Check) nur beim Login ermittelt und gilt für die Session-Laufzeit.
- **Statische Dateien**: bewusst nur Einzeldatei-Endpoints (`/`, `/static/bg.jpg`
  mit `Cache-Control: public, max-age=86400`) statt eines generischen
  StaticFiles-Mounts.
- **OAuth-CSRF**: `state` wird als signiertes 5-Minuten-Cookie abgelegt und im
  Callback verglichen; `redirect_uri` kommt ausschließlich aus der Config.
- **Public-API-Key**: Vergleich im Crime-Backend mit `secrets.compare_digest`
  (konstante Laufzeit); der Key taucht in keinem Log und keiner Response auf.
- **Security-Header**: `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy` werden per Middleware gesetzt. Eine strikte CSP ist erst
  möglich, wenn Tailwind/Alpine nicht mehr per CDN geladen werden (beide
  brauchen aktuell `eval`/Inline); CDN-Versionen sind deshalb fest gepinnt.
- **Proxy**: uvicorn läuft mit `--proxy-headers` hinter Traefik (TLS-Terminierung);
  Port 8080 ist nur im Docker-Netz erreichbar.

## Lokaler Test (ohne Docker, Windows)

```powershell
cd D:\Crime-Automation\docker\jobs
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

$env:DISCORD_CLIENT_ID = "..."
$env:DISCORD_CLIENT_SECRET = "..."
$env:DISCORD_REDIRECT_URI = "http://localhost:8090/auth/callback"
$env:DISCORD_GUILD_ID = "..."
$env:REQUIRED_ROLE_ID = "..."
$env:SESSION_SECRET = "nur-fuer-lokalen-test"
$env:CRIME_BACKEND_URL = "http://localhost:8000"   # lokales Crime-Backend
$env:CRIME_API_KEY = "..."                          # = JOBS_API_KEY im Backend
$env:JOBS_DB_PATH = "./data/jobs.db"
$env:COOKIE_SECURE = "0"                            # http://localhost

.venv\Scripts\uvicorn src.main:app --port 8090
```

Danach: <http://localhost:8090> → "Mit Discord anmelden".
Wichtig: Der localhost-Redirect muss im Dev-Portal eingetragen sein (s.o.).

## Docker-Deploy

Der Service wird über die zentrale `docker/docker-compose.yml` deployed
(Traefik-Labels, Netzwerke, Volume für `/app/data`) — siehe dort.
Build-Context ist dieses Verzeichnis (`docker/jobs/`), Port im Container: `8080`.

Wichtig für die Compose-Definition:

- Volume auf `/app/data` mounten, sonst ist `jobs.db` nach jedem Rebuild leer
- `CRIME_API_KEY` (hier) und `JOBS_API_KEY` (Crime-Backend) müssen identisch sein
- Ohne gesetzten `JOBS_API_KEY` antwortet das Crime-Backend mit 503 →
  das Board zeigt "Crime-Backend antwortet mit Fehler"

## Deployment auf dem VPS

1. **Cloudflare-DNS**: CNAME `jobs.bots` → `bots.sektorrp.eu`, Proxy-Status
   **"Nur DNS"** (graue Wolke) — TLS macht der Traefik auf dem VPS selbst
   (Cert-Resolver `letsencrypt`).
2. **Discord Dev-Portal**: Redirect `https://jobs.bots.sektorrp.eu/auth/callback`
   bei der App "Il Padrino" eintragen (siehe oben).
3. **`.env` auf dem VPS ergänzen** (Vorlage: `docker/.env.example`, Block
   "Jobs-Dashboard"): `JOBS_DISCORD_CLIENT_ID`, `JOBS_DISCORD_CLIENT_SECRET`,
   `JOBS_SESSION_SECRET`, `JOBS_API_KEY` (+ optionale Overrides wie
   `JOBS_REQUIRED_ROLE_ID`).
4. **Build + Start** (crime-backend mit neu starten, damit `JOBS_API_KEY`
   dort ankommt):

   ```bash
   cd <stack-verzeichnis>/docker
   docker compose up -d --build jobs-dashboard crime-backend
   ```

5. **Log-Check**:

   ```bash
   docker logs -f sekt6r-jobs
   docker logs sekt6r-crime-backend --tail 50
   ```

   Danach `https://jobs.bots.sektorrp.eu` aufrufen → Login-Card muss erscheinen;
   nach dem Login darf das Board keinen "Crime-Backend antwortet mit Fehler"
   zeigen (sonst `JOBS_API_KEY`/`CRIME_BACKEND_URL` prüfen).

## Dedicated (Übergangsphase)

Das Crime-Backend läuft aktuell noch NATIV auf dem Dedicated Server
(NSSM-Service `CrimeAutoBackend`, Port 8000) und NICHT im Docker-Stack auf
dem VPS. Solange das so ist, gilt zusätzlich:

1. `JOBS_API_KEY=...` auch in `D:\Crime-Automation\.env` auf dem **Dedicated**
   setzen (exakt derselbe Wert wie im VPS-`.env`), sonst antwortet die
   Public-API mit 503.
2. `CrimeAutoBackend` in einer **Admin**-PowerShell neu starten — ohne
   Admin-Rechte scheitert der Restart still:

   ```powershell
   Restart-Service CrimeAutoBackend
   ```

3. `JOBS_CRIME_BACKEND_URL` im VPS-`.env` auf eine **vom VPS erreichbare** URL
   des Dedicated setzen — der Compose-Default
   `http://sekt6r-crime-backend:8000` funktioniert nur, wenn das Backend als
   Container im selben Docker-Netz läuft. Das heißt: Port 8000 des Dedicated
   für die VPS-IP freigeben (Firewall!) oder einen Tunnel/Reverse-Proxy
   davorschalten. Das Backend ungeschützt ins Internet zu stellen ist keine
   Option.

**Einfachste Option:** Den Test des Jobs-Dashboards erst NACH der
Docker-Migration des Crime-Backends auf den VPS machen — dann greift der
Compose-Default (`http://sekt6r-crime-backend:8000`), und die Schritte 1–3
oben entfallen komplett. Bis dahin kann der Service trotzdem schon deployed
werden (Login funktioniert, das Board meldet nur einen Backend-Fehler).
