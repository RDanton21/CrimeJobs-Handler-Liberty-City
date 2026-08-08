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

import re
from typing import Any


def _force_slot(brief: str, slot: str) -> str:
    """Ueberschreibt die '**Slot:**'-Zeile im Personal-Brief mit einem
    vorgegebenen Zeitfenster (deterministisch, unabhaengig vom KI-Vorschlag)."""
    slot = (slot or "").strip()
    if not slot or not brief:
        return brief
    line = f"**Slot:** {slot}"
    if re.search(r"(?mi)^\s*\*\*Slot:\*\*.*$", brief):
        return re.sub(r"(?mi)^\s*\*\*Slot:\*\*.*$", line, brief, count=1)
    # keine Slot-Zeile vorhanden -> vor Team-Auslastung einfuegen, sonst anhaengen
    if re.search(r"(?mi)^\s*\*\*Team-Auslastung", brief):
        return re.sub(r"(?mi)^(\s*\*\*Team-Auslastung)", line + r"\n\1", brief, count=1)
    return brief.rstrip() + "\n" + line


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
Format des Briefings (Markdown, deutsch, ÜBERSICHTLICH & knapp):

**Sektor Questgeber**

**N× <kurzer Rollen-Titel>**
• Funktion: <ein knapper Satz>
• Location: <Ort/Stadtteil>
• Kostüm: <Trigger>

*(weitere Rollen nach demselben Muster, je durch EINE Leerzeile getrennt)*

**Slot:** <Zeitfenster>
**Team-Auslastung:** <N Questgeber in Rotation>

Regeln:
- KEINE „Mittler"-Zeile, keine Charakter-Beschreibungen, keine Story, keine
  Auftragsbeschreibung — NUR die Personal-Planung.
- Maximal 4 NPC-Rollen pro Mission, sonst wird's unspielbar.
- Rollen-Titel KURZ und konkret — EIN Begriff (z.B. „Tankwart", „Informant"),
  KEINE Schrägstrich-Listen wie „Tankwart / 24/7 Shops / Taco Wagen" und KEINE
  Archetyp-Nummer (#6 o.ä.) im Titel.
- Nutze intern nur Rollen aus dem Archetyp-Pool, gib sie aber sauber benannt aus.
- Genau drei Bullets pro Rolle (Funktion, Location, Kostüm) — je EINE knappe Zeile.
- Locations sollen zur Gang (Stadtteil) passen, wenn bekannt.
- Wenn der Auftrag rein Gang-vs-Gang ist (Verrat/Rivalität): KEINE NPCs — nur eine
  kurze Zeile, warum keine NPCs nötig sind.
- Antwort ist NUR der Markdown-Brief, kein Vor- oder Nachtext.
- AKTIONS-ZEITFENSTER für Slot: zwischen 17:00 und 02:00 (Server-Zeiten).
  Im Feld „Slot" IMMER Uhrzeiten aus diesem Fenster nennen, z.B. „22:00–23:30",
  „ab 19:00", „00:30–01:45". NIE Uhrzeiten wie „04:00", „08:00", „14:00".
- Zahlen IMMER als Ziffern, nie ausgeschrieben („2 Questgeber" statt „zwei").
- Rollen-Zeile IMMER mit „×" direkt nach der Anzahl: „3× Tankwart", NIE „3 Tankwart".
"""


def build_personnel_prompt(mission_text: str, crew_name: str, crew_district: str,
                           slot: str = "") -> str:
    """Baut den User-Prompt für die Personnel-KI."""
    district_line = f"Stadtteil der Gang: {crew_district}\n" if crew_district else ""
    slot_line = (
        f"VORGEGEBENER SLOT: Nutze im Feld 'Slot' EXAKT dieses Zeitfenster: {slot.strip()}\n"
        if slot and slot.strip() else ""
    )
    return f"""\
{NPC_POOL_PROMPT_DE}

{PERSONNEL_BRIEF_FORMAT_DE}

---

Hier ist der Auftrag, für den du das Personal planen sollst:

Gang: {crew_name}
{district_line}{slot_line}Auftragstext:
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
    slot: str = "",
) -> str:
    """Ruft die KI für einen Personal-Brief-Vorschlag.

    Defensiv: bei jedem Fehler leerer String zurück — Mission darf nicht
    blockieren, weil Personal-Generierung Bonus, nicht Pflicht ist.

    `slot`: vorgegebenes Zeitfenster — wird der KI mitgegeben UND danach
    deterministisch in die „Slot:"-Zeile geschrieben.
    """
    if not mission_text or not mission_text.strip():
        return ""
    try:
        prompt = build_personnel_prompt(mission_text, crew_name, crew_district, slot=slot)
        # Eigenes Mini-System-Prompt für diesen Sub-Call — überschreibt das
        # Big-Boss-Prompt, sonst kommt wieder Auftragstext statt Personal-Plan.
        system = (
            "Du bist ein Spielleiter-Assistent für ein GTA-RP-Event. "
            "Du planst das NPC-/Questgeber-Personal für Quest-Aufträge. "
            "Du schreibst ausschließlich kompakte, übersichtliche Markdown-"
            "Briefings im vorgegebenen Format — keine Mittler-Zeile, keine "
            "Story, keine Auftragsbeschreibung, nur Personal-Planung."
        )
        text = await provider.generate(prompt, model=model, system_prompt=system, max_tokens=1800)
        return _force_slot((text or "").strip(), slot)
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
**Sektor Questgeber**

**3× Tribut-Pflichtige** (aus den 13 Zivil-Firmen)
• Funktion: zahlen Schutzgeld, feste RP-Spieler
• Location: eigene Firmen-Standorte
• Kostüm: eigene Charaktere

**1× Widerständler**
• Funktion: zahlt NICHT freiwillig — Eskalations-Spielraum
• Location: zentraler Ort im Gang-Revier
• Kostüm: Schürze/Lokal-Logo oder Arbeitskleidung

**1× Korrupter Cop** (optional)
• Funktion: Drohbacking, wenn der Widerständler hart wird
• Location: taucht bei Eskalation auf
• Kostüm: LCPD-Uniform

**Slot:** 60–90 Min, fließend zwischen 17:00 und 02:00
**Team-Auslastung:** 2 Questgeber in Rotation\
"""
    },
    {
        "id": "tag4_stille",
        "label": "Tag 4 — Die Stille (Stealth)",
        "content": """\
**Sektor Questgeber** (3 Lieferungen)

**1× Empfänger**
• Funktion: nimmt die Lieferung still entgegen
• Location: variiert pro Lieferung
• Kostüm: unauffällig, zivil

**1× Wache**
• Funktion: Stealth-Patrouille, kein direkter Konflikt
• Location: am Übergabe-Ort
• Kostüm: Security-Uniform / Hi-Viz

**1× Augenzeuge** (optional)
• Funktion: könnte etwas sehen — Risiko-Vektor fürs RP
• Location: in der Nähe des Übergabe-Orts
• Kostüm: zivil

**Slot:** 45–60 Min pro Lieferung, gestaffelt über 2 Abende (17:00–02:00)
**Team-Auslastung:** 2 Questgeber in Rotation\
"""
    },
    {
        "id": "tag7_verrat",
        "label": "Tag 7 — Der Verrat (privat an Top 3)",
        "content": """\
**Sektor Questgeber** — KEINE.
Reiner Gang-vs-Gang-Auftrag: Ziel ist eine andere Spieler-Gang, kein NPC-Personal nötig.

**1× Snitch** (optional)
• Funktion: „Wer hat geredet?"-Hebel, falls die Gegenseite mauert
• Location: später, nur bei Eskalation
• Kostüm: zivil

**Slot:** 3× ~20 Min Einzelgespräche mit je einer Top-3-Gang, im Fenster 17:00–02:00
**Team-Auslastung:** minimal — nur bei Bedarf 1 Questgeber (Snitch)\
"""
    },
    {
        "id": "tag9_probe",
        "label": "Tag 9 — Die Probe (Rivalitäts-Eskalation)",
        "content": """\
**Sektor Questgeber** — KEINE.
Spieler vs. Spieler: jede Gang bekommt privat ihre Rivalen-Gang zugewiesen.

**1× LCPD-Detective** (optional)
• Funktion: Hintergrund-Ermittler — erhöht den Druck
• Location: streift sichtbar durch die Revier-Konflikte
• Kostüm: ziviler Ermittler / LCPD

**Slot:** Übergaben in der ersten Server-Hälfte (17:00–21:00), Abschluss bis 02:00
**Team-Auslastung:** 1 Questgeber für Schicht-Übergaben\
"""
    },
    {
        "id": "tag10_krone",
        "label": "Tag 10 — Die Krone (individueller Coup)",
        "content": """\
**Sektor Questgeber** — abhängig vom zugewiesenen Coup-Typ (unten konkretisieren):

• **Bank-Heist:** 2× Kassierer/Bankleiter · 1× Geisel · LCPD-Reaktion
• **Polit-Mord:** 1× Politiker · 1× Bodyguard · 1× Reporter
• **Großentführung:** 1× Opfer · 1× Wachmann
• **Geldwäsche-Schlag:** 1× Anwalt · 1× Bankier · 1× Geld-Kurier
• **Hafen-Heist:** 1× Hafenmeister · 1× Hafenwache · 1× Trucker
• **Drogen-Großschlag:** 1× „Doc" · 1× Lieferant · 1× Informant

**Slot:** 60–120 Min pro Gang, gestaffelt zwischen 19:00 und 02:00
**Team-Auslastung:** hoch — 4–6 Personen, je in 2–3 Rollen rotierend\
"""
    },
    {
        "id": "empty",
        "label": "Leer (Custom)",
        "content": """\
**Sektor Questgeber**

**N× <Rollen-Titel>**
• Funktion:
• Location:
• Kostüm:

**Slot:**
**Team-Auslastung:**\
"""
    },
]
