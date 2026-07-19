# 🎯 Admin Guide

Spielleiter-Handbuch für Crime Automation. Best Practices, Event-Setup, Personal-Planung.

## Inhalt

1. [Erste Schritte](#erste-schritte)
2. [Crew-Aufbau](#crew-aufbau)
3. [Beziehungs-Setup für packende Story](#beziehungs-setup-für-packende-story)
4. [Auftrag-Workflows](#auftrag-workflows)
5. [Personal-Planung](#personal-planung)
6. [Massen-Aufträge / Event-Tage](#massen-aufträge--event-tage)
7. [Ranking-Strategie](#ranking-strategie)
8. [Boss-Feedback-Workflow](#boss-feedback-workflow)
9. [Häufige Fragen](#häufige-fragen)

## Erste Schritte

### Tag 1: Discord-Setup

1. **Bot zum Server einladen** — komplette Schritt-für-Schritt-Anleitung in **[DISCORD_BOT_SETUP.md](DISCORD_BOT_SETUP.md)**
2. **Channel-Struktur** anlegen:
   ```
   📂 Crime-Automation
     #aufträge-vipers       ← Crew-Auftrags-Channel
     #zusatzinfo-vipers     ← Crew-Boss-Feedback-Channel
     #aufträge-mob          
     #zusatzinfo-mob
     ...
   📂 Spielleitung
     #🏆-ranking            ← ranking_daily_channel_id
     #🥇-top-3              ← ranking_top3_channel_id
     #🎭-personal-bedarf    ← personnel_admin_channel_id
   ```
3. **Channel-IDs sammeln** (Rechtsklick → ID kopieren mit aktivem Entwicklermodus)

### Tag 2: Tool-Setup

1. **Admin-Login** vergeben (in `.env`)
2. **API-Keys** eintragen (Settings → KI-Konfiguration)
3. **Default-System-Prompt** prüfen (Settings → System-Prompts), ggf. Casual/Hart-Boiled-Variante anlegen
4. **Channel-IDs in Settings** eintragen (Ranking + Personal-Bedarf)
5. **Test-Crew** anlegen, Test-Mission generieren, an Discord senden, Reaktion testen

### Tag 3+: Echtbetrieb

- Crews anlegen
- Hintergrund-Stories sorgfältig schreiben (sind KI-Kontext!)
- Beziehungen einpflegen
- Erste Missionen verteilen

## Crew-Aufbau

### Hintergrund-Story schreiben

Die Story ist **KI-Treibstoff**. Je besser sie ist, desto besser die Aufträge.

**Schlecht** (KI bekommt keinen Kontext):
> Die Vipers sind eine Gang in Bohan.

**Besser**:
> Die Vipers operieren seit den 90ern in Bohan, mit Wurzeln in der zweiten dominikanischen Einwanderungswelle. Sie kontrollieren den Hafen-Schwarzmarkt zwischen Pier 4 und 11, halten Tribut von 17 Bars und 3 Restaurants ein. Ihre Schwäche: zu sichtbar geworden — letztes Jahr hatten sie einen LCPD-Officer im Sold, der jetzt in Federal-Custody sitzt. Die Vipers wissen nicht, wieviel er weiß.

**Was die KI daraus nimmt:**
- **Orte** → Hafen, Pier 4-11, Bars, Restaurants
- **Rollen** → Tribut-Pflichtige, korrupter Cop
- **Konflikt-Hook** → Cop in Custody, Unsicherheit
- **Stil** → Etablierte Familie, mit Geschichte

### Crime-Business — der „interne Kompass"

Dieses Feld sieht die KI als **Direction**, aber bringt es nicht im Auftragstext.

| Wert | Auswirkung |
|---|---|
| `Drogenhandel` | Aufträge gehen oft um Übergaben, Labore, Streckmittel |
| `Waffenhandel` | Container-Schmuggel, Lieferungen, Bestechung |
| `Schutzgeld` | Lokale, Bars, Eskalations-Drama |
| `Geldwäsche` | Banken, Anwälte, Casinos, Briefkastenfirmen |
| `Hehlerei` | Auto-Diebstahl, Werkstätten, Verstecke |

Auch Kombinationen erlaubt: `Hauptgeschäft Drogen, Nebenlinie Geldwäsche durch ein Tankstellen-Imperium.`

### Stadtteil + Farbe

- **Stadtteil** → KI nutzt das für realistische Locations
- **Farbe** → Visuelle Wiedererkennung in Cards + Embeds + Personal-Briefs

## Beziehungs-Setup für packende Story

Beziehungen sind das **wichtigste Story-Werkzeug** nach der Hintergrund-Story.

### Beziehungs-Typen

| Typ | Wirkung in KI |
|---|---|
| `rival` | Story-Treiber — KI nutzt aktiv als Gegner |
| `hostile` | Wie rival, aber härter — KI eskaliert direkter |
| `allied` | Verbündete — KI kann als Helfer einbauen |
| `business` | Partner — KI kann als Druckmittel oder Übergabeort einbauen |
| `neutral` | KI nutzt selten, eher zur Vermeidung |

### Notizen wichtig!

Die Notiz ist **viel wichtiger als der Typ**.

**Schlecht**:
> Vipers vs. MOB: rival

**Besser**:
> Vipers vs. MOB: rival — seit dem Hafenkrieg 2023, drei tote Vipers-Soldaten unbeantwortet, MOB-Lieutenant Carlos „der Schatten" Reyes ist namentlich für die Hits verantwortlich. Vipers haben Tribut auf seinen Kopf gesetzt, der noch nicht eingelöst wurde.

Die KI generiert daraus Aufträge wie „der Schatten muss seinen ersten Fehler machen" oder „ein Treffen, das nie stattfinden sollte, in einem Pier, der nicht mehr existiert".

### Faustregeln

- **Mindestens 2–3 Beziehungen pro Crew** — eine Crew ohne Beziehungen hat keine Story-Hooks
- **1 rival/hostile + 1 allied/business** ist die magische Mischung
- **Notizen mit Namen, Daten, Orten** funktionieren am besten
- **Symmetrische Notizen** auf beiden Seiten (Vipers vs. MOB UND MOB vs. Vipers) machen die Welt konsistent

## Auftrag-Workflows

### Workflow A — Frei generiert (Standard)

Schnellster Weg, beste Story-Konsistenz:

1. Crew-Detail → **Tab „KI generiert"**
2. **Provider** wählen (Anthropic empfohlen)
3. Optional: **Zusätzliche Hinweise** an die KI
   - z.B. *„Diesmal etwas mit dem Hafen, eskaliert von der letzten Mission"*
4. **Generieren** klicken
5. Draft prüfen, ggf. **🔁 Umformulieren** für neue Variante
6. **An Discord senden**

### Workflow B — Eigener Text umschreiben

Wenn du eine konkrete Idee hast, aber im Stil verschlüsseln willst:

1. **Tab „Eigenen Text umschreiben"**
2. Klartext eingeben:
   > *„Crew soll heute Abend um 21:00 einen Container am Hafen klauen. Inhalt: gefälschte Pässe. Wachen sind bestechlich. Brücke nach Algonquin innerhalb 30 Minuten."*
3. **Generieren** → KI verschlüsselt im RP-Stil
4. Ergebnis sollte beibehalten:
   - Zeit 21:00 (in Server-Fenster)
   - Hafen + Brücke
   - Wachen + Pässe (verschlüsselt als „Papiere die niemandem mehr gehören")
5. **An Discord senden**

### Workflow C — Manueller Text

Für Klartext mit konkreten Codes/Adressen/GPS:

1. **Tab „Manuell"**
2. Text direkt eingeben
3. **An Discord senden**

KI berührt den Text nicht. Personal-Brief wird trotzdem KI-generiert.

### Zusatzinfos

Werden **1:1 an den Auftrag angehängt**, KI berührt sie nicht. Ideal für:
- GPS-Koordinaten
- Codes für Eingaben in-game
- Spezifische Items
- IDs

### Countdown / Deadline

| Use-Case | Empfehlung |
|---|---|
| Quick-Action (Stealth, Heist) | 15–60 Min |
| Mehrteilige Aktion | 2–4 Std |
| Story-Auftrag mit RP-Vorbereitung | 1–2 Tage |
| „Schläfer"-Auftrag | bis 7 Tage |

Discord rendert `<t:UNIX:R>` automatisch als „in 2 Stunden" — aktualisiert sich live im Client.

### Scheduled Send

Pre-Setup während der Vorbereitungszeit, dann automatisch zur richtigen Zeit:

1. Draft erstellen, optional bearbeiten
2. **„Senden um"** Datum/Zeit wählen
3. Draft bleibt im System
4. Bot-Watcher (alle 30 s) sendet zum eingestellten Zeitpunkt

Ideal für **synchronisierte Massen-Tage** — alle Aufträge starten 20:00 Uhr, du bereitest sie um 18:00 vor.

## Personal-Planung

### Was du planen musst

Pro Crime-Crew (PvE-Aufträge) brauchst du:
1. **Mittler** (Quest-Geber) — wer übergibt den Auftrag
2. **NPCs** — wer im Auftrag mitspielt (Hafenmeister, Bankleiter, etc.)
3. **Locations** — wo wird gespielt
4. **Slot** — wann läuft das

Bei **PvP-Aufträgen** (Crew-vs-Crew) brauchst du **nur den Mittler** — der Rest sind Spieler.

### Mittler-Team-Setup (Empfehlung)

Sechs Personen reichen für ein 10-Tage-Event:

| Person | Mittler | NPC-Rollen (Rotation) |
|---|---|---|
| User (Big Boss) | **Big Boss** (Voice-Over Tag 6/8/10) | — |
| Team 1 | **Miguel** | #2 korrupter LCPD, #9 Politiker |
| Team 2 | **Maklerin** | #4 Bankleiter, #5 Restaurantchef |
| Team 3 | **Fixer** | #7 Mechaniker, #11 Trucker, #14 Doc |
| Team 4 | **Pater** | #13 Snitch, #6 Tankwart |
| Team 5 | **Witwe** | #15 Zivilist |
| Team 6 | **Skrupellose** | #3 LCPD-Detective, #12 Wachmann |

### Personal-Brief im Tool

Wird automatisch beim Mission-Generieren mitgemacht. Du musst nichts tun — beim Discord-Send landet er auch in deinem Spielleiter-Channel.

**Anpassungen im Dashboard-Widget:**
- **✎ bearbeiten** — Markdown-Editor
- **📋 Vorlage** — Tag 2/4/7/9/10 Massen-Auftrag-Templates laden
- **🤖 KI-Vorschlag** — neuer KI-Lauf mit dediziertem Prompt
- **📤 Posten** — manuelles Discord-Update

### Faustregel — wann ist Personal nötig?

| Auftragstyp | Personal? |
|---|---|
| Heist (Bank, Hafen, Laden) | ✅ Mittler + 2–4 NPCs |
| Schmuggel/Übergabe | ✅ Mittler + 2 NPCs |
| Bestechung | ✅ Mittler + 1–2 NPCs |
| Polit-Erpressung | ✅ Mittler + 2–3 NPCs |
| Verrat innerhalb Crew | ✅ nur Mittler |
| Rivalitäts-Eskalation | ✅ nur Mittler |
| Tribut-Einkassierung | ✅ Mittler + Zivil-Firmen (sind eh Spieler) |

KI macht das automatisch richtig — sie weiß: PvP → nur Mittler.

## Massen-Aufträge / Event-Tage

### Vorbereitung am Event-Tag

**3 Stunden vor Start:**
1. Story-Briefing für den Tag vorbereiten (in `EVENT_BRIEFINGS_MASS.md`)
2. Mittler-Briefing an Team verteilen (Discord-DM)
3. NPC-Rollen zuteilen
4. Locations checken (Server-Performance, andere Events?)

**1 Stunde vor Start:**
1. Dashboard öffnen → **„📢 Massen-Auftrag senden"**
2. Modus wählen (meist „KI generiert" für freie Generierung)
3. Vorschau prüfen, ggf. anpassen
4. **„Senden um"** auf Event-Start-Zeit setzen
5. **„An N senden"** → alle Drafts werden erstellt mit Schedule
6. Personal-Briefs erscheinen im Dashboard-Widget — letzte Anpassungen

**Zum Event-Start:**
- Bot sendet automatisch alle Aufträge zur eingestellten Zeit
- Personal-Briefs werden parallel im Spielleiter-Channel gepostet
- Du musst nur das Spielleiter-Team koordinieren

### Live-Steuerung während des Events

- **Dashboard** offen lassen — siehst Reaktionen live (5 s Polling)
- **Personal-Bedarf-Widget** — Browser-Notifications bei Updates
- **Crew-Detail** offen, wenn du gerade eine Crew live betreust
- **Boss-Feedback** im Info-Channel pollt der Bot — du kannst auch direkt im Discord lesen

### Nach dem Event

- **„📦 Alle archivieren"** im Dashboard → Snapshots werden gemacht, Discord wird aufgeräumt
- **Top 3 jetzt posten** auf der Ranking-Seite — Belohnungs-Embed
- **PDF-Export** der besten Missionen als Erinnerung an die Crews verteilen

## Ranking-Strategie

### Punkte-Mathematik im Klartext

Wenn eine Crew über das Event 10 Missionen bekommt:
- **5× 👍** = +10 Punkte
- **3× 👎** = −3 Punkte
- **2× ❌** = 0 Punkte
- **Total** = +7 Punkte

Bonus-Punkte kommen on top.

### Wann Bonus-Punkte vergeben?

| Anlass | Empfehlung |
|---|---|
| Außergewöhnliches Solo-RP | +2 bis +5 |
| Spielleiter-Lob für Story-Aktion | +5 |
| Tag-Sieger (siehe Top 3 Top 3) | +10 |
| Regelverstoß | −2 bis −5 |
| Cheat-Verdacht (Strafe ohne Ban) | −10 |

### Reset-Stichtag

Vor jedem neuen Event:
1. Ranking-Seite → **„🔄 Ranking zurücksetzen"** (doppelter Confirm)
2. `bonus_points = 0` für alle Crews
3. `ranking_reset_at` wird gesetzt
4. Im „Gesamt"-View zählen nur Missionen ab diesem Stichtag

**Vorteil:** Alte Daten bleiben in der DB (z.B. für Statistiken im 7/30-Tage-View), aber das aktuelle Ranking startet bei 0.

## Boss-Feedback-Workflow

### Was ist das

Pro Crew kannst du einen **Zusatzinfo-Channel** anlegen — Discord-Channel, in den der **Crew-Boss Klartext-Antworten** schreibt, die im Tool sichtbar werden.

### Use-Cases

- Boss sagt: *„Wir machen Plan B, treffen uns 22:30 am Pier 7"*
  → Du siehst das im Tool unter der Mission, kannst die KI-Folgeaufträge entsprechend anpassen
- Boss schickt ein **Beweisfoto** als Bild-Attachment
  → Erscheint inline im Tool
- Boss bittet um **Klärung** zu einem Auftrag
  → Du siehst es sofort, kannst per Discord-DM oder InGame reagieren

### Workflow

1. Crew-Detail → Crew anlegen mit `info_channel_id`
2. Boss schreibt im Info-Channel
3. Bot pollt (alle 5 s)
4. UI zeigt:
   - **Pulsing Border** auf Dashboard-Card
   - **Boss-Texte inline** unter der aktiven Mission im Crew-Detail

### Wichtig

- Boss-Texte werden **per Zeitfenster** zugeordnet:
  - Nach `sent_at` der aktuellen Mission
  - Vor `sent_at` der nächsten Mission
- Beim Archivieren werden die Texte **als Snapshot in der Mission gespeichert**, dann aus Discord gelöscht

## Häufige Fragen

### Wie schalte ich die KI-Generierung aus?

Verwende den **„Manuell"**-Modus pro Mission. Personal-Brief wird trotzdem KI-generiert, ist aber per **🤖 KI-Vorschlag** ablehnbar — du kannst auch leer lassen.

### Was wenn die KI gegen die Regeln verstößt (Zahlen ausschreibt, Server-Zeit ignoriert)?

Die KI-Output-Cleaner laufen automatisch. Wenn trotzdem was durchrutscht:
- Mission → **🔁 Umformulieren** klicken
- Oder den Text manuell editieren in der Textarea

Bei wiederholten Verstößen: System-Prompt verschärfen (Settings → System-Prompts).

### Wie kommen Bonus-Punkte für die Crew zustande?

Punkte = `approved × 2 + rejected × −1 + bonus_points`. Bonus ist die einzige Stellschraube außerhalb der Mission-Reaktionen.

### Was wenn ich versehentlich eine Mission gelöscht habe?

- **Archiv** zurück bringen: Archive-Page → **↺ Restore**
- **Endgültig gelöscht** (Purge): nicht wiederherstellbar
- **Discord-Posts gelöscht**: nicht wiederherstellbar (außer aus Discord-Audit-Log manuell)

### Wie viele Crews kann ich verwalten?

Praktisch unbegrenzt. Performance-Sweet-Spot: 20–30 aktive Crews. Über 50 wird das Dashboard etwas träge, weil alle Daten geladen werden.

### Welche KI-Modelle sind am besten?

- **Anthropic Claude Sonnet 4.5** — bestes Verhältnis Qualität/Preis, sehr guter Big-Boss-Stil
- **Anthropic Claude Opus 4** — beste Qualität, deutlich teurer
- **GPT-4o** — solider Alternativer, manchmal weniger atmosphärisch

### Wie sicher ist mein Bot-Token?

- In `.env` → wird per `.gitignore` ausgeschlossen
- Backend zeigt im UI nur „gesetzt: ja/nein"
- Bei Leak (z.B. versehentlich gepushed): sofort im Developer Portal regenerieren

### Was wenn der Bot offline ist?

- Aufträge können nicht versendet werden (Backend gibt 503 zurück)
- Personal-Auto-Post läuft nicht
- Boss-Feedback wird nicht gepollt
- **Restart**: `Restart-Service CrimeAutoBot` (Windows) bzw. systemd-equivalent

### Kann ich das Tool für andere Games als GTA-V nutzen?

Ja — das Tool ist **server-unabhängig**. Es nutzt keine FiveM/GTA-spezifischen APIs. Du kannst es für RedM, ARMA, eigene Custom-Server oder sogar nicht-Gaming-Communities einsetzen. Anpassen:
- Stadtteile → andere Bezeichnungen
- Crime-Business → eigene Kategorien
- System-Prompts → eigener Welt-Setting
- Mittler & NPC-Pool → eigene Charakter-Welt

## Nächste Schritte

- **[FEATURES.md](FEATURES.md)** — Komplette Feature-Liste
- **[API.md](API.md)** — Für Custom-Integrationen
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** — Bei Problemen
