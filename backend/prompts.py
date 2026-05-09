from __future__ import annotations

from dataclasses import dataclass


SYSTEM_PROMPT = """Du bist Briefing-Autor für eine GTA-V-Liberty-City-Roleplay-Krimiserie.

Deine Aufträge sind kurz (3 bis 4 Sätze), kryptisch und atmosphärisch. Sie lesen sich wie verschlüsselte Nachrichten, die ein erfahrener Boss zwischen den Zeilen versteht. Schreibe nie offen "raubt", "tötet", "stehlt". Nutze stattdessen:

- Andeutungen, Code-Wörter, Synonyme aus dem Milieu
- Orte als Metaphern ("der alte Hafen schweigt nicht ewig", "die Glaskathedrale am Boulevard")
- Personen niemals beim Namen, sondern als Rollen ("der Buchhalter", "die Witwe von der 5th")
- Zeitangaben verschleiert ("wenn die Möwen schlafen", "vor dem dritten Glockenschlag")

Tonalität: hochwertig, literarisch, ein Hauch Noir. Kein Slang, kein Klischee. Wer es liest, soll spüren, dass dahinter Gewicht steht.

Format: nur den Auftragstext ausgeben. Keine Überschrift. Keine Erklärung. Keine Anrede. Drei bis vier Sätze.

Sprache: Deutsch."""


@dataclass
class MissionContext:
    crew_name: str
    crew_story: str
    related_crews: list[dict]  # [{name, story, relation_type, notes}]
    history: list[dict]        # [{content, status, created_at}]
    extra_instructions: str = ""


def build_user_prompt(ctx: MissionContext) -> str:
    parts: list[str] = []
    parts.append(f"## Gang\n{ctx.crew_name}")
    if ctx.crew_story:
        parts.append(f"\n## Hintergrund-Story\n{ctx.crew_story}")

    if ctx.related_crews:
        rel_lines = ["\n## Beziehungen zu anderen Gangs"]
        for r in ctx.related_crews:
            rel_lines.append(
                f"- **{r['name']}** ({r['relation_type']}): {r.get('notes', '').strip() or 'keine Notiz'}"
            )
            if r.get("story"):
                rel_lines.append(f"  Story-Notiz: {r['story'][:240]}")
        parts.append("\n".join(rel_lines))

    if ctx.history:
        hist = ["\n## Bisherige Aufträge (jüngste zuerst)"]
        for i, m in enumerate(ctx.history, start=1):
            status_label = {
                "approved": "👍 Erledigt",
                "rejected": "👎 Fehlgeschlagen",
                "cancelled": "❌ nicht ausführbar",
                "pending": "⏳ offen",
            }.get(m.get("status", ""), m.get("status", ""))
            hist.append(f"{i}. [{status_label}] {m.get('content', '')[:400]}")
        parts.append("\n".join(hist))

    parts.append(
        "\n## Verzweigung"
        "\n- Letzter Auftrag '👍 Erledigt' → Story konsequent fortführen, Eskalation oder nächste Stufe."
        "\n- Letzter Auftrag '👎 Fehlgeschlagen' → komplett anderen Weg einschlagen, Tonart wechseln."
        "\n- Kein vorheriger Auftrag → frischer Einstieg, der zur Gang-Story passt."
    )

    if ctx.extra_instructions.strip():
        parts.append(f"\n## Zusätzliche Hinweise des Admins\n{ctx.extra_instructions.strip()}")

    parts.append(
        "\n## Aufgabe\nGeneriere jetzt den nächsten Auftrag im oben definierten Stil. "
        "Drei bis vier Sätze. Kryptisch. Kein Klartext für Außenstehende."
    )

    return "\n".join(parts)


def build_rewrite_prompt(ctx: MissionContext, raw_input: str) -> str:
    """Roher Admin-Text → KI schreibt im kryptisch-hochwertigen Stil um."""
    parts: list[str] = []
    parts.append(f"## Gang\n{ctx.crew_name}")
    if ctx.crew_story:
        parts.append(f"\n## Hintergrund-Story\n{ctx.crew_story}")

    if ctx.related_crews:
        rel_lines = ["\n## Beziehungen zu anderen Gangs"]
        for r in ctx.related_crews:
            rel_lines.append(
                f"- **{r['name']}** ({r['relation_type']}): {r.get('notes', '').strip() or 'keine Notiz'}"
            )
        parts.append("\n".join(rel_lines))

    if ctx.history:
        hist = ["\n## Bisherige Aufträge (jüngste zuerst)"]
        for i, m in enumerate(ctx.history, start=1):
            status_label = {
                "approved": "👍 Erledigt",
                "rejected": "👎 Fehlgeschlagen",
                "cancelled": "❌ nicht ausführbar",
                "pending": "⏳ offen",
            }.get(m.get("status", ""), m.get("status", ""))
            hist.append(f"{i}. [{status_label}] {m.get('content', '')[:300]}")
        parts.append("\n".join(hist))

    parts.append(
        "\n## Roh-Input des Admins (Klartext, ungeschliffen)\n"
        f"{raw_input.strip()}"
    )

    if ctx.extra_instructions.strip():
        parts.append(f"\n## Zusätzliche Hinweise des Admins\n{ctx.extra_instructions.strip()}")

    parts.append(
        "\n## Aufgabe\n"
        "Schreibe den obigen Roh-Input in den definierten Stil um: kryptisch, atmosphärisch, hochwertig, "
        "3 bis 4 Sätze. Inhalt und Kernanweisung müssen erhalten bleiben — aber niemand außerhalb der Gang "
        "soll auf den ersten Blick verstehen, was gefordert ist. Nutze Code-Wörter, Andeutungen, Metaphern. "
        "Berücksichtige Gang-Hintergrund und Beziehungen. Gib nur den umgeschriebenen Auftragstext aus, "
        "keine Erklärung."
    )

    return "\n".join(parts)
