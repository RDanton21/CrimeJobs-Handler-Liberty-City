# ✨ Features

Komplette Feature-Übersicht von SEKT6R Crime Automation.

## Inhalt

1. [Dashboard](#-dashboard)
2. [Crew/Gang-Management](#-crewgang-management)
3. [Mission-System](#-mission-system)
4. [KI-Auftrag-Generierung](#-ki-auftrag-generierung)
5. [Discord-Integration](#-discord-integration)
6. [Personal-Bedarf-System](#-personal-bedarf-system)
7. [Mittler-Verwaltung](#-mittler-verwaltung)
8. [Ranking-System](#-ranking-system)
9. [Bonus-Punkte](#-bonus-punkte)
10. [Story-Editor](#-story-editor)
11. [Archive & Export](#-archive--export)
12. [Massen-Aufträge](#-massen-aufträge)

## 🖥 Dashboard

Hauptseite unter `/`.

### Sektionen

1. **Header** mit Navigation + Notification-Bell + „+ Neue Gang"
2. **Reaktions-Statistik** — Heute / 7 Tage / 30 Tage / Gesamt
3. **Massen-Auftrag senden** (ein-/ausklappbar)
4. **🎭 Personal-Bedarf-Widget** (Live, 30 s Polling)
5. **Gang-Liste** mit Kacheln pro Crew

### Reaktions-Statistik

Vier Status-Kacheln zeigen Counts:
- 👍 **Erledigt** — grüner Hintergrund
- 👎 **Fehlgeschlagen** — roter Hintergrund
- ❌ **Nicht durchführbar** — gelber Hintergrund
- ⏳ **Wartet** — neutraler Hintergrund

Filter:
- **Stadtteil-Dropdown**
- **Gang-Dropdown** (nur die der gewählten Stadtteile)
- **Zeitraum** (Heute / 7 Tage / 30 Tage / Gesamt)

Klick auf eine Kachel filtert die Crew-Liste auf den jeweiligen Status.

### Gang-Karten

Pro Crew eine Karte mit:
- **Farbiger Border-Link** (lefthand) — letzter Reaktions-Status
- **Pulsing Border** bei neuem Boss-Feedback (gelb)
- **Stadtteil-Tag**
- **Counts** (👍 / 👎 / ❌ / ⏳) der letzten 30 Tage
- **Klick → Crew-Detail**

### Notification-Bell

Im Header (🔔) mit Counter-Badge. Zählt:
- Neue Personal-Bedarf-Updates (seit letztem Klick)

Klick scrollt zum Personal-Bedarf-Widget.

## 👥 Crew/Gang-Management

### Crew anlegen

Im Dashboard: **„+ Neue Gang"** → Modal mit Feldern:

| Feld | Pflicht | Beschreibung |
|---|---|---|
| Name | ✅ | Anzeigename |
| Stadtteil | Empfohlen | Algonquin / Bohan / Broker / Colony Island / Dukes |
| Farbe | Empfohlen | Hex (`#b91c1c`) — für Cards, Embeds |
| Auftrags-Channel-ID | ✅ | Discord-Channel für Aufträge |
| Zusatzinfo-Channel-ID | Optional | Discord-Channel für Boss-Klartext-Feedback |
| Crime-Business-Channel-ID | Optional | Separater Workflow |
| Hintergrund-Story | ✅ | KI-Kontext (Multi-Line-Markdown) |
| Crime-Business | Optional | Interner KI-Kompass (nicht im Auftrag sichtbar) |

### Crew-Detail-Seite

Unter `/crew/{id}`. Vier Bereiche:

1. **Gang-Daten** — alle Felder editierbar, Live-Save bei Blur
2. **Beziehungen** — zu anderen Crews (allied / rival / hostile / business / neutral) mit Notiz
3. **Neuer Auftrag** — KI-generiert oder eigenen Text umschreiben
4. **KI-Folgeauftrags-Vorschläge** — 3 Vorschläge basierend auf letzter Reaktion
5. **🎁 Bonus-Punkte** — manuelle Vergabe (+2 / +5 / +10 / −2 / −5 / −10 / frei eingeben)
6. **Aktive Aufträge** — Liste mit Edit, Personal-Bedarf-Block, Boss-Feedback inline
7. **Archiv** (toggle-bar) — gleicher Aufbau, schreibgeschützt

### Beziehungs-Editor

Pro Beziehung:
- **Crew-Auswahl** (Dropdown der anderen Crews)
- **Typ** (5 Optionen)
- **Notiz** — Was ist der Konflikt-/Bündnis-Grund

Die KI nutzt diese als **Story-Treiber** — rivals/hostile-Beziehungen werden häufig in neue Aufträge eingewoben.

### Stadtteil-Tags

Pro Stadtteil eine Farbe + Emoji für visuelle Schnelle. In Frontend hartkodiert via `DISTRICTS` in `app.js`.

## 📋 Mission-System

### Mission-Status

| Status | Symbol | Beschreibung |
|---|---|---|
| `draft` | 📝 | Erstellt, nicht gesendet |
| `pending` | 🔴 | An Discord gesendet, wartet auf Boss-Reaktion |
| `approved` | ✅ | Boss-Reaktion 👍 |
| `rejected` | ❌ | Boss-Reaktion 👎 |
| `cancelled` | ⏹ | Boss-Reaktion ❌ |

### Mission-Workflow

```
Draft → Send → Pending → (Approved | Rejected | Cancelled) → Archive
```

### Optionen pro Mission

- **Provider/Modell** wählen (Anthropic / OpenAI)
- **Zusätzliche Hinweise** an die KI — werden in den Prompt eingebaut
- **Zusatzinfos** — werden 1:1 an den fertigen Text angehängt (Adressen, GPS, Codes)
- **Countdown** — Min/Std/Tage; Discord rendert als „in 2 Stunden"
- **Bild-Anhang** — wird mit dem Auftrag gepostet
- **Senden um** — geplanter Versand (Bot übernimmt)

### Mission-Aktionen

- **✎ Editieren** — Textarea-Bearbeitung mit Auto-Save bei Blur
- **🔁 Umformulieren** — neuer KI-Wurf mit aktuellem Text als Input
- **📤 An Discord senden** — manuell triggern (auch wenn Schedule gesetzt ist)
- **👍 / 👎 / ❌ Override** — Status manuell setzen (Spielleiter-Korrektur)
- **📦 Archivieren** — Soft-Delete mit Discord-Cleanup
- **🗑 Endgültig löschen** (nur Drafts)
- **📄 PDF-Export** (archivierte Missions)

## 🤖 KI-Auftrag-Generierung

### Drei Modi

| Modus | Input | KI-Verhalten |
|---|---|---|
| **KI generiert** | Hintergrund-Story + Beziehungen + Historie | Freie Generierung im Big-Boss-Stil |
| **Eigenen Text umschreiben** | User-Klartext | Verschlüsselt im RP-Stil, behält Inhalt bei |
| **Manuell** | User-Klartext | 1:1 übernommen, keine KI |

### Story-bewusste Generierung

KI bekommt als Kontext:
- **Crew-Name + Hintergrund-Story**
- **Crime-Business** (interner Kompass: Drogen / Waffen / Schutzgeld / Geldwäsche)
- **Beziehungen** (rivals als Story-Treiber priorisiert)
- **Letzte 5 Missions** (mit Status) für Verzweigung:
  - 👍 letzte Mission → Story konsequent fortführen
  - 👎 → Tonart wechseln, anderen Weg
  - Kein Vorgänger → frischer Einstieg

### Auto-Cleaner (Post-Processing)

Jeder KI-Output durchläuft 3 Reinigungsstufen:

1. **Aktennummer-Strip** — entfernt „Vorgang 091-23." am Anfang (auch mit `> ` Quote-Prefix)
2. **Reaktions-Strip** — entfernt „👍 oder 👎." am Ende
3. **Zahlen-Digitize** — `acht Minuten` → `8 Minuten`, `dreiundzwanzig` → `23`

Wird automatisch in `/generate`, `/rewrite`, `/manual`, `/bulk_send` und Re-Generate angewandt.

### Server-Zeitfenster

KI-System-Prompt setzt:
> *„AKTIONS-ZEITFENSTER: Server ist nur zwischen 17:00 und 02:00 aktiv. ALLE Zeitangaben MÜSSEN in diesem Fenster liegen."*

Resultat: keine „04:00 morgens"-Aufträge mehr, KI nutzt 17:00–02:00.

### KI-Folgeauftrags-Vorschläge

Im Crew-Detail nach einer Reaktion: **„Neu generieren"** liefert 3 Mini-Vorschläge:
- 👍 → **Eskalation** (nächste Stufe)
- 👎 → **Tonwechsel** (anderer Ansatz)
- ❌ → **Realistischer / frischer Einstieg**

Klick auf einen Vorschlag → wird als Draft angelegt, editierbar.

## 💬 Discord-Integration

### Bot „Il Padrino"

Eigenständiger Python-Prozess (`backend/bot.py`), kommuniziert mit Backend über interne HTTP-API auf `127.0.0.1:8001`.

### Auftrag senden

1. Backend ruft `POST /send` am Bot
2. Bot lädt Mission aus DB
3. Bot postet Embed im Crew-Channel mit:
   - **Content** — Auftragstext
   - **Footer** — Deadline (`<t:UNIX:R>` Live-Render)
   - **Image** — falls Bild gesetzt
4. Bot setzt 👍 / 👎 / ❌ als initiale Reaktionen
5. DB-Update: `status=PENDING`, `sent_at=now()`, `discord_message_id`

### Reaktions-Tracking (Single-Vote)

- Discord-Listener wartet auf User-Reaktionen
- **Erste Boss-Reaktion zählt** → Status-Update in DB
- **Andere Reaktionen werden gelöscht** (kein Doppel-Voting)
- **Nicht-Boss-Reaktionen** auch entfernt
- Optional: **Reaktions-Antwort** wird gepostet (Zufalls-Pool)

### Boss-Feedback-Polling

Read-Channel-Watcher liest alle 5 Sekunden den `info_channel_id` jeder Crew:
- Nimmt alle Messages **nach `sent_at`** der zuletzt aktiven Mission
- Stoppt vor `sent_at` der nächsten Mission
- Speichert Author, Content, Attachments, Timestamps
- UI zeigt sie inline unter der Mission

### Versager-Reply

Deadline-Watcher (alle 30 s) findet Missions mit abgelaufener `deadline_at` und Status `PENDING`:
- Wählt zufällig einen Spruch aus `expiry_messages`
- Postet als Reply auf den Auftragspost
- Setzt Status auf `REJECTED`
- Speichert `expiry_message_id` für späteres Cleanup

### Scheduled Send

Schedule-Watcher (alle 30 s) findet Drafts mit `scheduled_send_at <= now`:
- Postet automatisch über `_post_mission_to_discord()`
- Setzt Status auf `PENDING`, leert `scheduled_send_at`

### Archive-Cleanup

Beim Archivieren löscht der Bot:
- **Original-Auftragspost**
- **Versager-Reply** (falls vorhanden)
- **Reaktions-Antwort** (falls vorhanden)
- **Boss-Texte** im Info-Channel (im Zeitfenster der Mission)
- **Personal-Bedarf-Embed** im Admin-Channel (falls Auto-Post aktiv)

## 🎭 Personal-Bedarf-System

### Was es macht

Pro Mission generiert die KI ein **strukturiertes Personal-Briefing**:
- **Mittler** (welcher Quest-Geber übergibt) — Miguel / Maklerin / Pater / Fixer / Witwe / Skrupellose
- **Quest-NPCs** aus dem 15-Archetype-Pool (Hafenmeister, Bankleiter, etc.)
- **Locations** passend zur Crew (Stadtteil)
- **Slot** (Zeitfenster im Server-Range 17:00–02:00)
- **Team-Auslastung** (wie viele NPC-Spieler gebraucht)

### NPC-Pool (15 Archetypen)

| # | Archetype | Typischer Einsatz |
|---|---|---|
| 1 | Hafenmeister | Container, Schmuggel |
| 2 | Korrupter LCPD-Officer | Bestechung |
| 3 | LCPD-Detective | Ermittlung |
| 4 | Bankkassierer / -leiter | Heists, Geldwäsche |
| 5 | Bar-/Restaurantchef | Tribut, Treffpunkt |
| 6 | Tankwart / Late-Night-Shop | Tribut, Augenzeuge |
| 7 | Werkstatt-Mechaniker | Fahrzeug-Verstecker |
| 8 | Reporter / Journalist | Skandale |
| 9 | Stadtrat / Politiker | Polit-Mord, Bestechung |
| 10 | Anwalt / Geldwäscher | Saubermachen |
| 11 | Lieferant / Trucker | Stealth-Übergaben |
| 12 | Wachmann | Stealth-Hindernis |
| 13 | Informant / Snitch | Tipps, Aussage |
| 14 | „Kein-Fragen"-Arzt | Schussverletzungen |
| 15 | Geisel / Ziviler Statist | Heist, Entführung |

### Auto-Generierung

KI-Personal-Brief läuft als **separater KI-Call** nach jeder Mission-Generierung:
- Eigenes System-Prompt (Spielleiter-Assistent statt Big-Boss-Autor)
- Bekommt NPC-Pool als Kontext
- Spuckt strukturiertes Markdown aus

Wird bei `/generate`, `/rewrite`, `/manual` und `/bulk_send` ausgeführt.

### Dashboard-Widget

Live-Anzeige auf `/`:
- **Filter** (Alle aktiven / 24 h / 7 Tage / 30 Tage)
- **30-Sek-Polling** mit ETag-Vergleich
- **Toast + Bell-Update** bei Änderung
- **Browser-Notification** wenn Tab nicht aktiv (Berechtigung nötig)

Pro Mission Karte mit:
- Crew + Stadtteil + Slot + Status
- Auftrags-Snippet
- Voller Personal-Brief
- **✎ bearbeiten** + **🤖 KI-Vorschlag** (neuer Lauf)
- **📤 Posten** in Admin-Channel

### Discord-Auto-Post

Bei jedem `_post_mission_to_discord()`:
1. Mission wird im Crew-Channel gepostet
2. **Parallel** wird der Personal-Brief als Embed im `personnel_admin_channel_id` gepostet:
   - Title: `🎭 Personal-Bedarf — {Crew-Name}`
   - Color: crew.color_hex
   - Fields: Slot, Status, Stadtteil
   - Description: voller Brief
   - Auftrags-Snippet als zusätzliches Field
3. Bei Update: vorheriger Post wird gelöscht (Replace-Previous)
4. Bei Archivierung: Post wird gelöscht

### Templates für Massen-Aufträge

Sechs vordefinierte Templates über das Vorlage-Dropdown im Edit-Modus:
- **Tag 2 — Der Tribut** (Schutzgeld-Einkassierung)
- **Tag 4 — Die Stille** (Stealth-Operation)
- **Tag 7 — Der Verrat** (privat an Top-3)
- **Tag 9 — Die Probe** (Rivalitäts-Eskalation)
- **Tag 10 — Die Krone** (großer Coup)
- **Leer** (Custom-Vorlage)

## 👤 Mittler-Verwaltung

### Read-Only-Ansicht

Unter `/mittler` mit zwei Tabs:
- **👤 Mittler (Quest-Geber)** — rendert `docs/QUEST_GIVERS.md`
- **🎭 NPC-Pool** — rendert `docs/QUEST_PERSONNEL.md`

### In-Page-Editor

**✎ Bearbeiten**-Button im Header öffnet Textarea-Editor:
- **+ Neuer Mittler** (Tab 1) — fügt vorgefüllten Mittler-Block ans Ende
- **+ Neue NPC-Zeile** (Tab 2) — fügt Tabellenzeile an
- **💾 Speichern** — schreibt zurück mit `.bak`-Backup

### KI-Konsistenz-Check

**🔍 Konsistenz-Check (vs. Story)**-Button:

1. Backend lädt `QUEST_GIVERS.md` + `EVENT_BRIEFING.md` + `EVENT_TIMELINE.md` + `CITY_PUBLIC_BRIEFING.md`
2. KI bekommt beides + Aufgabe „prüfe, ob die Mittler noch zur Story passen"
3. KI liefert strukturierten Report:
   - **Gesamtbewertung** (1–3 Sätze)
   - **Pro Mittler**: ✅ passt / ⚠️ Anpassung / ❌ ersetzen
   - **Zusätzliche Mittler-Ideen**
   - **Empfohlene nächste Schritte**
4. **Recommendations als JSON-Block** am Ende der Antwort

### Auto-Apply

Pro Empfehlung erscheint eine **🤖 Anwenden**-Card mit Button:
1. KI bekommt: aktuelle Datei + spezifische Edit-Anweisung
2. KI generiert **komplette überarbeitete Datei**
3. **Preview-Modal** öffnet sich (Vorher | Nachher Split-Screen)
4. Nachher ist **editierbar** vor Übernahme
5. **💾 Übernehmen** speichert (`.bak`-Backup automatisch)
6. **Konsistenz-Check läuft direkt neu** mit der aktualisierten Datei

### Robuster JSON-Parser

3-Strategie-Extraktion für die KI-Empfehlungen:
1. `<recommendations_json>...</recommendations_json>` (Soll-Format)
2. ` ```json ... ``` ` (Codefence)
3. Nacktes `[ { ... } ]` am Ende (Fallback)
4. **Plus Bullet-Fallback** — wenn alle 3 leer: parse die „Empfohlene nächste Schritte"-Bullets als Recommendations

## 🏆 Ranking-System

### Punkte-Formel

```
crew_points = (approved × 2) + (rejected × −1) + bonus_points
```

Konstanten in `backend/routes_missions.py`.

### Ranking-Seite (`/ranking`)

- **Vollständige Tabelle** mit Rang, Crew-Name, Stadtteil, Counts pro Status, Punkte
- **Top-3 mit Gold/Silber/Bronze**-Border
- **Filter** — Zeitraum (Heute / 7 Tage / 30 Tage / Gesamt), optional „Nur Crime-Crews"
- **Auto-Refresh** alle 15 Sekunden

### Aktionen

- **📋 Gesamt jetzt posten** — One-Click-Versand in den konfigurierten Daily-Channel
- **🥇 Top 3 jetzt posten** — One-Click-Versand in den Top-3-Channel
- **🔄 Ranking zurücksetzen** — setzt `bonus_points` auf 0 + setzt `ranking_reset_at` auf jetzt

### Tägliche Auto-Posts

Bot postet automatisch zu konfigurierten Zeiten (`ranking_daily_time` / `ranking_top3_time`):
- Embed mit Title, Description (Intro), Field-Liste der Crews
- Replace-Previous: alter Post wird gelöscht, neuer gepostet
- Pro Massen-Auftrag-Tag bekommt der Top-3-Titel zufällig aus `top3_title_pool`

## 🎁 Bonus-Punkte

Manuelle Punkte-Vergabe pro Crew im Crew-Detail.

### Quick-Buttons

```
+2    +5    +10
−2    −5    −10
```

Plus **Freie Eingabe** + **0 Auf Null setzen**.

### Use-Cases

- **Beispiel-Spieler**-Belohnung für besonderes RP
- **Strafe** für Regelverstöße (Stille Sanktion ohne Mission-Override)
- **Story-Boni** außerhalb des Mission-Systems

### Reset

- Per Crew: 0-Button im Bonus-Bereich
- Global: Ranking-Reset-Button (alle Crews auf bonus_points = 0)

## 📝 Story-Editor

Unter `/story`. Whitelist-basierter Markdown-Editor für die Kern-Story-Files.

### Editierbare Files

| Datei | Was drin steht |
|---|---|
| `EVENT_BRIEFING.md` | Eröffnungs-Kapitel |
| `EVENT_TIMELINE.md` | 10-Tage-Timeline |
| `EVENT_FINALE.md` | Finale |
| `EVENT_BRIEFINGS_MASS.md` | Massen-Briefings für Tag 2/4/7/9/10 |
| `CITY_PUBLIC_BRIEFING.md` | Öffentliche Grundstory |
| `QUEST_GIVERS.md` | Mittler-Profile |
| `QUEST_PERSONNEL.md` | NPC-Pool + Templates |
| `DISTRICTS.md` | Stadtteile |
| `CREW_RELATIONS.md` | Beziehungs-Notizen |

### Features

- **Linke Liste** mit Files + Größen
- **Hauptbereich** mit Markdown-Textarea
- **Auto-Backup** als `.bak` vor jedem Save
- **Preview-Button** (rendert Markdown)
- **Path-Traversal-Schutz** (Whitelist-only)

## 📦 Archive & Export

### Soft-Delete-Workflow

Bei Archivierung:
1. **Snapshot** des Boss-Feedbacks aus Info-Channel (in `archived_boss_info` als JSON)
2. **Discord-Cleanup**:
   - Original-Auftragspost gelöscht
   - Versager-Reply gelöscht
   - Reaktions-Antwort gelöscht
   - Boss-Texte im Info-Channel gelöscht (Zeitfenster)
   - Personal-Bedarf-Embed im Admin-Channel gelöscht
3. **DB-Update** — `archived_at = now()`, IDs werden geleert

### Archive-Page

Globale Ansicht aller archivierten Missions:
- **Filter** nach Crew
- **Pro Mission** — Status, Datum, archiviertes Boss-Feedback
- **📄 PDF-Export** — komplettes Briefing inkl. Bild + Boss-Texte

### Restore

Bringt Mission aus Archive zurück (Status bleibt erhalten, Discord-Posts kommen NICHT zurück).

### Endgültig Löschen

Permanent-Delete inkl. Bild-Datei aus `data/images/`.

## 📢 Massen-Aufträge

Im Dashboard: **„📢 Massen-Auftrag senden"** Block.

### Scope

- **Alle Crews** mit gesetztem Discord-Channel
- **Nach Stadtteil**
- **Manuelle Auswahl** (Checkbox-Liste)

### Modi

| Modus | Was passiert |
|---|---|
| **Klartext direkt** | Text 1:1 an alle |
| **KI-Roh-Input umschreiben** | Einmaliger KI-Aufruf (erste Crew als Kontext), Vorschau, dann an alle |
| **KI aus Story generieren** | Einmaliger Frei-Generieren-Aufruf, dann an alle |

### Phase-Workflow

1. **Input** — Modus + Text + Scope wählen
2. **Vorschau** (bei KI-Modi) — KI generiert einmal, du editierst
3. **Dispatch** — Parallel an alle Crews mit `asyncio.Semaphore(5)` (max 5 gleichzeitig)
4. **Result** — pro Crew Erfolg/Fehler

### Personal-Brief bei Bulk

Wird einmal generiert (mit erster Crew als Kontext) und auf alle angewendet. Pro Crew nachträgliche Anpassung im Dashboard-Widget möglich.

## Nächste Schritte

- **[ADMIN_GUIDE.md](ADMIN_GUIDE.md)** — Best Practices für Spielleiter
- **[CONFIGURATION.md](CONFIGURATION.md)** — Settings im Detail
- **[API.md](API.md)** — REST-API für Custom-Integrationen
