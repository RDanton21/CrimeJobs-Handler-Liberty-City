# 🏗 Architecture

Tech-Architektur, Daten-Modell und Prozess-Kommunikation von Crime Automation.

## Inhalt

1. [System-Übersicht](#system-übersicht)
2. [Prozess-Architektur](#prozess-architektur)
3. [Daten-Modell](#daten-modell)
4. [Backend ↔ Bot Kommunikation](#backend--bot-kommunikation)
5. [KI-Integration](#ki-integration)
6. [Frontend-Architektur](#frontend-architektur)
7. [DB-Migrationen](#db-migrationen)
8. [Sicherheits-Modell](#sicherheits-modell)

## System-Übersicht

```
┌────────────────────────────────────────────────────────────────┐
│                         Browser (Admin)                         │
└────────────────────┬────────────────────────────────────────────┘
                     │ HTTP-Basic Auth
                     ▼
┌─────────────────────────────────────┐
│  Backend (FastAPI + uvicorn)        │
│  Port: 127.0.0.1:8000               │
│  - REST-API für Frontend            │
│  - DB-Zugriff                       │
│  - KI-Provider-Calls                │
└──────┬──────────────────┬───────────┘
       │                  │ httpx
       │                  ▼
       │       ┌────────────────────────┐
       │       │  Discord-Bot           │
       │       │  Port: 127.0.0.1:8001  │
       │       │  - discord.py Gateway  │
       │       │  - Watcher-Loops       │
       │       │  - Bot-HTTP-API        │
       │       └──────────┬─────────────┘
       │                  │
       │                  │ Discord Gateway/REST
       │                  ▼
       │       ┌────────────────────────┐
       │       │   Discord Server       │
       │       │   (Channels, Embeds)   │
       │       └────────────────────────┘
       ▼
┌─────────────────────────────────────┐
│  SQLite (data/crime.db)             │
│  WAL-Mode, beide Prozesse lesen     │
└─────────────────────────────────────┘
       ▲
       │
┌──────┴──────────────────┐
│  Externe KI-Provider    │
│  - Anthropic API        │
│  - OpenAI API           │
└─────────────────────────┘
```

## Prozess-Architektur

### Backend (uvicorn)

- **Async** mit FastAPI + SQLAlchemy 2 async
- **Single Worker** (geringer Concurrency-Bedarf)
- **Bindet auf 127.0.0.1** — kein externer Zugriff
- **HTTP-Basic Auth** für alle `/api/*`-Routen außer `/api/health`
- **Static-Files** unter `/static/*` (Frontend-Assets)
- **HTML-Routes** (`/`, `/crew/{id}`, `/ranking`, `/story`, `/mittler`, ...) liefern direkt HTML-Files

### Bot (discord.py)

- **Eigener Python-Prozess** wegen persistenter Discord-Gateway-Connection
- **aiohttp-Webserver** für Backend ↔ Bot RPC auf `127.0.0.1:8001`
- **Background-Watchers**:
  - **Scheduled-Send-Watcher** (alle 30 s) — sendet Drafts mit fälligem `scheduled_send_at`
  - **Deadline-Watcher** (alle 30 s) — markiert abgelaufene Pending-Missions als REJECTED + postet Versager-Spruch
  - **Boss-Feedback-Watcher** (alle 5 s) — liest Info-Channels aller Crews
  - **Daily-Ranking-Posters** (alle 60 s gepollt) — postet Ranking-Embeds zu konfigurierter Zeit

### Warum zwei Prozesse?

| Grund | Erklärung |
|---|---|
| **Persistente Gateway** | discord.py braucht eine immer-aktive WebSocket — passt nicht zu uvicorn-Reload |
| **Crash-Isolation** | Bot-Disconnect bringt Backend nicht runter, vice versa |
| **Restart-Unabhängigkeit** | Code-Change im Backend braucht kein Bot-Restart |
| **Separate Skalierung** | Bot ist meist idle, Backend hat Bursts |

## Daten-Modell

### Tabellen

#### `crews`

Die Gangs/Crews.

```sql
id              INTEGER PRIMARY KEY
name            VARCHAR(120) UNIQUE
story_background TEXT
crime_business  TEXT
crime_business_channel_id VARCHAR(40)
discord_channel_id        VARCHAR(40)
info_channel_id           VARCHAR(40)
district        VARCHAR(40)
color_hex       VARCHAR(7) DEFAULT '#b91c1c'
bonus_points    INTEGER DEFAULT 0
created_at      DATETIME
```

#### `crew_relations`

Beziehungen zwischen Crews. UNIQUE-Constraint auf (crew_a_id, crew_b_id).

```sql
id              INTEGER PRIMARY KEY
crew_a_id       FK → crews.id (CASCADE)
crew_b_id       FK → crews.id (CASCADE)
relation_type   ENUM (allied, rival, neutral, business, hostile)
notes           TEXT
```

#### `missions`

Aufträge. Das ist die wichtigste Tabelle.

```sql
id              INTEGER PRIMARY KEY
crew_id         FK → crews.id (CASCADE)
ai_provider     VARCHAR(20)
ai_model        VARCHAR(80)
prompt_used     TEXT
content_generated TEXT
content_final   TEXT
image_path      VARCHAR(255)
discord_message_id VARCHAR(40)
discord_channel_id VARCHAR(40)
status          ENUM (PENDING, APPROVED, REJECTED, CANCELLED, DRAFT)
created_at      DATETIME
sent_at         DATETIME
reacted_at      DATETIME
archived_at     DATETIME
deadline_at     DATETIME
scheduled_send_at DATETIME
archived_boss_info TEXT (JSON-Snapshot)
expiry_message_id  VARCHAR(40)
expiry_text     TEXT
reaction_reply_message_id VARCHAR(40)
reaction_reply_text TEXT
personnel_brief TEXT
personnel_updated_at DATETIME
personnel_discord_message_id VARCHAR(40)
```

#### `settings`

KV-Store. Whitelist in `backend/settings_store.py`.

```sql
id              INTEGER PRIMARY KEY
key             VARCHAR(80) UNIQUE
value           TEXT
```

#### `expiry_messages`, `reaction_messages`, `top3_title_pool`

Nachrichtenpools. Gleiches Schema:

```sql
id              INTEGER PRIMARY KEY
text            TEXT
created_at      DATETIME
```

#### `system_prompts`

KI-System-Prompt-Varianten. Genau einer ist `is_active=true`.

```sql
id              INTEGER PRIMARY KEY
name            VARCHAR(120)
text            TEXT
is_active       BOOLEAN
created_at      DATETIME
```

### ER-Diagramm

```
┌─────────┐  1   N  ┌──────────┐
│  crews  ├────────▶│ missions │
└────┬────┘         └──────────┘
     │ N
     │
     │ N
┌────▼──────────┐
│ crew_relations│
└───────────────┘

(weitere Tabellen sind eigenständig)
```

### State-Machine: Mission

```
        ┌──────────────────────────────┐
        │                              │
        ▼                              │
    ┌───────┐  send  ┌────────┐ react  ▼
    │ DRAFT ├───────▶│PENDING ├──────▶ APPROVED
    └───────┘        │        │       ─────────
        │            │        ├──────▶ REJECTED
        │ delete     │        │       ─────────
        │            │        ├──────▶ CANCELLED
        ▼            └────┬───┘
   (purge)                │ deadline
                          ▼
                       REJECTED
                       (auto-expired)
```

Archive-Flag `archived_at IS NOT NULL` ist orthogonal zum Status.

## Backend ↔ Bot Kommunikation

### Backend → Bot (Action-Aufrufe)

| Endpoint | Wofür |
|---|---|
| `POST /send` | Mission an Discord senden |
| `POST /send_embed` | Embed posten (Ranking, Personal) |
| `POST /post_text` | Klartext-Post |
| `POST /delete_message` | Einzelne Message löschen |
| `POST /delete_in_range` | Channel-Cleanup im Zeitfenster |
| `POST /read_channel` | Boss-Feedback abrufen |

Aufrufe per `httpx.AsyncClient` mit 10–60 s Timeout. Bei Bot-Offline → `503` mit defensiver Fortsetzung.

### Bot → DB (direkt)

Der Bot greift **direkt auf die SQLite zu** — nicht über das Backend. Vorteile:
- Weniger Hops bei Watchers
- Kein Backend-Restart bei Bot-Code-Änderungen nötig
- Kein zirkulärer HTTP-Loop

DB-Mode ist **WAL** (Write-Ahead-Logging) — beide Prozesse können parallel lesen, gleichzeitig schreiben.

### Bot → Discord

Über `discord.py` Gateway (WebSocket) und REST-API:
- Channel-Posts
- Reaktionen
- Edit, Delete
- Member-Lookups

## KI-Integration

### Provider-Layer

`backend/ai.py` definiert eine einheitliche Schnittstelle:

```python
class AIProvider:
    name: str
    async def generate(prompt: str, model: str | None = None,
                       system_prompt: str | None = None) -> str: ...
```

Implementationen:
- `AnthropicProvider` — nutzt `anthropic` SDK
- `OpenAIProvider` — nutzt `openai` SDK

Factory: `get_provider(name, keys, models)` liefert den richtigen Provider mit konfigurierten API-Keys.

### Prompt-Building

`backend/prompts.py`:

- `DEFAULT_SYSTEM_PROMPT` — Code-Default
- `build_user_prompt(ctx)` — baut Story + Beziehungen + Historie + Aufgaben-Block
- `build_rewrite_prompt(ctx, raw)` — gleicher Kontext + Klartext-Input

### Personal-AI

`backend/personnel_ai.py`:

- `NPC_POOL_PROMPT_DE` — Mittler + 15 Archetypen hartkodiert
- `PERSONNEL_BRIEF_FORMAT_DE` — Format-Spec für die KI
- `build_personnel_prompt()` — Pool + Format + Mission-Text + Crew-Kontext
- `TEMPLATES` — 6 Massen-Auftrag-Templates

### Quest-Givers-AI

`backend/quest_givers_ai.py`:

- `build_consistency_prompt()` — Story + Mittler + Konsistenz-Check-Aufgabe
- `_extract_recommendations_json()` — 3-Strategie-Parser (XML-Tag / Codefence / nacktes Array)
- `_parse_recommendations_from_bullets()` — Fallback aus „Empfohlene nächste Schritte"
- `build_apply_prompt()` — Edit-Anweisung anwenden

### Auto-Cleaner

`backend/routes_missions.py`:

```python
def _clean_ai_output(text: str) -> str:
    return _digitize_german_numbers(
        _strip_reaction_tail(
            _strip_case_number_prefix(text)
        )
    )
```

Wird auf alle KI-Outputs der Mission-Generierung angewandt.

## Frontend-Architektur

### Stack

- **Vanilla HTML** — keine Frameworks, kein Build-Step
- **Alpine.js** (CDN) für Reactivity
- **Tailwind CSS** (CDN, JIT) für Styling
- **marked.js** (CDN) für Markdown-Rendering + Mini-Fallback im Code

### Datei-Layout

```
frontend/
├── index.html          ← Dashboard
├── crew.html           ← Crew-Detail
├── archive.html        ← Archiv-Übersicht
├── ranking.html        ← Ranking-Tabelle
├── lore.html           ← Lore-Übersicht
├── story.html          ← Story-Editor
├── quest_givers.html   ← Mittler-Tab
├── settings.html       ← Settings
├── app.js              ← Alle Alpine-Factories
├── style.css           ← Custom-Styles (minimal)
└── logo.png            ← Brand-Asset
```

### Page-Routing

Backend liefert HTML direkt für die Page-URLs:
- `/` → `index.html`
- `/crew/{id}` → `crew.html` (id wird per JS aus URL geparst)
- `/ranking` → `ranking.html`
- usw.

### Alpine-Factories

Jede Page hat eine eigene Factory-Funktion in `app.js`:
- `dashboard()` — Hauptseite
- `crewPage()` — Crew-Detail
- `archivePage()` — Archive
- `rankingPage()` — Ranking
- `lorePage()` — Lore
- `storyPage()` — Story-Editor
- `questGiversPage()` — Mittler-Tab
- `settingsPage()` — Settings

Jede Factory liefert ein Objekt mit `init()` und State + Methoden.

### API-Client

Zentraler Helper:

```javascript
const api = {
  get(path),
  send(path, method, body),
  post(path, body),
  put(path, body),
  patch(path, body),
  del(path),
  upload(path, file),
};
```

Auto-Auth via Browser-Basic-Auth (nach Login-Prompt).

### Cache-Bust

Asset-URLs mit Query-Parameter `?v=...` damit Browser-Cache bei Updates umgangen wird.

```html
<script src="/static/app.js?v=mittler6"></script>
```

Bei JS-Änderungen wird der Suffix erhöht (z.B. `v=mittler5` → `v=mittler6`).

## DB-Migrationen

### Automatisch beim Start

`backend/db.py` führt beim Start `init_db()` aus:

1. **`Base.metadata.create_all()`** — erstellt fehlende Tabellen
2. **`_migrate_add_column_if_missing()`** — fügt fehlende Spalten zu bestehenden Tabellen hinzu

Beispiel:
```python
await _migrate_add_column_if_missing(
    conn, "missions", "personnel_brief", "TEXT NOT NULL DEFAULT ''"
)
```

### Warum nicht Alembic?

- **Solo-Setup** mit weniger als 100 MB DB-Größe
- **WAL-Mode** macht alterungs-Operationen safe
- **Schema-Changes selten** und kontrolliert
- **Backups** vor jedem Deploy als Sicherheitsnetz

Bei wachsender Komplexität wäre Alembic eine sinnvolle Migration.

### Backups

DB-Backup empfohlen vor:
- Major-Updates
- Schema-Migration-Tests
- Daten-Bulk-Operationen (z.B. Ranking-Reset)

```powershell
Copy-Item data\crime.db "data\crime.db.bak.$(Get-Date -f yyyyMMdd-HHmm)"
```

## Sicherheits-Modell

### Threat-Model

| Bedrohung | Schutz |
|---|---|
| Unautorisierter API-Zugriff | HTTP-Basic-Auth + `127.0.0.1`-Only-Binding |
| Bot-Token-Leak | `.env` in `.gitignore`, nie im Frontend |
| API-Key-Exposure | Nur in DB/Settings, Frontend bekommt nur `_set: bool` |
| SQL-Injection | SQLAlchemy ORM + Parametrized Queries |
| Path-Traversal | Whitelist-only Story-Files, `Path.resolve()`-Check |
| Discord-Spam | Replace-Previous-Pattern verhindert Spam beim Re-Post |
| AI-Cost-Runaway | Single-Call pro Aktion, kein Retry-Loop |

### Was NICHT geschützt ist

- **Insider-Bedrohung** — wer Admin-Zugriff hat, kann alles
- **DOS auf Backend** — kein Rate-Limiting (lokal-only Setup → akzeptabel)
- **Discord-Bot-Abuse** — wenn Token geleakt: Bot-Permissions reichen für viel Schaden

### Empfohlene Production-Härtung

- **HTTPS-Reverse-Proxy** (caddy/nginx) wenn extern erreichbar
- **VPN/Tailscale** statt Port-Forward für Remote-Admin
- **Tägliche DB-Backups** zu Cloud (encrypted)
- **Bot-Token-Rotation** alle 90 Tage
- **Log-Aggregation** (Grafana Loki o.ä.)

## Performance-Charakteristik

### Backend

- **Request-Latenz**: < 50 ms für DB-Lookups, 2–10 s für KI-Calls
- **Concurrent-Requests**: 50–200 (uvicorn-async)
- **DB-Größe**: ~ 1 KB pro Mission → 1000 Missions = ~ 1 MB

### Bot

- **Channel-Posts**: ~ 200 ms pro Embed
- **Bulk-Send**: parallelisiert mit `asyncio.Semaphore(5)` — 30 Crews in ~ 2 s
- **Boss-Feedback-Polling**: alle 5 s, 1 Channel-Read pro Crew

### KI-Calls

- **Mission-Generate**: 3–8 s (Anthropic Sonnet)
- **Personal-Brief**: 2–5 s
- **Bulk + Personal**: 3–8 s gesamt (1 Mission-Call + 1 Personal-Call)
- **Konsistenz-Check**: 5–15 s (große Context-Window)

## Logging

### Backend

Standard-uvicorn-Log:
```
INFO:     127.0.0.1:51461 - "POST /api/missions/8/rewrite HTTP/1.1" 200 OK
```

Plus eigene `logging`-Calls in Routes für Business-Events.

Pfad: `logs/backend.log` + `logs/backend.err.log`

### Bot

Eigene Logger-Instanz `crime-bot`:
```
2026-06-14 13:14:03 [crime-bot] Bot ready as Il Padrino#4671
2026-06-14 13:14:05 [crime-bot] scheduled mission 42 sent
```

Pfad: `logs/bot.log` + `logs/bot.err.log`

### Discord-Library

discord.py default-loggt auch in `bot.log` + `bot.err.log`.

## Nächste Schritte

- **[API.md](API.md)** — Komplette Endpoint-Referenz
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** — Bei Problemen
