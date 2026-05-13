from __future__ import annotations

from dataclasses import dataclass


DEFAULT_SYSTEM_PROMPT = """Du bist Briefing-Autor für eine GTA-V-Liberty-City-Roleplay-Krimiserie.

Deine Aufträge sind kurz (3 bis 4 Sätze), kryptisch und atmosphärisch. Sie lesen sich wie verschlüsselte Nachrichten, die ein erfahrener Boss zwischen den Zeilen versteht. Schreibe nie offen "raubt", "tötet", "stehlt". Nutze stattdessen:

- Andeutungen, Code-Wörter, Synonyme aus dem Milieu
- Orte als Metaphern ("der alte Hafen schweigt nicht ewig", "die Glaskathedrale am Boulevard")
- Personen niemals beim Namen, sondern als Rollen ("der Buchhalter", "die Witwe von der 5th")
- Zeitangaben verschleiert ("wenn die Möwen schlafen", "vor dem dritten Glockenschlag")

Tonalität: hochwertig, literarisch, ein Hauch Noir. Kein Slang, kein Klischee. Wer es liest, soll spüren, dass dahinter Gewicht steht.

Format: nur den Auftragstext ausgeben. Keine Überschrift. Keine Erklärung. Keine Anrede. Drei bis vier Sätze.

Sprache: Deutsch."""

# Backwards-compat alias
SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT


@dataclass
class MissionContext:
    crew_name: str
    crew_story: str
    related_crews: list[dict]  # [{name, story, relation_type, notes}]
    history: list[dict]        # [{content, status, created_at}]
    extra_instructions: str = ""
    crime_business: str = ""


def build_user_prompt(ctx: MissionContext) -> str:
    parts: list[str] = []
    parts.append(f"## Gang\n{ctx.crew_name}")
    if ctx.crew_story:
        parts.append(f"\n## Hintergrund-Story\n{ctx.crew_story}")

    if ctx.crime_business and ctx.crime_business.strip():
        parts.append(
            f"\n## Crime-Business (intern, fuer Auftrags-Ausrichtung)\n"
            f"{ctx.crime_business.strip()}\n\n"
            f"Diese Information ist NICHT oeffentlich. Die KI nutzt sie als Kompass, "
            f"in welche Richtung Auftraege gehen sollen (Drogenhandel, Waffenhandel, "
            f"Schutzgeld, Hehlerei, Geldwaesche etc.), ohne sie im Auftragstext direkt "
            f"zu nennen."
        )

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
        "\n\n**Story-Verankerung:** Greife sichtbar 1–2 konkrete Elemente aus der "
        "Hintergrund-Story auf — typische Orte, Rollen, Geschäftsfelder, Reviere "
        "oder die Mentalität der Gang. Der Auftrag soll sich anfühlen wie aus dem "
        "inneren Kreis genau dieser Gang, nicht wie ein generisches Mafia-Briefing. "
        "Erzwinge es nicht plump — die Anker sollen organisch im Text sitzen, "
        "nicht aufgezählt wirken."
    )

    return "\n".join(parts)


def build_crime_business_briefing_prompt(
    crew_name: str, crew_story: str, crime_business: str
) -> tuple[str, str]:
    """Eigenstaendiger Prompt: KI formuliert das interne Crime-Business
    der Crew in einen atmosphaerischen Briefing-Text um, der direkt in einen
    privaten Discord-Channel der Crew gepostet wird.

    Returns (system_prompt, user_prompt). Kein Mission-Kontext, keine Historie.
    Output soll <= 1900 Zeichen sein (Discord-Limit), 3-6 Absaetze."""
    sys = (
        "Du bist Briefing-Autor fuer eine GTA-V-Liberty-City-Roleplay-Krimiserie. "
        "Du formulierst das interne Geschaeftsprofil einer Crime-Crew als atmosphaerischen "
        "Einfuehrungstext um, der von einem Mittelsmann oder Crew-Insider an die Crew "
        "selbst gerichtet ist — also kein verschluesseltes Auftrags-Briefing, sondern eine "
        "Beschreibung des Geschaeftsfeldes der Crew im Noir-Ton.\n\n"
        "Ton: literarisch, atmosphaerisch, ein Hauch Noir. Kein Slang. Kein platter Klartext "
        "('wir handeln mit Drogen'), sondern Andeutungen, Code-Woerter, Milieu-Sprache. "
        "Die Crew weiss schon, was sie tut — der Text soll Stimmung und Identitaet liefern, "
        "nicht Information.\n\n"
        "Struktur: 3 bis 6 kurze Absaetze, Gesamtlaenge <= 1800 Zeichen. Keine Ueberschrift, "
        "keine Anrede an die Crew, keine Aufzaehlungen mit Bullets. Sprache: Deutsch."
    )
    parts = [f"## Gang\n{crew_name}"]
    if crew_story:
        parts.append(f"\n## Hintergrund-Story der Gang\n{crew_story}")
    parts.append(
        f"\n## Internes Crime-Business (Klartext, ungeschliffen)\n{crime_business.strip()}"
    )
    parts.append(
        "\n## Aufgabe\n"
        "Formuliere das oben genannte Crime-Business in einen atmosphaerischen Briefing-Text "
        "im Stil der Hintergrund-Story. Der Text wird in den privaten Discord-Channel der Crew "
        "gepostet — die Crew soll spueren, wer sie ist und was ihr Geschaeftsfeld ist, ohne dass "
        "konkrete Klartext-Begriffe ('Kokain', 'Schutzgeld') verwendet werden. Stattdessen: "
        "Code-Woerter, Schauplaetze, Rollen, Mentalitaet der Gang."
    )
    return sys, "\n".join(parts)


def build_rewrite_prompt(ctx: MissionContext, raw_input: str) -> str:
    """Roher Admin-Text → KI schreibt im kryptisch-hochwertigen Stil um."""
    parts: list[str] = []
    parts.append(f"## Gang\n{ctx.crew_name}")
    if ctx.crew_story:
        parts.append(f"\n## Hintergrund-Story\n{ctx.crew_story}")

    if ctx.crime_business and ctx.crime_business.strip():
        parts.append(
            f"\n## Crime-Business (intern, fuer Auftrags-Ausrichtung)\n"
            f"{ctx.crime_business.strip()}\n\n"
            f"Beim Umschreiben des Roh-Inputs darf dieses Business-Profil als Kompass "
            f"dienen — passe Code-Woerter und Andeutungen an das Geschaeftsfeld der "
            f"Gang an, ohne es im Auftragstext direkt zu nennen."
        )

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
        "soll auf den ersten Blick verstehen, was gefordert ist. Nutze Code-Wörter, Andeutungen, Metaphern."
        "\n\n**Story-Verankerung:** Lass die Hintergrund-Story spürbar werden — übersetze Locations, "
        "Rollen oder Geschäftsfelder aus dem Roh-Input in die Welt der Gang (z.B. der Roh-Input nennt "
        "'Juwelier in der Innenstadt' → die Gang-Story spricht vom 'Diamantenviertel' → nutze diesen "
        "Begriff). Die Tonalität soll zur Mentalität der Gang passen. Beziehungen und Reviere "
        "berücksichtigen, ohne sie aufzuzählen."
        "\n\nGib nur den umgeschriebenen Auftragstext aus, keine Erklärung."
    )

    return "\n".join(parts)
