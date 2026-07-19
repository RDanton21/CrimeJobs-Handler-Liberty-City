# ⚙️ Configuration

Alle Konfigurationsoptionen, Settings und Channels von Crime Automation. Settings werden in der DB gespeichert und sind im Web-UI editierbar.

## Inhalt

1. [Konfigurations-Ebenen](#konfigurations-ebenen)
2. [Discord-Bot einrichten](#discord-bot-einrichten)
3. [KI-Provider konfigurieren](#ki-provider-konfigurieren)
4. [Discord-Channels](#discord-channels)
5. [Ranking-Posts (täglich)](#ranking-posts-täglich)
6. [Personal-Bedarf Admin-Channel](#personal-bedarf-admin-channel)
7. [System-Prompts verwalten](#system-prompts-verwalten)
8. [Nachrichtenpools](#nachrichtenpools)

## Konfigurations-Ebenen

Crime Automation hat drei Konfigurations-Ebenen:

| Ebene | Wofür | Wie ändern |
|---|---|---|
| **`.env`** | Bootstrap-Werte (Bot-Token, Admin-Login, API-Keys) | Datei editieren + Service-Restart |
| **DB-Settings** | Laufzeit-Settings (Channels, Zeiten, Defaults) | Web-UI unter `/settings` |
| **Story-Files** | Markdown-Dokumente (Briefings, Quest-Geber) | Story-Editor unter `/story` |

## Discord-Bot einrichten

> 💡 **Komplette idiotensichere Anleitung:** **[DISCORD_BOT_SETUP.md](DISCORD_BOT_SETUP.md)** — Schritt-für-Schritt mit allen Details, häufigen Fehlern und Notfall-Recovery.

Kurzform für erfahrene Nutzer:

### Bot-Token in `.env`

```env
DISCORD_BOT_TOKEN=MTAwM...your...token...here
```

### Benötigte Intents im Developer Portal

- ✅ **Message Content Intent** — für Boss-Feedback-Polling im Zusatzinfo-Channel
- ✅ **Server Members Intent** — optional, für User-Info bei Boss-Feedback-Attribution

### Bot-Permissions im Server

| Permission | Wofür |
|---|---|
| View Channels | Posts und Lesen |
| Send Messages | Aufträge senden |
| Embed Links | Embeds für Aufträge + Ranking |
| Attach Files | Bilder zu Aufträgen |
| Read Message History | Boss-Feedback-Backlog lesen |
| Add Reactions | 👍 / 👎 / ❌ initial setzen |
| Manage Messages | Reaktions-Cleanup (Single-Vote-Enforcement) |

## KI-Provider konfigurieren

### Anthropic Claude (empfohlen)

In `.env`:
```env
ANTHROPIC_API_KEY=sk-ant-api03-...
DEFAULT_AI_PROVIDER=anthropic
DEFAULT_CLAUDE_MODEL=claude-sonnet-4-5-20250929
```

Oder im Web-UI: **Settings** → **🤖 KI-Konfiguration** → API-Key eintragen + Speichern.

**Empfohlene Modelle:**
- `claude-sonnet-4-5-20250929` — Beste Balance Qualität/Preis
- `claude-opus-4-20250514` — Höchste Qualität, langsamer & teurer
- `claude-haiku-4-20250514` — Schnell und günstig, einfachere Texte

### OpenAI

In `.env`:
```env
OPENAI_API_KEY=sk-...
DEFAULT_OPENAI_MODEL=gpt-4o
```

**Empfohlene Modelle:**
- `gpt-4o` — Standard für hohe Qualität
- `gpt-4o-mini` — Schnell und günstig
- `gpt-4-turbo` — Stabil, etwas langsamer

### Provider-Umschaltung pro Mission

Im Crew-Detail beim Auftrag-Erstellen: Dropdown **„Provider"** mit `Anthropic` / `OpenAI`. Override pro Mission möglich.

### Kosten-Einschätzung

| Provider | Modell | Pro Auftrag (typisch) | 100 Aufträge/Monat |
|---|---|---|---|
| Anthropic | Sonnet 4.5 | ~ 0,015 USD | ~ 1,50 USD |
| Anthropic | Opus 4 | ~ 0,06 USD | ~ 6,00 USD |
| OpenAI | GPT-4o | ~ 0,02 USD | ~ 2,00 USD |
| OpenAI | GPT-4o-mini | ~ 0,002 USD | ~ 0,20 USD |

Personal-Bedarf-Generierung läuft als zusätzlicher KI-Call → effektive Kosten verdoppeln sich.

## Discord-Channels

### Pro Crew (im Crew-Detail einstellen)

| Feld | Wofür | Pflicht? |
|---|---|---|
| `discord_channel_id` | Auftrags-Channel — Bot postet hier Aufträge | ✅ Ja |
| `info_channel_id` | Zusatzinfo-Channel — Boss-Klartext-Antworten | Optional |
| `crime_business_channel_id` | Crime-Business-Briefings (separater Workflow) | Optional |

### Globale Channels (in Settings)

| Setting-Key | Wofür |
|---|---|
| `ranking_daily_channel_id` | Tägliches Ranking-Embed (Gesamt) |
| `ranking_top3_channel_id` | Tägliches Top-3-Hype-Embed |
| `personnel_admin_channel_id` | Personal-Bedarf-Briefings für Spielleitung |

Alle Channel-IDs sind **18-stellige Discord-Snowflakes**. Per Rechtsklick auf einen Channel in Discord → **„ID kopieren"** (Entwicklermodus muss aktiv sein).

## Ranking-Posts (täglich)

Bot postet täglich zu festgelegten Zeiten automatisch das Ranking. Konfiguration in **Settings → 🏆 Ranking — Tägliches Posting**:

### Gesamt-Ranking-Post

| Setting | Default | Beschreibung |
|---|---|---|
| `ranking_daily_enabled` | `false` | Auto-Post aktivieren |
| `ranking_daily_channel_id` | — | Channel-ID |
| `ranking_daily_time` | `03:33` | Zeit `HH:MM` (Server-Zeit) |
| `ranking_daily_range` | `all` | `today` / `7d` / `30d` / `all` |
| `ranking_daily_crime_only` | `true` | Zivil-Firmen ausblenden |
| `ranking_daily_show_districts` | `true` | Stadtteil-Aggregat als Footer |
| `ranking_daily_title` | `🏆 Crew-Ranking — Liberty City` | Embed-Titel |
| `ranking_daily_intro` | — | Optionaler Text über Embed |

### Top-3-Hype-Post

Eigene Sektion in Settings, gleiche Felder mit Prefix `ranking_top3_*`. Plus **Titel-Pool** in Settings (zufällige Titel pro Tag — siehe [Nachrichtenpools](#nachrichtenpools)).

### Replace-Previous-Pattern

Beide Posts merken sich die letzte Message-ID (`ranking_daily_last_message_id` / `ranking_top3_last_message_id`) und löschen den vorherigen Post vor dem neuen. So bleibt der Channel sauber.

### Reset-Stichtag

`ranking_reset_at` — ISO-Timestamp. Wenn gesetzt: im „Gesamt"-View des Rankings zählen nur Missions ab diesem Datum, und `bonus_points` werden auf 0 zurückgesetzt.

Setzbar über **Ranking-Seite → „🔄 Ranking zurücksetzen"** (doppelter Confirm).

## Personal-Bedarf Admin-Channel

In **Settings → 🎭 Personal-Bedarf — Admin-Channel**:

```
personnel_admin_channel_id = <Discord-Channel-ID>
```

**Was passiert:**

1. Bei jeder neuen KI-Mission wird automatisch ein **Personal-Brief** generiert (Mittler + NPCs)
2. Beim „An Discord senden" postet der Bot **zusätzlich** im Admin-Channel ein Embed mit:
   - Crew-Name + Stadtteil
   - Slot (wann), Status
   - Personal-Brief (Mittler + NPC-Liste)
   - Auftrags-Snippet
3. Beim Mission-Update / -Edit: vorheriger Post wird ersetzt (Replace-Previous)
4. Beim Archivieren: Post wird automatisch gelöscht

**Manueller Post:** im Dashboard-Widget oder auf der Crew-Seite per **„📤 Posten"**-Button.

## System-Prompts verwalten

In **Settings → 💬 System-Prompts** kannst du beliebig viele Varianten anlegen und eine aktivieren.

### Beispiel-Prompts

**Default (Big-Boss-Stil):**
```
Du bist Briefing-Autor für eine GTA-V-Liberty-City-Roleplay-Krimiserie.
Deine Aufträge sind kurz (3 bis 4 Sätze), kryptisch und atmosphärisch.
...
```

**Casual:**
```
Schreibe direkter, weniger literarisch. Kurze Sätze, klare Aktionen.
Maximal 3 Sätze. Trotzdem im Crime-RP-Kontext.
```

**Hart-Boiled:**
```
Tonfall: Düster, brutal, ohne Pathos. Eher Noir-Roman als Big-Boss-Story.
...
```

### Wichtig

- **Nur ein Prompt kann aktiv sein** (`is_active=true`)
- Aktiver Prompt überschreibt den `DEFAULT_SYSTEM_PROMPT` aus `backend/prompts.py`
- Wenn kein Custom-Prompt aktiv: Default aus Code wird benutzt

### Default-Prompt aus Code laden

In der Liste: Button **„📋 Default-Kopie anlegen"** → erstellt einen editierbaren Klon vom Code-Default.

## Nachrichtenpools

Drei Pools für zufällige Texte. In Settings unter den jeweiligen Sektionen verwaltbar.

### Versager-Sprüche

Bot postet einen davon zufällig, wenn eine Mission-Deadline abläuft ohne Reaktion.

**Beispiele:**
- *„Stille spricht laut. Eure habe ich verstanden."*
- *„24 Stunden. Ihr hattet die Stadt im Griff — und sie ist euch durch die Finger gerutscht."*

DB-Tabelle: `expiry_messages`

### Reaktions-Antworten

Bot postet eine davon zufällig nach jeder Boss-Reaktion (👍 / 👎 / ❌).

**Beispiele:**
- *„Verstanden, Don."*
- *„Wir melden uns mit Details."*

DB-Tabelle: `reaction_messages`

### Top-3-Titel-Pool

Bot wählt zufällig einen Titel pro täglichem Top-3-Hype-Post.

**Beispiele:**
- *„🥇 Die Spitze von Liberty City"*
- *„👑 Wer regiert die Stadt"*

DB-Tabelle: `top3_title_pool` — Fallback: `settings.ranking_top3_title` wenn Pool leer.

## Stadtteile-Liste

Hartkodiert in `backend/seed_event_lore.py` (`FIRMS_TO_CREATE`). Aktuell:

- Algonquin
- Bohan
- Broker
- Colony Island
- Dukes

Für eigene Stadtteile: Datei anpassen + Re-Seed.

## NPC-Pool & Mittler

Über den **Mittler-Tab** (`/mittler`) editierbar:

- **`docs/QUEST_GIVERS.md`** — 6 Mittler (Miguel, Maklerin, Pater, Fixer, Witwe, Skrupellose)
- **`docs/QUEST_PERSONNEL.md`** — 15 NPC-Archetypen + Templates

⚠ **Beachten:** Der **NPC-Pool im KI-Prompt** (`backend/personnel_ai.py` → `NPC_POOL_PROMPT_DE`) ist hartkodiert für Performance. Wenn du neue Archetypen in `QUEST_PERSONNEL.md` einträgst, sieht die KI sie nicht automatisch — du musst auch `personnel_ai.py` erweitern.

## Settings-Whitelist

Backend lehnt unbekannte Settings-Keys ab. Whitelist in `backend/settings_store.py`:

```python
KEYS = {
    "anthropic_api_key",
    "openai_api_key",
    "default_provider",
    "default_claude_model",
    "default_openai_model",
    "system_prompt",
    # Ranking
    "ranking_daily_enabled", "ranking_daily_channel_id", ...
    "ranking_top3_enabled", "ranking_top3_channel_id", ...
    "ranking_reset_at",
    # Personnel
    "personnel_admin_channel_id",
}
```

Neue Keys → in Whitelist + `SettingsUpdate`-Schema + Mapping in `routes_settings.py` ergänzen.

## Nächste Schritte

- **[FEATURES.md](FEATURES.md)** — Komplette Feature-Übersicht
- **[ADMIN_GUIDE.md](ADMIN_GUIDE.md)** — Spielleiter-Workflows
- **[API.md](API.md)** — REST-API für Custom-Integrationen
