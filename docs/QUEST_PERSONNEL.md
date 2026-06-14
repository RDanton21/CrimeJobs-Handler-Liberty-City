# Personal-Bedarf — NPC-Pool & Team-Setup

Zentrale Referenz für die **Quest-NPCs** innerhalb der Aufträge — also
NICHT die Mittler (Miguel, Maklerin, etc., siehe `QUEST_GIVERS.md`),
sondern die Personen, die in den Aufträgen vorkommen: Hafenmeister,
Bankkassierer, korrupter Cop, etc. Pro Mission wird im Admin-Panel ein
`personnel_brief`-Feld gepflegt — diese Datei ist die **Quelle** für die
Archetypen, aus denen jeder Brief schöpft.

Wird sichtbar:
- im **Mission-Detail** auf der Crew-Seite
- im **Dashboard-Widget „🎭 Personal-Bedarf — nächste 24 h"** mit Live-Update
- bei Browser-Notification, wenn sich was ändert

---

## 3 Personal-Ebenen

| Ebene | Wer | Wo dokumentiert |
|---|---|---|
| **A — Mittler** | 5–6 Personen (User + Team) als Quest-Geber | `QUEST_GIVERS.md` |
| **B — Quest-NPCs** | Zielpersonen / Beteiligte im Auftrag | diese Datei |
| **C — Eigene Crew-Member** | Spieler der Crime-Gang | regeln die Crews selbst |

Du planst nur A + B.

---

## NPC-Pool — 15 Archetypen

Repertoire, das du einmal mit deinem Team festlegst. Danach werden Rollen
nur noch zugeteilt, nicht neu erfunden. Kostüm-Triggers in der letzten
Spalte machen den Charakter-Wechsel ohne langen Umzieh-Aufwand.

| # | Archetype | Typischer Einsatz | Kostüm-Trigger |
|---|---|---|---|
| 1 | **Hafenmeister** | Container-Lieferungen, Schmuggel | Hi-Viz-Weste, Klemmbrett |
| 2 | **Korrupter LCPD-Officer** | Bestechung, Tipps verkaufen | Uniform |
| 3 | **LCPD-Detective** | Ermittlung, Snitch-Druck | Trenchcoat, Marke |
| 4 | **Bankkassierer / -leiter** | Heists, Geldwäsche | Hemd, Krawatte |
| 5 | **Bar-/Restaurantchef** | Tribut, Treffpunkt-Vermittlung | Schürze, Lokal-Logo |
| 6 | **Tankwart / Late-Night-Shop** | Tribut, Augenzeuge, Schmuggel | Arbeitskleidung |
| 7 | **Werkstatt-Mechaniker** | Fahrzeuge verstecken, Hehler | Overall, ölige Hände |
| 8 | **Reporter / Journalist** | Sichtbarkeits-Aktionen, Verrats-Story | Notizblock, Mikrofon |
| 9 | **Stadtrat / Politiker** | Polit-Mord, Bestechung | Anzug, Anstecker |
| 10 | **Anwalt / Geldwäscher** | Saubermachen, Drogengeld einschleusen | Aktenkoffer |
| 11 | **Lieferant / Trucker** | Stealth-Übergaben, Hijacking | Trucker-Cap, Klemmbrett |
| 12 | **Wachmann** (Lager/Hafen/Privat) | Stealth-Hindernis, Bestechung | Security-Uniform, Walkie |
| 13 | **Informant / Snitch** | Tipps geben, später aussagen | unauffällig |
| 14 | **„Kein-Fragen"-Arzt** | Schussverletzungen, Drogen | Kittel oder Privat |
| 15 | **Geisel / Ziviler Statist** | Bank-Heist, Entführung | beliebig |

---

## Team-Setup für das 10-Tage-Event

| Person | Mittler-Hauptrolle | Sekundär-NPC-Rollen (Rotation) |
|---|---|---|
| User (Big Boss) | **Big Boss** (Tag 6/8/10) | — |
| Team 1 | **Miguel** | #2 korrupter LCPD, #9 Politiker |
| Team 2 | **Maklerin** | #4 Bankleiter, #5 Restaurantchef, #10 Anwalt |
| Team 3 | **Fixer** | #7 Mechaniker, #11 Trucker, #14 „Doc" |
| Team 4 | **Pater** | #13 Snitch, #6 Tankwart |
| Team 5 | **Witwe** | #15 Zivilist, #6 Tankwart (alternierend mit Team 4) |
| Team 6 | **Skrupellose** | #3 LCPD-Detective, #12 Wachmann |

→ **6 Personen reichen** für das gesamte 10-Tage-Event, wenn rotiert wird.

---

## Standard-Brief-Format (Markdown)

Jeder `personnel_brief` im Tool sollte dieser Struktur folgen — Pflege ist
einfacher und der Live-Feed bleibt scannbar.

```
**Mittler:** Der Fixer (Team-Mitglied: Marco)

**Quest-NPCs:**
- 1× #1 Hafenmeister
  → Funktion: bestochen werden, Container 47 freigeben
  → Location: Pier 3, Dukes Hafen
  → Kostüm: Hi-Viz + Klemmbrett

- 2× #12 Wachmann
  → Funktion: Patrouille am Lagerhaus (Stealth-Hindernis)
  → Location: „Broker Logistics" Lagerhaus
  → Kostüm: Security-Uniform + Walkie

**Slot:** ~ 60 Min, ab 22:00
**Team-Auslastung:** Fixer + 2 NPC-Spieler in Rotation
```

---

## Pro Massen-Auftrag — Personal-Übersicht

### Tag 2 — „Der Tribut" (08.08.2026)

- **Mittler:** Miguel
- **Quest-NPCs:** 5–7 Tribut-Pflichtige pro Crew. Die **13 Zivil-Firmen**
  fungieren als Haupt-Tribut-Pflichtige (sind eh Spieler). Zusätzlich
  pro Crew 1–2 „Widerständler"-NPCs aus dem Pool (#5 Bar/Restaurant,
  #6 Tankwart, #7 Mechaniker).
- **Optional:** 1× #2 Korrupter LCPD für Crews, die Drohbacking brauchen
- **Team-Bedarf:** ~ 2 Personen (Miguel + 1 NPC-Spieler, rotierend)

### Tag 4 — „Die Stille" (10.08.2026)

3 Stealth-Lieferungen pro Crew.

- **Mittler:** Der Fixer
- **Quest-NPCs pro Lieferung:**
  - 1× **Empfänger** (#11 Lieferant, #4 Bankleiter, #10 Anwalt — variiert)
  - 1× **Wachmann/Hafenmeister** als Hindernis (#1, #12)
  - Optional: 1× **Augenzeuge** (#6 Tankwart, #13 Snitch) als Risiko-Vektor
- **Team-Bedarf:** ~ 3 Personen (Fixer + 2 NPC-Spieler in Rotation)
- **Workflow:** 30 % der Crews Live-RP, 70 % bekommen Auftrag schriftlich +
  improvisieren mit eigenen Crew-Membern als NPCs

### Tag 7 — „Der Verrat" (13.08.2026)

Privat an Top-3 — Sabotage einer schwächeren Crew.

- **Mittler:** Der Skrupellose (privat, 3× hintereinander mit Top-3)
- **Quest-NPCs:** **Keine** — Ziel ist eine andere Spieler-Crew
- **Optional:** 1× #13 Snitch als „Wer hat geredet?"-Hebel
- **Team-Bedarf:** **nur 1 Person** (Skrupellose). Geringster Personal-Tag.

### Tag 9 — „Die Probe" (15.08.2026)

Rivalitäts-Eskalation — jede Crew gegen eine zugewiesene Rivalen-Crew.

- **Mittler:** Miguel + Crew-Mittler (privat Rivalitäts-Info übergeben)
- **Quest-NPCs:** **Keine** — Spieler vs. Spieler
- **Optional:** 1× #3 LCPD-Detective als „Hintergrund-Ermittler" zur Druck-Erhöhung
- **Team-Bedarf:** ~ 2 Personen (Miguel + 1 für Schicht-Übergaben)

### Tag 10 — „Die Krone" (16.08.2026)

Individueller Coup pro Crew — **personal-intensivster Tag**.

| Coup-Typ | NPC-Bedarf |
|---|---|
| Bank-Heist | #4 Kassierer + #4 Bankleiter + #15 Geisel + #2/#3 LCPD-Reaktion |
| Polit-Mord | #9 Politiker + #12 Bodyguard + #8 Reporter (Folge-Skandal) |
| Großentführung | #15 Opfer (Family / Anwalt / Mätresse) + #12 Wachmann |
| Geldwäsche-Schlag | #10 Anwalt + #4 Bankier + #11 Geld-Kurier |
| Hafen-Heist | #1 Hafenmeister + #12 Hafenwache + #11 Trucker |
| Drogen-Großschlag | #14 „Doc" + #11 Lieferant + #13 Informant |

- **Mittler:** Big Boss direkt (Voice-Over) + Crew-Mittler für individuelle Übergaben
- **Team-Bedarf:** **maximum** — 4–6 Personen, jede in 2–3 Rollen rotierend
- **Wichtig:** Coup-Typen pro Crew vorab festlegen (Rotation), damit nicht 21× Bank-Heist gleichzeitig läuft

---

## Live-Update-Mechanik

- Backend stempelt `personnel_updated_at` bei jeder Änderung
- Dashboard pollt `/api/dashboard/personnel?hours=24` alle 30 s
- Bei ETag-Änderung: Toast unten rechts + Bell-Counter im Header + Browser-Notification (wenn aktiviert)
- Klick auf Bell oder Toast → springt zum Widget

So sind du und dein Team immer auf dem aktuellen Stand — auch wenn die
Grundstory nächste Woche überarbeitet wird oder ein anderes Team-Mitglied
Personal-Briefs während des Events anpasst.
