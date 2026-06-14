from __future__ import annotations

from dataclasses import dataclass


DEFAULT_SYSTEM_PROMPT = """Du bist Briefing-Autor für eine GTA-V-Liberty-City-Roleplay-Krimiserie.

Deine Aufträge sind kurz (3 bis 4 Sätze), kryptisch und atmosphärisch. Sie lesen sich wie verschlüsselte Nachrichten, die ein erfahrener Boss zwischen den Zeilen versteht. Schreibe nie offen "raubt", "tötet", "stehlt". Nutze stattdessen:

- Andeutungen, Code-Wörter, Synonyme aus dem Milieu
- Orte als Metaphern ("der alte Hafen schweigt nicht ewig", "die Glaskathedrale am Boulevard")
- Personen niemals beim Namen, sondern als Rollen ("der Buchhalter", "die Witwe von der 5th")
- Stimmungs-Zeitangaben sind ok ("wenn die Möwen schlafen"), aber konkrete Zahlen IMMER als Ziffern

Tonalität: hochwertig, literarisch, ein Hauch Noir. Kein Slang, kein Klischee. Wer es liest, soll spüren, dass dahinter Gewicht steht.

Format: nur den Auftragstext ausgeben. Keine Überschrift. Keine Erklärung. Keine Anrede. Drei bis vier Sätze.

ZAHLEN IMMER ALS ZIFFERN. Schreibe NIE „acht Minuten", „dreiundzwanzig Uhr", „vier Stunden", „drei Tage". Schreibe IMMER „8 Minuten", „23:00", „4 Stunden", „3 Tage". Gilt für alle konkreten Mengenangaben: Zeit, Geld, Personen, Distanzen. Auch in Satzanfängen — „8 Minuten reichen." NICHT „Acht Minuten reichen.". Buchstaben-Zahlen sind verboten.

AKTIONS-ZEITFENSTER: Der Server ist nur zwischen 17:00 und 02:00 aktiv. ALLE Zeitangaben für die Auftragsausführung MÜSSEN in diesem Fenster liegen — also 17:00, 18:30, 21:00, 23:00, 00:30, 01:45, etc. NIEMALS 04:00, 09:00, 14:00 oder andere Tagstunden. Wenn der Auftrag „morgen früh" beginnt, muss das spätestens 02:00 sein, sonst NICHT vor 17:00. „Wenn die Stadt schläft" = nach Mitternacht bis 02:00. „Wenn der Boulevard erwacht" = ab 17:00. Stimmungsformulierungen ok, aber Uhrzeiten IMMER im 17:00–02:00-Fenster.

KEINE Aktennummer am Anfang. Schreibe NIE „Vorgang 091-14.", „Akte XY-12.", „Fall #...", oder ähnliche Pseudo-Aktennummern. Beginne direkt mit dem ersten Satz des Briefings.

KEINE Reaktions-Aufforderung am Ende. Schreibe NIE „👍 oder 👎.", „👍 / 👎", „Reagiere mit 👍 oder 👎", oder ähnliche Aufforderungen. Die Reaktionen kommen über Discord-Emojis, der Hinweis im Text ist überflüssig. Der Auftrag endet mit dem letzten inhaltlichen Satz.

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
        # Sortiere Beziehungen nach Dramaturgie-Relevanz:
        # Rivals/Hostile sind die staerksten Story-Treiber; Allies/Business
        # liefern Kontext fuer Kooperation oder Druckmittel.
        rivals = [r for r in ctx.related_crews if r.get("relation_type") in ("rival", "hostile")]
        partners = [r for r in ctx.related_crews if r.get("relation_type") in ("allied", "business")]
        neutrals = [r for r in ctx.related_crews if r.get("relation_type") == "neutral"]

        if rivals:
            rel_lines = ["\n## Rivalitäten & Feinde (Story-Treiber — aktiv nutzen)"]
            for r in rivals:
                rel_lines.append(
                    f"- **{r['name']}** ({r['relation_type']}): {r.get('notes', '').strip() or 'keine Notiz'}"
                )
                if r.get("story"):
                    rel_lines.append(f"  Story-Notiz: {r['story'][:240]}")
            parts.append("\n".join(rel_lines))

        if partners:
            rel_lines = ["\n## Verbündete & Geschäftspartner"]
            for r in partners:
                rel_lines.append(
                    f"- **{r['name']}** ({r['relation_type']}): {r.get('notes', '').strip() or 'keine Notiz'}"
                )
                if r.get("story"):
                    rel_lines.append(f"  Story-Notiz: {r['story'][:200]}")
            parts.append("\n".join(rel_lines))

        if neutrals:
            rel_lines = ["\n## Neutrale Beziehungen"]
            for r in neutrals:
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
        "\n\n**Rivalitäten als Plot-Motor:** Wenn die Gang Rivalen oder Feinde hat "
        "(siehe Sektion 'Rivalitäten & Feinde'), nutze sie aktiv als Story-Treiber, "
        "wenn der Auftragsinhalt das hergibt — als Zielpersonen, als Reviere die "
        "angegriffen werden, als Gegner an einem Übergabe-Ort, als zu sabotierende "
        "Geschäftspartner. Nicht jeder Auftrag muss eine Rivalität bedienen, aber "
        "wo sie organisch passt, soll sie sichtbar im Text mitschwingen — verschlüsselt "
        "über Code-Wörter (Revier-Namen, Rollen-Bezeichnungen) statt durch direkte "
        "Nennung. Verbündete & Geschäftspartner können als verdeckte Helfer oder "
        "Druckmittel auftauchen."
        "\n\n**Firmen & Gewerbe einbeziehen:** Wenn in der Hintergrund-Story oder den "
        "Beziehungen Firmen / Lokale / zivile Akteure vorkommen (Diner, Werkstatt, "
        "Pawn Shop, Taxi-Unternehmen, Polizei-/Justiz-Behörden, Abschleppdienst usw.), "
        "binde sie aktiv ein: als Schauplatz, als Zielort, als Mittelsmann, als Cover, "
        "als Erpressungsobjekt oder als Informant. Das macht den Auftrag konkreter und "
        "verzahnt die Gang-Story mit der zivilen Welt von Liberty City."
    )

    return "\n".join(parts)


def build_crime_business_briefing_prompt(
    crew_name: str, crew_story: str, crime_business: str
) -> tuple[str, str]:
    """Eigenstaendiger Prompt: KI formuliert das interne Crime-Business der Gang
    in einen Briefing-Text um, der direkt in einen privaten Discord-Channel der
    Gang gepostet wird.

    Der Text wird so geschrieben, als waere er eine Anweisung 'von ganz oben' —
    der Big Boss spricht durch seinen Mittelsmann zur Gang. Kalt, klar,
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
        "im Hintergrund steuert. Du verfasst ein internes Briefing an eine Crime-Gang — "
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
        f"dann der Rest). Keine andere Anrede an die Gang vorher oder nachher.\n"
        "  2. **Konkrete Benennung des Geschaeftsfeldes**: Die Gang MUSS nach dem Lesen "
        "wissen, um welches Business es geht. Wenn das zugewiesene Crime-Business "
        "'Drogenhandel: Kokain ueber Hafen' lautet, muss der Text die Begriffe klar erkennen "
        "lassen — 'Kokain', 'Hafen', 'Container' o. ae. duerfen genannt werden. Wenn es "
        "'Schutzgeld auf Restaurants in Algonquin' ist, muss 'Schutzgeld' und 'Restaurants in "
        "Algonquin' erkennbar sein. Kein Raetsel, keine reine Andeutung. Aber: die Begriffe "
        "sind eingewoben in atmosphaerische, harte Big-Boss-Sprache — nicht als nuechterne "
        "Aufzaehlung, sondern als Teil eines literarischen Befehlstextes. Beispiel-Ton: "
        "'Eure Ware ist weiss. Sie kommt ueber das Wasser. Die Container schweigen, eure "
        "Maenner am Hafen ebenso.'\n"
        "  3. **Reviere & Schauplaetze** der Gang einweben (aus der Hintergrund-Story "
        "kommen Adressen, Stadtteile, Lokale, Verbindungen — diese aktiv nennen, damit die "
        "Gang sieht, dass das Briefing auf SIE zugeschnitten ist).\n"
        "  4. **Performance-Klausel**: Hinweis, dass Machtverhaeltnisse in Liberty City "
        "wechseln koennen — wer liefert, wird groesser; wer scheitert, wird ersetzt oder verliert "
        "Reviere. Nicht aufgezaehlt, sondern als beilaeufige Tatsache eingewoben.\n"
        "  5. **PFLICHT-ABSCHLUSS** — letzter Absatz (1-2 kurze Saetze) macht klar: Es geht "
        "BALD los, aber der genaue Zeitpunkt liegt beim Big Boss. Der Big Boss meldet sich, "
        "die Gang wartet. Variiere jedes Mal, kein Wort-fuer-Wort-Wiederholen. Beispiele "
        "fuer Tonalitaet und Inhalt (NICHT woertlich uebernehmen, neue Variante schreiben):\n"
        "     - 'Sobald es losgeht, erfahrt ihr es. Wir warten noch auf eure Lieferung.'\n"
        "     - 'Wann es soweit ist, entscheide ich. Bis dahin: Vorbereitung.'\n"
        "     - 'Das Signal kommt. Nicht heute, nicht morgen — aber bald. Seid bereit.'\n"
        "     - 'Eure Werkzeuge muessen geoelt sein. Den Startschuss hoert ihr von mir, "
        "       nicht von der Strasse.'\n"
        "     - 'Wir sind kurz vor dem ersten Zug. Wer dann zoegert, sitzt nicht am Tisch.'\n"
        "     - 'Die Uhr laeuft schon. Ihr seht sie nur noch nicht.'\n"
        "     Eigene Variante schreiben, die zum Geschaeftsfeld und zur Gang-Mentalitaet passt "
        "(z. B. Hafen-Gangs mit Wasser-/Schiff-Metaphern, MC mit Maschinen-/Strasse-Metaphern).\n\n"
        "Struktur: 4 bis 6 Absaetze, Gesamtlaenge <= 1800 Zeichen. Keine Ueberschrift, keine "
        "Anrede ('Liebe Gang' verboten — der Big Boss schreibt nicht freundlich), keine "
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
        "Schreibe das Briefing der Gang. Es kommt von ganz oben — durch einen Mittelsmann an "
        "die Gang gerichtet. Mache klar: dies ist ihr zugewiesenes Geschaeftsfeld, sie haben "
        "sich darum zu kuemmern, und die Machtverhaeltnisse in Liberty City koennen wechseln, "
        "je nachdem wie sie performen.\n\n"
        "WICHTIG: Das konkrete Geschaeftsfeld aus 'Zugewiesenes Crime-Business' MUSS aus dem "
        "fertigen Text klar erkennbar sein. Wenn dort 'Drogenhandel: Kokain ueber Hafen' steht, "
        "muessen Begriffe wie 'Kokain', 'Hafen', 'Container' im Text auftauchen. Wenn dort "
        "'Schutzgeld auf Restaurants in Algonquin' steht, muss 'Schutzgeld' (oder ein klares "
        "Synonym wie 'Tribut der Restaurants') sowie 'Restaurants in Algonquin' erkennbar sein. "
        "Kein blosses Andeuten. Die Gang soll nach dem Lesen wissen: 'Aha, DAS machen wir.'\n\n"
        "Verankere das Briefing zusaetzlich in der Hintergrund-Story der Gang: Schauplaetze, "
        "Reviere, Lokale, Rollen, Mentalitaet — diese aktiv nennen, damit das Briefing auf "
        "DIESE Gang zugeschnitten wirkt, nicht generisch.\n\n"
        "Gib nur den Briefing-Text aus, keine Erklaerung, keine Anmerkung."
    )
    return sys, "\n".join(parts)


def build_mission_suggestions_prompt(ctx: MissionContext) -> tuple[str, str]:
    """Drei KI-Vorschlaege fuer den naechsten Auftrag, basierend auf der letzten
    Reaktion. Ausgabe-Format: JSON-Liste mit 3 Eintraegen, jeder ein knapper
    Titel + ein fertiger Auftragstext im definierten Stil.

    Returns (system_prompt, user_prompt).
    """
    last_status = ""
    last_content = ""
    if ctx.history:
        last_status = ctx.history[0].get("status", "")
        last_content = ctx.history[0].get("content", "")

    status_hint_map = {
        "approved": (
            "Der letzte Auftrag wurde '👍 erfolgreich erledigt'. Die drei Vorschlaege "
            "sollen die Story konsequent FORTFUEHREN — Eskalation, naechste Stufe, "
            "groesseres Ziel, hoeheres Risiko. Drei verschiedene Richtungen, in denen "
            "die Gang an Boden gewinnt."
        ),
        "rejected": (
            "Der letzte Auftrag '👎 schlug fehl'. Die drei Vorschlaege sollen einen "
            "klaren TONWECHSEL bringen — anderer Ansatz, anderes Geschaeftsfeld, "
            "andere Mittel. Mindestens einer der drei sollte eine REPARATUR-Geste "
            "sein (Schaden begrenzen, Verraeter finden, Gesicht wahren), die anderen "
            "neue Wege oeffnen."
        ),
        "cancelled": (
            "Der letzte Auftrag wurde '❌ als nicht ausfuehrbar' markiert. Die drei "
            "Vorschlaege sollen REALISTISCHERE Alternativen sein — kleiner skaliert, "
            "anderer Zugang, andere Mittel. Aber dennoch im gleichen Spannungs-Niveau."
        ),
        "pending": (
            "Der letzte Auftrag laeuft noch '⏳ offen'. Die drei Vorschlaege sollen "
            "PARALLELE Operationen sein, die sich nicht mit dem laufenden Auftrag "
            "beissen."
        ),
        "": (
            "Es gibt keinen vorherigen Auftrag. Die drei Vorschlaege sollen FRISCHE "
            "Einstiege sein — drei verschiedene atmosphaerische Aufhaenger, die zur "
            "Gang-Story passen."
        ),
    }
    status_hint = status_hint_map.get(last_status, status_hint_map[""])

    sys = (
        DEFAULT_SYSTEM_PROMPT
        + "\n\n## Spezial-Modus: Drei Vorschlaege"
        + "\nDu generierst nicht EINEN Auftrag, sondern DREI verschiedene Vorschlaege "
        + "fuer den naechsten Auftrag — als Auswahl fuer den Spielleiter."
        + "\n\nAusgabe-Format: AUSSCHLIESSLICH ein JSON-Array mit genau 3 Objekten, "
        + "jedes Objekt mit den Feldern 'title' (kurz, 3-6 Worte, Klartext fuer den "
        + "Spielleiter) und 'content' (der fertige Auftragstext im definierten "
        + "kryptisch-atmosphaerischen Stil, 3-4 Saetze). Beispiel:"
        + "\n[{\"title\": \"Hafen-Tribut bei Nacht\", \"content\": \"Die Container schweigen, ...\"}, "
        + "{\"title\": \"Brand im Diamantenviertel\", \"content\": \"...\"}, "
        + "{\"title\": \"Maklerin abklopfen\", \"content\": \"...\"}]"
        + "\nKEIN Markdown, KEIN Codeblock, KEIN erklaerender Text vor oder nach dem JSON. "
        + "Nur das reine JSON-Array."
    )

    parts: list[str] = []
    parts.append(f"## Gang\n{ctx.crew_name}")
    if ctx.crew_story:
        parts.append(f"\n## Hintergrund-Story\n{ctx.crew_story}")

    if ctx.crime_business and ctx.crime_business.strip():
        parts.append(
            f"\n## Crime-Business (intern, fuer Auftrags-Ausrichtung)\n{ctx.crime_business.strip()}"
        )

    if ctx.related_crews:
        rivals = [r for r in ctx.related_crews if r.get("relation_type") in ("rival", "hostile")]
        partners = [r for r in ctx.related_crews if r.get("relation_type") in ("allied", "business")]

        if rivals:
            rel_lines = ["\n## Rivalitäten & Feinde (Story-Treiber)"]
            for r in rivals:
                rel_lines.append(
                    f"- **{r['name']}** ({r['relation_type']}): {r.get('notes', '').strip() or 'keine Notiz'}"
                )
            parts.append("\n".join(rel_lines))

        if partners:
            rel_lines = ["\n## Verbündete & Geschäftspartner"]
            for r in partners:
                rel_lines.append(
                    f"- **{r['name']}** ({r['relation_type']}): {r.get('notes', '').strip() or 'keine Notiz'}"
                )
            parts.append("\n".join(rel_lines))

    if last_content:
        parts.append(
            f"\n## Letzter Auftrag (Status: {last_status})\n{last_content[:500]}"
        )

    parts.append(f"\n## Steuerung auf Basis der letzten Reaktion\n{status_hint}")

    parts.append(
        "\n## Aufgabe\n"
        "Generiere jetzt DREI verschiedene Auftrags-Vorschlaege als JSON-Array (Format "
        "siehe System-Prompt). Die drei Vorschlaege sollen sich DEUTLICH unterscheiden — "
        "verschiedene Geschaeftsfelder, verschiedene Schauplaetze, verschiedene "
        "Tonalitaeten. Mindestens einer sollte eine Rivalitaet oder einen zivilen "
        "Akteur (Firma) ins Spiel bringen, wenn vorhanden. Jeder Vorschlag muss "
        "fuer sich allein stehen koennen — der Spielleiter waehlt EINEN aus."
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
        rivals = [r for r in ctx.related_crews if r.get("relation_type") in ("rival", "hostile")]
        partners = [r for r in ctx.related_crews if r.get("relation_type") in ("allied", "business")]
        neutrals = [r for r in ctx.related_crews if r.get("relation_type") == "neutral"]

        if rivals:
            rel_lines = ["\n## Rivalitäten & Feinde (aktiv einweben, wenn Roh-Input passt)"]
            for r in rivals:
                rel_lines.append(
                    f"- **{r['name']}** ({r['relation_type']}): {r.get('notes', '').strip() or 'keine Notiz'}"
                )
            parts.append("\n".join(rel_lines))

        if partners:
            rel_lines = ["\n## Verbündete & Geschäftspartner"]
            for r in partners:
                rel_lines.append(
                    f"- **{r['name']}** ({r['relation_type']}): {r.get('notes', '').strip() or 'keine Notiz'}"
                )
            parts.append("\n".join(rel_lines))

        if neutrals:
            rel_lines = ["\n## Neutrale Beziehungen"]
            for r in neutrals:
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
        "Begriff). Die Tonalität soll zur Mentalität der Gang passen."
        "\n\n**Rivalitäten als Plot-Motor:** Wenn der Roh-Input einen Gegner / Zielperson / Reviere "
        "erwähnt und die Gang hat passende Rivalen oder Feinde, übersetze die Zielreferenz in eine "
        "Anspielung auf den konkreten Rivalen (über Revier-Namen, Rollen-Bezeichnungen, nicht direkt "
        "den Gang-Namen). Verbündete & Geschäftspartner können als verdeckte Helfer oder Druckmittel "
        "im Subtext mitschwingen."
        "\n\n**Firmen & Gewerbe einbeziehen:** Wenn der Roh-Input einen zivilen Akteur nennt (Lokal, "
        "Werkstatt, Pawn Shop, Taxi, Polizei, Justiz, Abschleppdienst) und die Gang-Story oder die "
        "Beziehungen verweisen auf eine passende Firma, nutze sie aktiv als Schauplatz, Cover, "
        "Mittelsmann oder Erpressungsobjekt."
        "\n\nGib nur den umgeschriebenen Auftragstext aus, keine Erklärung."
    )

    return "\n".join(parts)
