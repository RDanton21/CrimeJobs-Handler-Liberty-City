# 🔌 API Reference

REST-API-Referenz für Crime Automation. Alle Endpoints auf `127.0.0.1:8000` mit HTTP-Basic-Auth.

## Inhalt

1. [Authentifizierung](#authentifizierung)
2. [Konventionen](#konventionen)
3. [System](#system)
4. [Crews](#crews)
5. [Missions](#missions)
6. [Dashboard](#dashboard)
7. [Story](#story)
8. [Settings](#settings)
9. [System-Prompts](#system-prompts)
10. [Nachrichtenpools](#nachrichtenpools)
11. [Bot-API (intern)](#bot-api-intern)

## Authentifizierung

Alle Endpoints (außer `/api/health`) benötigen HTTP-Basic-Auth mit `ADMIN_USERNAME` und `ADMIN_PASSWORD` aus `.env`.

```bash
curl -u admin:supersecret http://127.0.0.1:8000/api/crews
```

## Konventionen

- **Base URL**: `http://127.0.0.1:8000`
- **Content-Type**: `application/json` (außer File-Uploads → `multipart/form-data`)
- **Datumsformat**: ISO 8601 ohne Zeitzonen (`2026-08-07T18:00:00`)
- **IDs**: Auto-Increment Integer
- **Soft-Delete**: Mission-Archive setzt `archived_at`, Datensatz bleibt erhalten

### Error-Format

```json
{
  "detail": "Mission nicht gefunden"
}
```

Standard-HTTP-Codes:
- `200` OK
- `204` No Content (DELETE)
- `400` Bad Request (Validation)
- `401` Unauthorized
- `404` Not Found
- `409` Conflict (z.B. „Nur DRAFTs editierbar")
- `422` Pydantic-Validation-Error
- `502` Bad Gateway (KI- oder Bot-Fehler)

## System

### `GET /api/health`

Health-Check ohne Auth.

```json
{ "ok": true }
```

## Crews

### `GET /api/crews`

Liste aller Crews mit `last_mission_status` und `last_mission_at`.

**Response:**
```json
[
  {
    "id": 1,
    "name": "Vipers",
    "story_background": "...",
    "crime_business": "Drogen",
    "discord_channel_id": "1234...",
    "info_channel_id": "5678...",
    "district": "Bohan",
    "color_hex": "#b91c1c",
    "bonus_points": 0,
    "created_at": "2026-06-14T12:00:00",
    "last_mission_status": "approved",
    "last_mission_at": "2026-06-14T15:30:00"
  }
]
```

### `POST /api/crews`

Neue Crew anlegen.

**Body:**
```json
{
  "name": "Vipers",
  "story_background": "Operiert seit den 90ern...",
  "crime_business": "Drogen",
  "discord_channel_id": "1234...",
  "info_channel_id": "5678...",
  "district": "Bohan",
  "color_hex": "#b91c1c"
}
```

### `GET /api/crews/{id}`

Eine Crew abrufen.

### `PATCH /api/crews/{id}`

Crew updaten. Alle Felder optional.

```json
{
  "story_background": "Neue Story...",
  "bonus_points": 50
}
```

### `DELETE /api/crews/{id}`

Crew löschen (inkl. aller zugehörigen Missions per cascade).

### `POST /api/crews/{id}/bonus`

Bonus-Punkte inkrementell ändern.

**Body:**
```json
{ "points": 5 }
```

Liefert die aktualisierte Crew.

### `GET /api/crews/{id}/relations`

Beziehungen einer Crew.

```json
[
  {
    "id": 1,
    "crew_a_id": 1,
    "crew_b_id": 2,
    "relation_type": "rival",
    "notes": "Hafenkrieg 2023..."
  }
]
```

### `POST /api/crews/{id}/relations`

Neue Beziehung anlegen.

**Body:**
```json
{
  "crew_a_id": 1,
  "crew_b_id": 2,
  "relation_type": "rival",
  "notes": "Hafenkrieg 2023..."
}
```

### `DELETE /api/crews/relations/{rel_id}`

Beziehung löschen.

### `GET /api/crews/notifications`

Pulsing-Border-Status aller Crews (für Boss-Feedback-Indicator).

```json
{
  "1": "2026-06-14T15:35:00",
  "2": null
}
```

## Missions

### `GET /api/missions`

Liste mit Filtern.

**Query-Parameter:**
- `crew_id` — auf eine Crew filtern
- `archived` — `true` / `false`
- `status` — `draft` / `pending` / `approved` / ...
- `limit` — Default 100

### `GET /api/missions/{id}`

Einzelne Mission.

```json
{
  "id": 42,
  "crew_id": 1,
  "ai_provider": "anthropic",
  "ai_model": "claude-sonnet-4-5-20250929",
  "content_generated": "...",
  "content_final": "...",
  "image_path": "data/images/abc.jpg",
  "discord_message_id": "999...",
  "discord_channel_id": "1234...",
  "status": "pending",
  "created_at": "2026-06-14T12:00:00",
  "sent_at": "2026-06-14T12:01:00",
  "deadline_at": "2026-06-14T18:00:00",
  "personnel_brief": "**Mittler:** Der Fixer...",
  "personnel_updated_at": "2026-06-14T12:01:00",
  "personnel_discord_message_id": "888..."
}
```

### `POST /api/missions/generate`

KI generiert frei.

**Body:**
```json
{
  "crew_id": 1,
  "provider": "anthropic",
  "model": null,
  "extra_instructions": "Diesmal eskaliert vom letzten Verrat",
  "append_text": "GPS: 1234,5678",
  "deadline_minutes": 240,
  "scheduled_send_at": "2026-08-07T20:00:00"
}
```

Personal-Brief wird automatisch mitgemacht.

### `POST /api/missions/rewrite`

KI verschlüsselt Klartext-Input im RP-Stil.

**Body:**
```json
{
  "crew_id": 1,
  "raw_input": "Crew soll Container am Hafen klauen...",
  "provider": "anthropic"
}
```

### `POST /api/missions/manual`

Klartext-Mission ohne KI.

**Body:**
```json
{
  "crew_id": 1,
  "content": "GPS: 1234,5678 — Code 4711",
  "deadline_minutes": 60
}
```

Personal-Brief wird trotzdem KI-generiert (defensiv, leer bei Fehler).

### `POST /api/missions/{id}/rewrite`

Bestehenden Draft mit KI re-generieren.

### `PATCH /api/missions/{id}`

Mission updaten (nur DRAFT-Status).

**Body:**
```json
{
  "content_final": "Editierter Text...",
  "scheduled_send_at": "2026-08-08T20:00:00",
  "clear_scheduled_send_at": false
}
```

### `DELETE /api/missions/{id}`

**Soft-Delete (Archivieren)**. Discord-Cleanup automatisch. Snapshots werden erstellt.

### `POST /api/missions/{id}/restore`

Aus Archive zurückholen.

### `DELETE /api/missions/{id}/purge`

Endgültig löschen (auch aus Archive). Bild-Datei wird ebenfalls gelöscht.

### `POST /api/missions/{id}/send`

An Discord senden. Bot wird intern aufgerufen.

### `POST /api/missions/{id}/override`

Status manuell setzen (Spielleiter-Korrektur).

**Body:**
```json
{ "status": "approved" }
```

### `POST /api/missions/{id}/image`

Bild anhängen.

**Content-Type:** `multipart/form-data`
**File-Field:** `file`

### `DELETE /api/missions/{id}/image`

Bild entfernen.

### `GET /api/missions/{id}/pdf`

PDF-Export der Mission.

**Response:** `application/pdf`

### `GET /api/missions/ranking`

Crew-Ranking.

**Query-Parameter:**
- `since` — ISO-Datum, default `null` (= seit ranking_reset_at oder unbeschränkt)
- `crime_only` — `true` / `false`

**Response:**
```json
{
  "crews": [
    {
      "crew_id": 1,
      "name": "Vipers",
      "district": "Bohan",
      "color_hex": "#b91c1c",
      "approved": 5,
      "rejected": 2,
      "cancelled": 1,
      "pending": 0,
      "bonus_points": 5,
      "mission_points": 8,
      "points": 13
    }
  ],
  "districts": { "Bohan": 13 },
  "since": "2026-06-14T00:00:00",
  "crime_only": true
}
```

### `POST /api/missions/ranking/reset`

Setzt `bonus_points` aller Crews auf 0 und stempelt `ranking_reset_at`.

```json
{
  "ok": true,
  "reset_at": "2026-06-14T15:30:00",
  "crews_total": 21,
  "bonus_resets": 8
}
```

### `POST /api/missions/ranking/post-to-discord`

Manuelles Ranking-Posting.

**Body:**
```json
{
  "channel_id": "1234...",
  "since": null,
  "crime_only": true,
  "title": "🏆 Crew-Ranking — Liberty City",
  "intro": "",
  "show_district_aggregate": true,
  "mode": "full",
  "replace_previous": true
}
```

### `GET /api/missions/stats`

Aggregat-Stats für Dashboard.

**Query:**
- `crew_id`
- `since`

### `POST /api/missions/bulk_send`

Massen-Versand.

**Body:**
```json
{
  "crew_ids": [1, 2, 3],
  "content": "Text...",
  "deadline_minutes": 120,
  "scheduled_send_at": "2026-08-07T20:00:00"
}
```

### `POST /api/missions/suggestions/{crew_id}`

3 KI-Folgeauftrags-Vorschläge basierend auf letzter Reaktion.

## Dashboard

### `GET /api/dashboard/personnel`

Personal-Bedarf-Liste.

**Query-Parameter:**
- `mode` — `active` (Default) / `window`
- `hours` — bei `mode=window`: Stunden-Fenster

**Response:**
```json
{
  "items": [
    {
      "mission_id": 42,
      "crew_id": 1,
      "crew_name": "Vipers",
      "crew_color_hex": "#b91c1c",
      "crew_district": "Bohan",
      "slot": "2026-08-07T20:00:00",
      "status": "pending",
      "deadline_at": "2026-08-07T22:00:00",
      "personnel_brief": "**Mittler:** ...",
      "personnel_updated_at": "2026-08-07T19:55:00",
      "personnel_discord_message_id": "888...",
      "content_snippet": "Drei Lieferungen, eine Nacht..."
    }
  ],
  "count": 1,
  "mode": "active",
  "horizon_hours": null,
  "generated_at": "2026-08-07T20:05:00",
  "etag": "a3f9b2c1..."
}
```

ETag-Header für effizientes Polling.

### `PATCH /api/dashboard/missions/{id}/personnel`

Personal-Brief editieren.

**Body:**
```json
{
  "personnel_brief": "**Mittler:** Der Fixer..."
}
```

### `POST /api/dashboard/missions/{id}/personnel/ai-suggest`

KI generiert neuen Personal-Brief-Vorschlag (nicht direkt gespeichert).

**Response:**
```json
{
  "suggestion": "**Mittler:** Der Fixer..."
}
```

### `POST /api/dashboard/missions/{id}/personnel/post`

Personal-Brief in Admin-Channel posten (Replace-Previous).

### `GET /api/dashboard/personnel/templates`

Vorgefertigte Personal-Templates.

```json
{
  "templates": [
    {
      "id": "tag2_tribut",
      "label": "Tag 2 — Der Tribut (Schutzgeld)",
      "content": "..."
    }
  ]
}
```

## Story

### `GET /api/story/files`

Liste aller editierbaren Story-Files.

### `GET /api/story/file/{filename}`

Inhalt einer Datei.

### `PUT /api/story/file/{filename}`

Datei speichern. Backup als `.bak` wird automatisch erstellt.

**Body:**
```json
{
  "content": "# Markdown..."
}
```

### `POST /api/story/quest-givers/consistency-check`

KI prüft Konsistenz zwischen Mittlern und Story.

**Response:**
```json
{
  "report": "## Gesamtbewertung\n\n...",
  "recommendations": [
    {
      "title": "Maklerin anpassen",
      "instruction": "Betone, dass sie...",
      "target": "Die Maklerin"
    }
  ],
  "story_files_used": ["EVENT_BRIEFING.md", "EVENT_TIMELINE.md"],
  "givers_size": 13436
}
```

### `POST /api/story/quest-givers/apply-recommendation`

KI wendet eine Empfehlung auf `QUEST_GIVERS.md` an.

**Body:**
```json
{
  "instruction": "Füge einen neuen Mittler 'Der Schatten' hinzu..."
}
```

**Response:**
```json
{
  "new_content": "# Die Mittler...",
  "old_size": 13436,
  "new_size": 14250
}
```

Der neue Content wird NICHT direkt gespeichert — der Client soll ihn per `PUT /api/story/file/QUEST_GIVERS.md` einreichen.

## Settings

### `GET /api/settings`

Alle Settings als KV-Map.

```json
{
  "anthropic_api_key": "sk-ant-...",
  "default_provider": "anthropic",
  "ranking_daily_channel_id": "1234...",
  "personnel_admin_channel_id": "5678..."
}
```

### `PATCH /api/settings`

Einzelne Settings updaten. Unbekannte Keys werden defensiv übersprungen.

```json
{
  "personnel_admin_channel_id": "1515654327459381479"
}
```

## System-Prompts

### `GET /api/system-prompts`

Liste aller Prompts.

### `POST /api/system-prompts`

Neuen Prompt anlegen.

```json
{
  "name": "Casual",
  "text": "Schreibe direkter..."
}
```

### `PATCH /api/system-prompts/{id}`

Prompt updaten.

### `DELETE /api/system-prompts/{id}`

Löschen.

### `POST /api/system-prompts/{id}/activate`

Diesen Prompt als aktiv setzen (deaktiviert alle anderen).

### `GET /api/system-prompts/default`

Default-Prompt aus Code zurückgeben (für Quick-Copy in der UI).

## Nachrichtenpools

Drei Pools, gleiche API-Struktur.

### Versager-Sprüche

- `GET /api/expiry-messages`
- `POST /api/expiry-messages` — `{ "text": "..." }`
- `DELETE /api/expiry-messages/{id}`

### Reaktions-Antworten

- `GET /api/reaction-messages`
- `POST /api/reaction-messages`
- `DELETE /api/reaction-messages/{id}`

### Top-3-Titel-Pool

- `GET /api/top3-title-pool`
- `POST /api/top3-title-pool`
- `DELETE /api/top3-title-pool/{id}`

## Bot-API (intern)

Läuft auf `127.0.0.1:8001`. **Nicht von außen erreichbar**, wird vom Backend per `httpx` aufgerufen.

### `GET /health`

```json
{ "ok": true, "ready": true }
```

### `POST /send`

Mission an Discord senden.

**Body:**
```json
{ "mission_id": 42 }
```

Personal-Auto-Post läuft parallel.

### `POST /send_embed`

Embed posten (für Ranking, Personal-Bedarf, Custom).

**Body:**
```json
{
  "channel_id": "1234...",
  "content": "",
  "embed": {
    "title": "...",
    "description": "...",
    "color": 12131356,
    "fields": [{ "name": "...", "value": "...", "inline": true }],
    "footer": { "text": "..." },
    "timestamp": "2026-08-07T20:00:00",
    "thumbnail_url": null,
    "image_url": null
  }
}
```

**Response:**
```json
{ "ok": true, "message_id": "999..." }
```

### `POST /post_text`

Klartext-Post.

```json
{ "channel_id": "1234...", "content": "Text..." }
```

### `POST /delete_message`

```json
{ "channel_id": "1234...", "message_id": "999..." }
```

### `POST /delete_in_range`

Zeitfenster löschen (für Boss-Feedback-Cleanup).

```json
{
  "channel_id": "1234...",
  "after_iso": "2026-08-07T20:00:00",
  "before_iso": "2026-08-08T20:00:00"
}
```

### `POST /read_channel`

```json
{
  "channel_id": "1234...",
  "after_iso": "2026-08-07T20:00:00",
  "limit": 100
}
```

**Response:**
```json
[
  {
    "message_id": "999...",
    "author": "BossUserName",
    "content": "Text...",
    "posted_at": "2026-08-07T21:30:00",
    "attachments": [
      {
        "url": "https://...",
        "filename": "evidence.jpg",
        "content_type": "image/jpeg"
      }
    ]
  }
]
```

## Versionierung

Aktuelle API-Version: **v2.0** (nach Personal-Bedarf-System-Release).

Breaking Changes werden im Changelog dokumentiert. Patches bleiben rückwärtskompatibel.

## OpenAPI / Swagger

Bei lokalem Start: <http://127.0.0.1:8000/docs> liefert auto-generierte Swagger-UI für interaktives Testen.

ReDoc-Format: <http://127.0.0.1:8000/redoc>
