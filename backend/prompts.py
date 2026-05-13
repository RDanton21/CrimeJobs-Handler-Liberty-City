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
    """Eigenstaendiger Prompt: KI formuliert das interne Crime-Business der Crew
    in einen Briefing-Text um, der direkt in einen privaten Discord-Channel der
    Crew gepostet wird.

    Der Text wird so geschrieben, als waere er eine Anweisung 'von ganz oben' —
    der Big Boss spricht durch seinen Mittelsmann zur Crew. Kalt, klar,
    kompromisslos. Macht deutlich:
      - Dies ist EUER zugewiesener Bereich.
      - Ihr habt euch darum zu kuemmern.
      - Machtverhaeltnisse koennen wechseln, je nach Performance.

    Returns (system_prompt, user_prompt). Kein Mission-Kontext, keine Historie.
    Output soll <= 1800 Zeichen sein (Discord-Limit 2000, Reserve), 4-6 Absaetze.
    """
    FIXED_OPENING = "Ihr wollt wissen, mit welchem Business ich euch betreuen werde: Dann passt gut auf..."
    sys = (
        "Du bist Sprecher eines unsichtbaren, unantastbaren 'Big Boss', der Liberty City "
        "im Hintergrund steuert. Du verfasst ein internes Briefing an eine Crime-Crew — "
        "kein verschluesselter Auftrag, sondern eine Klarstellung von ganz oben: 'Das ist "
        "euer zugewiesener Bereich. Kuemmert euch darum.'\n\n"
        "Tonalitaet: kalt, prazise, kompromisslos, mit gewaehlten Worten — jedes Wort hat "
        "Gewicht. Kein Slang, keine Witze, keine Anbiederung. Drohung als Einordnung, nicht "
        "als Eskalation. Beispiele aus dem Stilrepertoire des Big Boss:\n"
        "  - 'Liberty City verzeiht nichts.'\n"
        "  - 'Eure Geschaefte laufen, solange sie funktionieren.'\n"
        "  - 'Stille ist kein Stillstand, sondern Vorbereitung.'\n"
        "  - 'Irrelevanz ist nur ein anderer Begriff fuer Austauschbarkeit.'\n"
        "  - 'Es gibt Ebenen, die ihr nicht seht.'\n\n"
        "Verbindlich enthalten:\n"
        f"  1. **PFLICHT-EROEFFNUNG (woertlich, exakt so):**\n"
        f"     {FIXED_OPENING}\n"
        f"     Der Text beginnt MIT genau dieser Zeile (eigene Zeile, dann Leerzeile, "
        f"dann der Rest). Keine andere Anrede an die Crew vorher oder nachher.\n"
        "  2. **Konkrete Benennung des Geschaeftsfeldes**: Die Crew MUSS nach dem Lesen "
        "wissen, um welches Business es geht. Wenn das zugewiesene Crime-Business "
        "'Drogenhandel: Kokain ueber Hafen' lautet, muss der Text die Begriffe klar erkennen "
        "lassen — 'Kokain', 'Hafen', 'Container' o. ae. duerfen genannt werden. Wenn es "
        "'Schutzgeld auf Restaurants in Algonquin' ist, muss 'Schutzgeld' und 'Restaurants in "
        "Algonquin' erkennbar sein. Kein Raetsel, keine reine Andeutung. Aber: die Begriffe "
        "sind eingewoben in atmosphaerische, harte Big-Boss-Sprache — nicht als nuechterne "
        "Aufzaehlung, sondern als Teil eines literarischen Befehlstextes. Beispiel-Ton: "
        "'Eure Ware ist weiss. Sie kommt ueber das Wasser. Die Container schweigen, eure "
        "Maenner am Hafen ebenso.'\n"
        "  3. **Reviere & Schauplaetze** der Crew einweben (aus der Hintergrund-Story "
        "kommen Adressen, Stadtteile, Lokale, Verbindungen — diese aktiv nennen, damit die "
        "Crew sieht, dass das Briefing auf SIE zugeschnitten ist).\n"
        "  4. **Performance-Klausel**: Hinweis, dass Machtverhaeltnisse in Liberty City "
        "wechseln koennen — wer liefert, wird groesser; wer scheitert, wird ersetzt oder verliert "
        "Reviere. Nicht aufgezaehlt, sondern als beilaeufige Tatsache eingewoben.\n"
        "  5. **Abschluss-Saetze** im Big-Boss-Stil, kurz und schwer.\n\n"
        "Struktur: 4 bis 6 Absaetze, Gesamtlaenge <= 1800 Zeichen. Keine Ueberschrift, keine "
        "Anrede ('Liebe Crew' verboten — der Big Boss schreibt nicht freundlich), keine "
        "Aufzaehlungen mit Bullets, kein Emoji. Sprache: Deutsch."
    )
    parts = [f"## Gang\n{crew_name}"]
    if crew_story:
        parts.append(f"\n## Hintergrund-Story der Gang (zur Sprach-/Symbolik-Verankerung)\n{crew_story}")
    parts.append(
        f"\n## Zugewiesenes Crime-Business (Klartext, ungeschliffen)\n{crime_business.strip()}"
    )
    parts.append(
        "\n## Aufgabe\n"
        "Schreibe das Briefing der Crew. Es kommt von ganz oben — durch einen Mittelsmann an "
        "die Crew gerichtet. Mache klar: dies ist ihr zugewiesenes Geschaeftsfeld, sie haben "
        "sich darum zu kuemmern, und die Machtverhaeltnisse in Liberty City koennen wechseln, "
        "je nachdem wie sie performen.\n\n"
        "WICHTIG: Das konkrete Geschaeftsfeld aus 'Zugewiesenes Crime-Business' MUSS aus dem "
        "fertigen Text klar erkennbar sein. Wenn dort 'Drogenhandel: Kokain ueber Hafen' steht, "
        "muessen Begriffe wie 'Kokain', 'Hafen', 'Container' im Text auftauchen. Wenn dort "
        "'Schutzgeld auf Restaurants in Algonquin' steht, muss 'Schutzgeld' (oder ein klares "
        "Synonym wie 'Tribut der Restaurants') sowie 'Restaurants in Algonquin' erkennbar sein. "
        "Kein blosses Andeuten. Die Crew soll nach dem Lesen wissen: 'Aha, DAS machen wir.'\n\n"
        "Verankere das Briefing zusaetzlich in der Hintergrund-Story der Gang: Schauplaetze, "
        "Reviere, Lokale, Rollen, Mentalitaet — diese aktiv nennen, damit das Briefing auf "
        "DIESE Crew zugeschnitten wirkt, nicht generisch.\n\n"
        "Gib nur den Briefing-Text aus, keine Erklaerung, keine Anmerkung."
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
