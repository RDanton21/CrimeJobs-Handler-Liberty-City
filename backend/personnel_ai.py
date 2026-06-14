"""KI-Generierung und Templates für `personnel_brief` (Admin-internes
Personal-Briefing pro Mission).

- `NPC_POOL_PROMPT_DE`: hartcodierter Pool der 15 Archetypen + Mittler.
  Wird der Personnel-KI als Kontext mitgegeben, damit Vorschläge zum
  bestehenden Repertoire passen (nicht jedes Mal neue Rollen erfinden).
- `TEMPLATES`: 5 vordefinierte Massen-Auftrag-Briefs zum Quick-Pick im UI.
- `build_personnel_prompt()` + `generate_personnel_brief()`: Helper für
  KI-Aufruf, mit defensivem Fallback (nie hart blocken — Personal-Brief
  ist optional und manuell nachtragbar).
"""
from __future__ import annotations

from typing import Any


NPC_POOL_PROMPT_DE = """\
# Quest-NPC-Pool (Repertoire — bevorzugt aus dieser Liste wählen)

Mittler (6 — Spielleitung):
- Miguel (kalt, formell)
- Die Maklerin (charmant, gefährlich)
- Der Pater (leise, paternal)
- Der Fixer (pragmatisch, schnoddrig)
- Die Witwe (bitter, alt)
- Der Skrupellose (brutal, drohend)

Quest-NPC-Archetypen (15 — nummeriert, immer mit Nummer referenzieren):
1. Hafenmeister — Container, Schmuggel
2. Korrupter LCPD-Officer — Bestechung, Tipps
3. LCPD-Detective — Ermittlung, Druck
4. Bankkassierer / -leiter — Heists, Geldwäsche
5. Bar-/Restaurantchef — Tribut, Treffpunkt
6. Tankwart / Late-Night-Shop — Tribut, Augenzeuge
7. Werkstatt-Mechaniker — Fahrzeug-Verstecker, Hehler
8. Reporter / Journalist — Skandale, Sichtbarkeit
9. Stadtrat / Politiker — Polit-Mord, Bestechung
10. Anwalt / Geldwäscher — Saubermachen
11. Lieferant / Trucker — Stealth-Übergaben
12. Wachmann — Stealth-Hindernis
13. Informant / Snitch — Tipps, Aussage
14. „Kein-Fragen"-Arzt — Schussverletzungen
15. Geisel / Ziviler Statist — Heist, Entführung
"""


PERSONNEL_BRIEF_FORMAT_DE = """\
Format des Briefings (Markdown, deutsch, prägnant):

**Mittler:** <Mittler-Name> (passend zum Ton des Auftrags)

**Quest-NPCs:**
- N× #<Nr> <Archetype>
  → Funktion: <was die Rolle im Auftrag tut>
  → Location: <Ort/Stadtteil, passend zur Gang>
  → Kostüm: <Trigger>

**Slot:** <ungefähre Dauer + Zeitfenster>
**Team-Auslastung:** <Mittler + N NPC-Spieler in Rotation>

Regeln:
- Maximal 4 NPC-Rollen pro Mission, sonst wird's unspielbar
- Nutze NUR Archetypen aus dem Pool (mit Nummer)
- Locations sollen zur Gang (Stadtteil) passen, wenn bekannt
- Wenn der Auftrag rein Gang-vs-Gang ist (z. B. Verrats- oder Rivalitäts-Auftrag),
  KEINE NPCs erfinden — nur Mittler nennen und kurz begründen warum keine NPCs
- Keine Story-Wiederholung des Auftrags, NUR Personal-Planung
- Antwort ist NUR der Markdown-Brief, kein Vor- oder Nachtext
- AKTIONS-ZEITFENSTER für Slot: zwischen 17:00 und 02:00 (Server-Zeiten).
  Im Feld „Slot" IMMER Uhrzeiten aus diesem Fenster nennen, z.B. „22:00–23:30",
  „ab 19:00", „00:30–01:45". NIE Uhrzeiten wie „04:00", „08:00", „14:00".
- Zahlen IMMER als Ziffern, nie ausgeschrieben („2 NPC-Spieler" statt „zwei").
"""


def build_personnel_prompt(mission_text: str, crew_name: str, crew_district: str) -> str:
    """Baut den User-Prompt für die Personnel-KI."""
    district_line = f"Stadtteil der Gang: {crew_district}\n" if crew_district else ""
    return f"""\
{NPC_POOL_PROMPT_DE}

{PERSONNEL_BRIEF_FORMAT_DE}

---

Hier ist der Auftrag, für den du das Personal planen sollst:

Gang: {crew_name}
{district_line}
Auftragstext:
\"\"\"
{mission_text.strip()}
\"\"\"

Generiere jetzt das Personal-Briefing nach obigem Format.\
"""


async def generate_personnel_brief(
    provider: Any,
    mission_text: str,
    crew_name: str,
    crew_district: str,
    model: str | None = None,
) -> str:
    """Ruft die KI für einen Personal-Brief-Vorschlag.

    Defensiv: bei jedem Fehler leerer String zurück — Mission darf nicht
    blockieren, weil Personal-Generierung Bonus, nicht Pflicht ist.
    """
    if not mission_text or not mission_text.strip():
        return ""
    try:
        prompt = build_personnel_prompt(mission_text, crew_name, crew_district)
        # Eigenes Mini-System-Prompt für diesen Sub-Call — überschreibt das
        # Big-Boss-Prompt, sonst kommt wieder Auftragstext statt Personal-Plan.
        system = (
            "Du bist ein Spielleiter-Assistent für ein GTA-RP-Event. "
            "Du planst Personal (Mittler + NPCs) für Quest-Aufträge. "
            "Du schreibst ausschließlich kompakte Markdown-Briefings im "
            "vorgegebenen Format — keine Story, keine Auftragsbeschreibung, "
            "nur Personal-Planung."
        )
        text = await provider.generate(prompt, model=model, system_prompt=system)
        return (text or "").strip()
    except Exception:
        return ""


# ============================================================
# Templates — Quick-Pick für die 5 Massen-Aufträge
# ============================================================

TEMPLATES: list[dict] = [
    {
        "id": "tag2_tribut",
        "label": "Tag 2 — Der Tribut (Schutzgeld)",
        "content": """\
**Mittler:** Miguel (formell, kalt — „die Stimme")

**Quest-NPCs:**
- 3–5× Tribut-Pflichtige aus den **13 Zivil-Firmen**
  → Funktion: zahlen Schutzgeld, sind feste RP-Spieler
  → Location: deren jeweilige Firmen-Standorte
  → Kostüm: bereits eigene Charaktere

- 1× #5 Bar-/Restaurantchef ODER #6 Tankwart als „Widerständler"
  → Funktion: zahlt NICHT freiwillig — Eskalations-Spielraum
  → Location: an einem zentralen Ort im Gang-Revier
  → Kostüm: Schürze/Lokal-Logo bzw. Arbeitskleidung

- Optional: 1× #2 Korrupter LCPD
  → Funktion: erscheint als Drohbacking, wenn Widerständler hart wird

**Slot:** 60–90 Min, fließend zwischen 17:00 und 02:00 verteilt (1 Server-Abend)
**Team-Auslastung:** Miguel + 1 NPC-Spieler in Rotation (Widerständler + LCPD)\
"""
    },
    {
        "id": "tag4_stille",
        "label": "Tag 4 — Die Stille (Stealth)",
        "content": """\
**Mittler:** Der Fixer (pragmatisch, schnoddrig)

**Quest-NPCs (3 Lieferungen):**
- 1× #11 Lieferant ODER #4 Bankleiter ODER #10 Anwalt als Empfänger
  → Funktion: nimmt Lieferung still entgegen
  → Location: variiert pro Lieferung
  → Kostüm: passend zum Archetype

- 1× #12 Wachmann ODER #1 Hafenmeister als Hindernis
  → Funktion: Stealth-Patrouille, kein direkter Konflikt
  → Location: am Übergabe-Ort
  → Kostüm: Security-Uniform / Hi-Viz

- Optional: 1× #13 Snitch ODER #6 Tankwart als Augenzeuge
  → Funktion: könnte sehen, wäre Risiko-Vektor (für RP-Drama)

**Slot:** 45–60 Min pro Lieferung, gestaffelt über 2 Server-Abende (jeweils 17:00–02:00)
**Team-Auslastung:** Fixer + 2 NPC-Spieler in Rotation
**Hinweis:** Bei 21 Gangs × 3 Lieferungen nur 30 % Live-RP, Rest schriftlich + Gang-Eigen-NPCs\
"""
    },
    {
        "id": "tag7_verrat",
        "label": "Tag 7 — Der Verrat (privat an Top 3)",
        "content": """\
**Mittler:** Der Skrupellose (brutal-direkt, privat)

**Quest-NPCs:** KEINE — Ziel ist eine andere Spieler-Gang.
Das ist ein reiner Gang-vs-Gang-Auftrag, das Personal-Setup besteht
aus dem Mittler allein.

- Optional: 1× #13 Snitch
  → Funktion: „Wer hat geredet?"-Hebel falls die Top-3-Gang mauert
  → Location: später, falls Eskalation nötig

**Slot:** 3× ~20 Min Mittler-Einzelgespräch mit jeweils einer Top-3-Gang, im Server-Fenster 17:00–02:00
**Team-Auslastung:** **nur 1 Person** (Skrupellose). Geringster Personal-Tag.\
"""
    },
    {
        "id": "tag9_probe",
        "label": "Tag 9 — Die Probe (Rivalitäts-Eskalation)",
        "content": """\
**Mittler:** Miguel + Gang-Mittler (Rotation)

**Quest-NPCs:** KEINE — Spieler vs. Spieler.
Jede Gang bekommt privat ihre zugewiesene Rivalen-Gang aus
CREW_RELATIONS.md. Akteure sind ausschließlich Spieler-Gangs.

- Optional: 1× #3 LCPD-Detective
  → Funktion: „Hintergrund-Ermittler" — erhöht Druck
  → Location: streift sichtbar durch Revier-Konflikte

**Slot:** Übergaben in der ersten Server-Hälfte (17:00–21:00), Abschluss bis 02:00 des Folgetags
**Team-Auslastung:** Miguel + 1 NPC-Spieler für Schicht-Übergaben\
"""
    },
    {
        "id": "tag10_krone",
        "label": "Tag 10 — Die Krone (individueller Coup)",
        "content": """\
**Mittler:** Big Boss DIREKT (Voice-Over) + Gang-Mittler für Coup-Übergabe

**Quest-NPCs:** abhängig vom zugewiesenen Coup-Typ:

- **Bank-Heist:** #4 Kassierer + #4 Bankleiter + #15 Geisel + #2/#3 LCPD-Reaktion
- **Polit-Mord:** #9 Politiker + #12 Bodyguard + #8 Reporter
- **Großentführung:** #15 Opfer + #12 Wachmann
- **Geldwäsche-Schlag:** #10 Anwalt + #4 Bankier + #11 Geld-Kurier
- **Hafen-Heist:** #1 Hafenmeister + #12 Hafenwache + #11 Trucker
- **Drogen-Großschlag:** #14 „Doc" + #11 Lieferant + #13 Informant

**Slot:** 60–120 Min pro Gang, gestaffelt zwischen 19:00 und 02:00
**Team-Auslastung:** **maximum** — 4–6 Personen, jede in 2–3 Rollen rotierend
**Wichtig:** Coup-Typen pro Gang vorab festlegen (Rotation), damit nicht 21× Bank-Heist parallel läuft.

→ Konkreten Coup-Typ + NPCs in diesem Brief unten ergänzen.\
"""
    },
    {
        "id": "empty",
        "label": "Leer (Custom)",
        "content": """\
**Mittler:**

**Quest-NPCs:**
- 1× #<Nr> <Archetype>
  → Funktion:
  → Location:
  → Kostüm:

**Slot:**
**Team-Auslastung:**\
"""
    },
]
