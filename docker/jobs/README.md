# SEKTOR Personal-Börse (Jobs-Dashboard)

Eigenständiger Docker-Service: GTA-RP-Spieler loggen sich mit Discord ein
(nur SEKTOR-Guild-Mitglieder mit der Freischalt-Rolle), sehen das
Event-Board (Zeiträume via `EVENT_PERIODS`, Europe/Berlin) mit allen
Crime-Aufträgen die Personal-Slots haben, und tragen sich selbst
in Slots ein/aus.

- Mehrfachbuchung über **verschiedene** Slots: erlaubt
- Derselbe Slot pro Spieler: nur 1x (DB-Unique-Constraint)
- Slot voll (`assignments >= required_count`): keine weitere Direkt-Buchung —
  stattdessen **Warteliste** (s.u.)
- Alle eingeloggten Spieler sehen, **wer** wo eingetragen ist (gewollt, Koordination)
- **Admin-Kick**: Admins (Admin-Rolle `ADMIN_ROLE_ID` oder User-ID in
  `ADMIN_USER_IDS`) können jeden Spieler per ✕ am Namen aus einem Slot
  austragen (`DELETE /api/admin/assignments/{slot_id}/{player_discord_id}`,
  serverseitig per Session-`is_admin` geprüft)
- **Warteliste mit Auto-Nachrücken**: Bei vollem Slot per Button auf die
  Warteliste (`POST/DELETE /api/slots/{id}/waitlist`, FIFO). Wird ein Platz
  frei (Austragen oder Admin-Kick), rückt der älteste Eintrag automatisch
  nach und bekommt eine Discord-DM.
- **Anwesenheits-Erfassung**: Admins schalten am Namen durch
  offen → ✓ erschienen → ✗ No-Show (`POST /api/admin/attendance/{slot}/{player}`).
  Der Status ist für alle sichtbar (grün/rot) und fließt in die Auswertung
  ein („da" / „No-Show"-Spalten, Sortierung nach tatsächlich Erschienenen).
- **Erinnerungs-DMs**: Hintergrund-Loop schickt `REMINDER_LEAD_MINUTES`
  (Default 30) vor `window_start` jedem Eingetragenen eine DM mit allen
  Einsatz-Details — via Discord-REST-API mit dem Bot-Token (Feature aus,
  wenn `DISCORD_BOT_TOKEN` leer). Dedupe über Tabelle `sent_reminders`,
  überlebt Neustarts; geschlossene DMs werden nicht erneut versucht.

## Architektur

```
Browser (Alpine.js + Tailwind, mobile-first)
   |
   v
Jobs-Dashboard (FastAPI, Port 8080, eigene jobs.db)
   |  Tabellen: players, slot_assignments, waitlist_entries,
   |            completed_participations, sent_reminders, dismissed_missions
   |  Hintergrund: Erinnerungs-Loop (60s) -> Discord-REST-DMs
   |
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
| `EVENT_PERIODS`         | nein    | s. `config.py`                     | Event-Zeiträume: `start~ende[:Label]`, kommagetrennt     |
| `EVENT_START`           | nein    | —                                  | Alt: übersteuert den ersten Zeitraum (ISO, Berlin)       |
| `EVENT_END`             | nein    | —                                  | Alt: übersteuert den ersten Zeitraum (ISO, Berlin)       |
| `JOBS_DB_PATH`          | nein    | `/app/data/jobs.db`                | SQLite-Pfad (im Compose als Volume mounten!)             |
| `COOKIE_SECURE`         | nein    | `1`                                | `0` für lokalen Test ohne HTTPS                          |
| `DISCORD_BOT_TOKEN`     | nein    | —                                  | Bot-Token für Erinnerungs-/Nachrück-DMs (leer = aus)     |
| `REMINDER_LEAD_MINUTES` | nein    | `30`                               | Vorlauf der Erinnerungs-DM vor `window_start`            |
| `ROLE_RECHECK_MINUTES`  | nein    | `10`                               | Rollen-Recheck-Intervall (0 = aus, braucht Bot-Token)    |
| `PUBLIC_URL`            | nein    | `https://jobs.bots.sektorrp.eu`    | Basis-URL der Börse für Links in DMs                     |

## Sicherheit

- **Rollen-Check beim Login + periodischer Recheck**: Die Discord-Rolle
  (`REQUIRED_ROLE_ID`) wird im OAuth-Callback geprüft; der User-Access-Token
  wird danach **bewusst nicht gespeichert**. Ist `DISCORD_BOT_TOKEN` gesetzt,
  prüft `require_session` zusätzlich alle `ROLE_RECHECK_MINUTES` (Default 10)
  die Rollen per Bot-Token neu (`GET /guilds/{gid}/members/{uid}`): Rolle
  entzogen oder Server verlassen → 401, Admin-Rolle entzogen → `is_admin`
  fällt sofort. Discord-Ausfälle sperren niemanden aus (60s-Backoff, letzter
  bekannter Stand gilt). Ohne Bot-Token bleibt das alte Verhalten: Session
  bis zu **7 Tage** gültig; Not-Aus = `JOBS_SESSION_SECRET` rotieren und
  Container neu starten (loggt **alle** Spieler aus).
- **Session-Cookie**: signiert (itsdangerous, `SESSION_SECRET`), `HttpOnly`,
  `Secure` (Default), `SameSite=Lax` (schützt die POST/DELETE-Endpoints vor
  CSRF), Verifikation mit `max_age`. Inhalt nur `discord_user_id`, `username`,
  `avatar`, `is_admin` — keine Tokens, keine Secrets. `is_admin` aus dem
  Cookie wird beim Recheck durch den aktuellen Discord-Stand ersetzt.
- **Admin-Audit-Log**: Kick, Anwesenheits-Bewertung und „Erledigte entfernt"
  landen mit Admin, Ziel, Slot und Zeitstempel in der Tabelle `admin_actions`
  (Einsicht: `GET /api/admin/audit` bzw. „Admin-Protokoll" in der Auswertung).
  Einträge werden nie gelöscht.
- **Statische Dateien**: explizite Allowlist (`_STATIC_FILES` in `main.py`)
  statt eines generischen StaticFiles-Mounts — nur bewusst freigegebene
  Dateien werden ausgeliefert, alles andere ist 404.
- **OAuth-CSRF**: `state` wird als signiertes 5-Minuten-Cookie abgelegt und im
  Callback verglichen; `redirect_uri` kommt ausschließlich aus der Config.
- **Public-API-Key**: Vergleich im Crime-Backend mit `secrets.compare_digest`
  (konstante Laufzeit); der Key taucht in keinem Log und keiner Response auf.
- **Security-Header + strikte CSP**: `X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy` und eine `Content-Security-Policy`
  mit `default-src 'self'` werden per Middleware gesetzt. Möglich, weil alle
  Assets self-hosted sind (kein CDN, **keine Google Fonts** — auch DSGVO-seitig
  sauber): Tailwind vorkompiliert, Alpine + Oswald-Fonts lokal, JS in
  `app.js` statt inline. Ausnahmen: `'unsafe-eval'` (Alpine wertet
  `x-*`-Ausdrücke aus), Style-Attribute inline (`:style`-Bindings),
  `img-src` erlaubt `cdn.discordapp.com` (Avatare).
- **CSV-Export** (`GET /api/admin/export.csv`, Admin-only): Belegung +
  Warteliste aller Aufträge fürs Event-Briefing. Zellen mit führendem
  `=`/`+`/`-`/`@` werden neutralisiert (Excel-Formel-Injektion über
  Discord-Nutzernamen).
- **Proxy**: uvicorn läuft mit `--proxy-headers` hinter Traefik (TLS-Terminierung);
  Port 8080 ist nur im Docker-Netz erreichbar.

## Frontend-Assets bauen

`tailwind.css` ist vorkompiliert (kein CDN). Nach Änderungen an
Tailwind-Klassen in `index.html` oder `app.js` neu bauen:

Die Build-Inputs liegen versioniert unter `assets-src/`
(`input.css` = `@tailwind`-Direktiven + `@font-face` für Oswald +
Custom-Styles; `tailwind.config.js` = Content-Scan über `index.html` + `app.js`):

```bash
curl -sfL -o /tmp/tailwindcss \
  https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.16/tailwindcss-linux-x64
chmod +x /tmp/tailwindcss
cd assets-src
/tmp/tailwindcss -c tailwind.config.js -i input.css -o ../src/static/tailwind.css --minify
```

Die Custom-Styles (Kino-Look, `.headline`, `.card-cine`) und die
`@font-face`-Blöcke stecken mit im kompilierten CSS. `alpine.min.js` ist der
gepinnte unpkg-Snapshot von Alpine 3.14.9; die Oswald-Fonts (Variable Font,
latin + latin-ext) liegen als `oswald-*.woff2` in `src/static/`.

## Tests

```bash
docker run --rm -v "$PWD":/app -w /app python:3.13-slim \
  sh -c "pip install -q -r requirements-dev.txt && python -m pytest -q"
```

Die Suite (`tests/`) testet gegen die echte App (signierte Session-Cookies,
eigene SQLite-DB unter `/tmp`), nur das Crime-Backend und der DM-Versand
sind gefakt. Abgedeckt: Auth/AuthZ, Eintragen/Kapazität, Warteliste inkl.
FIFO-Nachrücken + Überbuchungs-Invariante, Anwesenheit, Audit-Log,
CSV-Export inkl. Formel-Injektion, eigene Bilanz, Event-Perioden-Parser.

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
