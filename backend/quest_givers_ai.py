"""KI-Konsistenz-Check zwischen den aktuellen Mittlern (QUEST_GIVERS.md)
und der aktuellen Event-Story (EVENT_BRIEFING + TIMELINE + CITY_PUBLIC_BRIEFING).

Liefert einen strukturierten Markdown-Report + maschinenlesbaren
Recommendations-Block, den das Frontend pro Empfehlung als „Anwenden"-
Button anbieten kann.
"""
from __future__ import annotations

import json
import re
from typing import Any


_SYSTEM_PROMPT = (
    "Du bist ein präziser Konsistenz-Prüfer für RPG-Story-Dokumentation. "
    "Du vergleichst Charakter-Profile mit der Storyline und beurteilst, "
    "ob sie noch zusammenpassen. Du gibst klare, kompakte Bewertungen "
    "mit konkreten Vorschlägen — keine Story-Spekulation, keine Schwärmerei. "
    "Antwortest ausschließlich auf Deutsch und ausschließlich im "
    "geforderten Markdown-Format."
)


def _strip_outer_codefence(text: str) -> str:
    """Entfernt einen umschließenden ```markdown ... ``` (oder ```...```)
    Codefence-Wrapper, falls die KI den ganzen Report da reingepackt hat.
    Sonst rendert marked.js den gesamten Inhalt als Code-Block (monospace,
    sichtbare ##-Syntax)."""
    text = text.strip()
    m = re.match(r"^```(?:markdown|md|)\s*\n", text, re.IGNORECASE)
    if not m:
        return text
    text = text[m.end():]
    if text.rstrip().endswith("```"):
        text = text.rstrip()[:-3].rstrip()
    return text


def _parse_recommendations_from_bullets(report: str) -> list[dict]:
    """Fallback wenn KI keinen JSON-Block liefert: parse die
    `## Empfohlene nächste Schritte`-Sektion und mache aus jedem
    Bullet-Point eine Recommendation. So sieht der User auch dann
    Apply-Buttons, wenn die strukturierte Antwort fehlt."""
    m = re.search(
        r"##\s+Empfohlene\s+n[äa]chste\s+Schritte\s*\n+(.*?)(?:\n##\s+|\Z)",
        report, re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return []
    block = m.group(1)
    recs: list[dict] = []
    for line in block.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Bullet-Points: -, *, •, 1., 2., …
        m_bullet = re.match(r"^(?:[-*•]|\d+[.)])\s+(.*)$", line)
        if not m_bullet:
            continue
        instruction = m_bullet.group(1).strip()
        # Markdown-Fett-Marker und überflüssige Whitespaces wegnehmen
        clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", instruction)
        if len(clean) < 10:
            continue
        # Title = die ersten 6 Wörter (max 60 Zeichen)
        words = clean.split()
        title = " ".join(words[:6])
        if len(title) > 60:
            title = title[:57] + "…"
        recs.append({
            "title": title,
            "instruction": clean,
            "target": "Empfehlung",
        })
    return recs


def _extract_recommendations_json(raw: str) -> tuple[str, list]:
    """Versucht 3 Strategien, das Recommendations-JSON aus der KI-Antwort
    rauszuholen. Liefert (report_ohne_json, recommendations_list). Wenn nichts
    geparst werden kann, bleibt der Report unverändert und die Liste leer.

    1. `<recommendations_json>...</recommendations_json>` (Soll-Format)
    2. ```json ... ``` Codefence
    3. Nacktes JSON-Array `[ {...} ]` am Ende des Texts, balanced gesucht
    """
    # Strategie 1: XML-artiger Tag (Soll-Format aus dem Prompt)
    m = re.search(
        r"<recommendations_json>\s*(.*?)\s*</recommendations_json>",
        raw, re.DOTALL | re.IGNORECASE,
    )
    if m:
        try:
            recs = json.loads(m.group(1))
            if isinstance(recs, list):
                return raw[:m.start()].rstrip(), recs
        except json.JSONDecodeError:
            pass

    # Strategie 2: ```json ... ``` Codefence
    m = re.search(
        r"```json\s*\n(.*?)\n\s*```",
        raw, re.DOTALL | re.IGNORECASE,
    )
    if m:
        try:
            recs = json.loads(m.group(1))
            if isinstance(recs, list):
                return raw[:m.start()].rstrip(), recs
        except json.JSONDecodeError:
            pass

    # Strategie 3: nacktes [ ... ] am Ende. Balanciert von hinten suchen.
    text = raw.rstrip()
    if text.endswith("]"):
        depth = 0
        start_idx = None
        for i in range(len(text) - 1, -1, -1):
            ch = text[i]
            if ch == "]":
                depth += 1
            elif ch == "[":
                depth -= 1
                if depth == 0:
                    start_idx = i
                    break
        if start_idx is not None:
            candidate = text[start_idx:]
            try:
                recs = json.loads(candidate)
                if isinstance(recs, list) and recs and isinstance(recs[0], dict):
                    return text[:start_idx].rstrip(), recs
            except json.JSONDecodeError:
                pass

    return raw, []


def build_consistency_prompt(story_md: str, givers_md: str) -> str:
    return f"""\
# Aktuelle Event-Story

{story_md.strip()}

---

# Aktuelle Mittler (Quest-Geber)

{givers_md.strip()}

---

# Aufgabe

Prüfe, ob die aktuellen Mittler stilistisch und inhaltlich noch zur
oben beschriebenen Story passen. Beurteile jeden Mittler einzeln und
gib am Ende Vorschläge für Lücken.

Status-Bewertung pro Mittler:
- ✅ **passt** — keine Änderung nötig
- ⚠️ **Anpassung empfohlen** — kleinere Tweaks (welche?)
- ❌ **ersetzen** — passt nicht mehr (Alternative vorschlagen)

# Format der Antwort (KEIN Vor- oder Nachtext, NUR dieser Markdown-Block):

## Gesamtbewertung

<1–3 Sätze: passen die Mittler insgesamt zur Story? Wo gibt es Spannungen?>

## Pro Mittler

### 1. <Name> — <Status-Emoji> <Status>

<Begründung in 1–3 Sätzen, konkret auf die Story bezogen.>

**Vorschlag:** <Bei „Anpassung empfohlen" oder „ersetzen": konkreter Text/Alternative. Bei „passt": Zeile weglassen.>

### 2. <Name> — ...

(usw. für ALLE Mittler aus der QUEST_GIVERS.md — auch wenn es mehr oder weniger als 6 sind)

## Zusätzliche Mittler-Ideen

<0–3 Vorschläge für Mittler-Typen, die die aktuelle Story bräuchte, aber noch nicht da sind. Jeweils mit Name, Rolle und Stil-Stichworten.>

## Empfohlene nächste Schritte

<2–4 Bullet-Points: welche konkreten Edits an QUEST_GIVERS.md würdest du jetzt machen?>

# Maschinenlesbarer Block (PFLICHT — am ENDE der Antwort)

Nach dem menschenlesbaren Markdown-Report HÄNGE folgenden Block an, EXAKT
in dieser Form (kein anderes Format, keine Erklärung drumherum):

<recommendations_json>
[
  {{
    "title": "<Kurzer Titel der Empfehlung, max 60 Zeichen>",
    "instruction": "<Konkrete Edit-Anweisung an die KI: was in QUEST_GIVERS.md ändern, ergänzen oder ersetzen. 2–4 Sätze, spezifisch genug, dass ein anderer Bearbeiter die Änderung umsetzen könnte. Bei NEUEN Mittlern: Name, Rolle, Stil, Sprechweise, Erscheinung, Schwerpunkt, Beziehung zu Gangs, typische Aufträge und eine Catchphrase angeben.>",
    "target": "<Name des betroffenen Mittlers ODER 'neuer Mittler' ODER 'gesamtes Dokument'>"
  }}
]
</recommendations_json>

# Was MUSS als Recommendation in den JSON-Block?

Liefere für JEDE der folgenden Situationen einen eigenen JSON-Eintrag:

1. JEDER Mittler mit Status „⚠️ Anpassung empfohlen" — instruction beschreibt,
   was am bestehenden Mittler-Abschnitt zu ändern ist.
2. JEDER Mittler mit Status „❌ ersetzen" — instruction beschreibt, durch
   welchen neuen Mittler er ersetzt wird (mit allen Feldern).
3. JEDE zusätzliche Mittler-Idee aus dem Abschnitt „Zusätzliche Mittler-Ideen"
   bekommt einen EIGENEN JSON-Eintrag mit instruction
   „Füge einen neuen Mittler '<Name>' am Ende der Mittler-Liste in
   QUEST_GIVERS.md hinzu, im selben Markdown-Format wie die bestehenden
   Mittler (## Nummer. Name — „Spitzname", Rolle, Stil, Sprechweise,
   Erscheinung, Schwerpunkt, Beziehung zu Gangs, Typische Aufträge,
   Catchphrase). Nutze folgende Eckdaten: <konkrete Story-Anker, Rolle,
   Stil>."
4. JEDER konkrete „Empfohlene nächste Schritte"-Bullet, der noch nicht
   durch 1–3 abgedeckt ist.

Mittler mit Status „✅ passt" bekommen KEINEN Eintrag.

Anzahl: typischerweise 2–8 Einträge. Wenn alles perfekt sitzt: `[]`.

# Regeln

- Sprache: Deutsch (auch im JSON-Block in den Texten)
- Konkret bleiben, keine Story-Spekulation jenseits der gelieferten Files
- Bei „passt" reicht eine kurze Begründung — keine Vorschlag-Zeile
- Bei „Anpassung empfohlen" / „ersetzen" / „neuer Mittler" IMMER konkret werden
- JSON muss valides JSON sein (keine Trailing-Commas, Strings mit "")
- Der `<recommendations_json>`-Block kommt IMMER am Ende, KEIN Text danach
"""


async def check_quest_givers_consistency(
    provider: Any,
    story_md: str,
    givers_md: str,
    model: str | None = None,
) -> tuple[str, list[dict]]:
    """Ruft die KI für den Konsistenz-Check.

    Returns: (markdown_report, recommendations_list)
    Der markdown_report ist der menschlich lesbare Teil ohne den JSON-Block.
    Die recommendations_list ist eine Liste von {title, instruction, target}-Dicts.

    Defensiv: bei Fehler wird die Exception nach oben gereicht. Wenn der
    JSON-Block fehlt oder kaputt ist, wird die Liste leer zurückgegeben —
    der Markdown-Report ist trotzdem nutzbar."""
    prompt = build_consistency_prompt(story_md, givers_md)
    raw = await provider.generate(prompt, model=model, system_prompt=_SYSTEM_PROMPT)
    raw = (raw or "").strip()

    # Recommendations-JSON extrahieren (3-Strategie-Parser)
    report, raw_recs = _extract_recommendations_json(raw)

    # Normalisieren: nur Dicts mit erwarteten Keys, Strings trimmen
    recommendations: list[dict] = []
    for r in raw_recs:
        if not isinstance(r, dict):
            continue
        title = str(r.get("title", "")).strip()
        instruction = str(r.get("instruction", "")).strip()
        target = str(r.get("target", "")).strip()
        if title and instruction:
            recommendations.append({
                "title": title[:200],
                "instruction": instruction[:2000],
                "target": target[:200],
            })

    # Codefence-Wrapper entfernen, falls die KI den ganzen Report gewrappt hat
    report = _strip_outer_codefence(report)

    # Fallback: wenn JSON-Recommendations leer sind, aus den
    # "Empfohlene nächste Schritte"-Bullet-Points im Report ableiten.
    # So sieht der User auch dann Apply-Buttons, wenn die KI das
    # strukturierte Format verfehlt hat.
    if not recommendations:
        recommendations = _parse_recommendations_from_bullets(report)

    return report, recommendations


_APPLY_SYSTEM_PROMPT = (
    "Du bist ein präziser Dokumenten-Editor für RPG-Story-Markdown. "
    "Du nimmst eine bestehende Markdown-Datei und eine konkrete "
    "Edit-Anweisung. Du gibst die KOMPLETTE überarbeitete Datei zurück — "
    "kein Diff, keine Erklärung, kein Vorwort, kein Codefence. Du erhältst "
    "Stil, Format, Überschriften-Hierarchie und alle nicht betroffenen "
    "Abschnitte EXAKT bei. Du änderst NUR das, was die Anweisung verlangt. "
    "Die Antwort ist die neue Datei, fertig zum Speichern."
)


def build_apply_prompt(current_content: str, instruction: str,
                       story_context: str = "") -> str:
    story_block = ""
    if story_context.strip():
        story_block = f"""\
# Story-Kontext (zur Orientierung — NICHT verändern, NICHT ausgeben)

{story_context.strip()}

---
"""
    return f"""\
{story_block}
# Aktuelle Datei (QUEST_GIVERS.md)

{current_content}

---

# Edit-Anweisung

{instruction}

---

# Aufgabe

Wende die obige Edit-Anweisung auf die Datei an. Gib die KOMPLETTE neue
Datei zurück. Keine Erklärung, kein Codefence, kein Vorwort, kein
Nachsatz. NUR der neue Datei-Inhalt — fertig zum Speichern unter
`docs/QUEST_GIVERS.md`.

Behalte das bestehende Markdown-Format, die Emoji-Verwendung, die
Überschriften-Hierarchie und alle nicht betroffenen Abschnitte EXAKT bei.
"""


async def apply_recommendation(
    provider: Any,
    current_content: str,
    instruction: str,
    story_context: str = "",
    model: str | None = None,
) -> str:
    """Wendet eine einzelne Edit-Anweisung auf QUEST_GIVERS.md an und gibt
    den NEUEN Datei-Inhalt zurück (nicht gespeichert — das macht das
    Frontend nach User-Bestätigung)."""
    prompt = build_apply_prompt(current_content, instruction, story_context)
    text = await provider.generate(prompt, model=model, system_prompt=_APPLY_SYSTEM_PROMPT)
    text = (text or "").strip()
    # Falls die KI doch einen Codefence drum gemacht hat, abschneiden
    if text.startswith("```"):
        # Erste Zeile (```markdown / ```md / ```) wegnehmen
        lines = text.split("\n", 1)
        text = lines[1] if len(lines) > 1 else ""
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()
