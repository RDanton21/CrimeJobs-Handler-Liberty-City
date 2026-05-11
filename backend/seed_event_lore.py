"""Seed-Skript fuer Event-Lore (Stories + Beziehungen + Crew-Umbenennung).

Liest Stories aus ../docs/gang-stories/*.md, ordnet sie ueber CREW_STORY_MAP
den DB-Crew-IDs zu, und schreibt:

  1. crew.story_background  fuer alle 21 Crews
     - Standard: nur leere Felder ueberschreiben
     - --force: auch befuellte Felder ueberschreiben
  2. crew.name fuer ID 3 setzen auf TARGET_CREW3_NAME (siehe Konstante).
     (kann mit --no-rename uebersprungen werden)
  3. crew_relations: Beziehungen aus RELATIONS-Liste
     - Standard: insert if not exists
     - --force: bestehende Eintraege werden auf RELATIONS-Werte
       aktualisiert (relation_type + notes)

Schalter:
  --dry-run    Zeigt nur, was gemacht wuerde, schreibt nichts.
  --force      Ueberschreibt vorhandene story_background-Eintraege
               UND aktualisiert vorhandene crew_relations-Notes.
  --no-rename  Ueberspringt die Crew-Umbenennung von ID 3.

Aufruf aus Repo-Root (Windows PowerShell):
  python -m backend.seed_event_lore --dry-run
  python -m backend.seed_event_lore --force
"""
import argparse
import asyncio
import re
import sys
from pathlib import Path

from sqlalchemy import select

from .db import SessionLocal
from .models import Crew, CrewRelation, RelationType


# ----------------------------------------------------------------------------
# Crew-3 Zielname (Discord-Channel heisst bereits so)
TARGET_CREW3_NAME = "Asiatische Yakuza"

# Mapping: Crew-ID -> (Substring im "## "-Header der Story-Sektion, Stadtteil-Datei)
# Reihenfolge entspricht den DB-IDs aus der initialen Erkundung.
# ----------------------------------------------------------------------------
CREW_STORY_MAP: list[tuple[int, str, str]] = [
    # (id, header_substring, district_file)
    (1,  "AOD MC",                     "algonquin"),
    (2,  "The Harlem Vipers",          "algonquin"),
    (3,  "Asiatische Yakuza",          "algonquin"),
    (4,  "Italienische Mafia",         "algonquin"),
    (5,  "LOST MC",                    "bohan"),
    (6,  "Bohan Sequidors",            "bohan"),
    (7,  "Los Aztecas",                "bohan"),
    (8,  "Blue Union",                 "bohan"),
    (9,  "Broker Crossline Kings",     "broker"),
    (10, "The Fireflys",               "broker"),
    (11, "Jamaikanische Yardis",       "broker"),
    (12, "Broker Avenue Lords",        "broker"),
    (13, "Russian Mafia",              "broker"),
    (14, "Little Bay Pirates",         "colony-island"),
    (15, "Independent Smugglers",      "colony-island"),
    (16, "Blackline Security",         "colony-island"),
    (17, "Money over Bitches",         "dukes"),
    (18, "Dukes Latin Kings",          "dukes"),
    (19, "Spanish Lords",              "dukes"),
    (20, "Eastline Wolves",            "dukes"),
    (21, "Midtown 49ers",              "dukes"),
]

# Beziehungen: (crew_a_id, crew_b_id, relation_type, notes)
# Konvention: crew_a_id < crew_b_id
RELATIONS: list[tuple[int, int, RelationType, str]] = [
    # --- Algonquin intra ---
    (3, 4, RelationType.BUSINESS,
     "Geteilte Theaterstrasse, Uebereinkunft seit zwei Generationen — gegenseitiger "
     "Respekt zwischen Don Manschetti und Oyabun Tanaka, aber keine Waerme."),
    (1, 4, RelationType.RIVAL,
     "Drei Saeulen, eine Stadt — beide kontrollieren je 25 % Algonquins. Mafia toleriert "
     "den Charter, Charter trotzt der Mafia. Ungeschriebene Linien."),
    (2, 4, RelationType.HOSTILE,
     "Vipers brechen alte Hierarchien, Mafia sieht das als Affront. 15 % gegen 25 %. "
     "Bisher kein Krieg, aber jeder Vorfall wird gezaehlt."),
    (2, 3, RelationType.NEUTRAL,
     "Distanziert. Yakuza hat parallele Welt, Vipers haben ihre Blocks. Wenn sich die "
     "Welten kreuzen, ist es noch nicht entschieden, wie."),
    (1, 2, RelationType.RIVAL,
     "MC sieht Vipers als 'die Neuen', Vipers sehen den MC als 'die Alten'. Wer in den "
     "naechsten Jahren in Algonquin neu denkt, gewinnt das Verhaeltnis."),
    (1, 3, RelationType.NEUTRAL,
     "Drei Saeulen, drei Welten. AOD und Yakuza haben sich seit Jahren nicht persoenlich "
     "begegnet — und genau das ist die Uebereinkunft. Stille als Vertrag."),

    # --- Bohan intra ---
    (6, 7, RelationType.RIVAL,
     "Beide Latino, beide Block-orientiert, beide stolz. Die Uebereinkunft, sich nicht in "
     "die Reviere des anderen zu draengen, ist bruechig — und aelter als die meisten Mitglieder."),
    (5, 6, RelationType.HOSTILE,
     "Sequidors sehen den MC als Eindringling auf ihren Bruecken. MC sieht die Sequidors "
     "als das, was im Weg steht."),
    (5, 7, RelationType.RIVAL,
     "Aztecas wollen Stille im Barrio, MC bringt Laerm. Verletzungen, aber keine "
     "Beerdigungen — bisher."),
    (6, 8, RelationType.BUSINESS,
     "Kalter Modus vivendi: Union 'patrouilliert', Sequidors 'verstehen'. Geld wechselt "
     "nicht den Besitzer — Schweigen tut es."),
    (5, 8, RelationType.HOSTILE,
     "Ex-Cops gegen Outlaw-MC, klassisch und tief. Jede Patrouille der Union an der "
     "Bruecke endet mit Worten, manche mit mehr."),

    # --- Broker intra ---
    (9, 12, RelationType.BUSINESS,
     "Lords haben die Hauptstrassen, Kings haben die Querstrassen — geteilter Kuchen, "
     "kalt aber funktional."),
    (12, 13, RelationType.BUSINESS,
     "Bratva liefert ueber den Hafen, Lords oeffnen die Tueren, hinter denen geliefert "
     "wird. Niemand spricht oeffentlich darueber."),
    (9, 11, RelationType.ALLIED,
     "Alte Bekanntschaft aus Mercer's Gym — Selecta hat dort einmal trainiert, lange vor "
     "der Crew. Allianz nicht in Vertraegen, sondern in Erinnerungen."),
    (11, 13, RelationType.RIVAL,
     "Streit um Hafen-Anteile, kalt seit dem letzten Winter. Eine Sache reicht, um den "
     "Streit wieder warm zu machen."),
    (10, 12, RelationType.HOSTILE,
     "Lords sehen die Fireflys als Bedrohung des Club-Geschaefts — illegale Locations, "
     "kein Tuersteher, kein Anteil. Mehrere Razzien wurden zugefluestert."),
    (10, 11, RelationType.BUSINESS,
     "Yardis liefern Sound, Fireflys liefern Locations. Kooperation aus Notwendigkeit, "
     "die zur Freundschaft werden koennte."),

    # --- Colony Island intra ---
    (14, 15, RelationType.HOSTILE,
     "Pirates haben in den letzten zwei Jahren mehrfach Lieferungen der Independents "
     "geentert. Das Captains' Council schweigt darueber — aber sie haben Erinnerungen."),
    (15, 16, RelationType.BUSINESS,
     "Heimliche Lieferantenkette: Blackline 'bemerkt' bestimmte Transporte nicht, "
     "im Gegenzug Zugang zu Frachtbriefen, die ihr offiziell verschlossen waeren."),
    (14, 16, RelationType.HOSTILE,
     "Pirates sind das, was Blackline auf dem Papier 'bekaempft'. In der Realitaet ein "
     "wechselseitiges Foto-Album aus Vorfaellen, das niemand veroeffentlicht."),

    # --- Dukes intra ---
    (18, 19, RelationType.RIVAL,
     "Zwei Generationen alte Schwebe. Beide Latino, beide stolz, beide ueberzeugt, dass "
     "die andere ein Schatten ist. Frieden haelt, weil ihn niemand bricht."),
    (18, 21, RelationType.BUSINESS,
     "49ers vermitteln, Kings schuetzen die Vermittlung. Provision, die man nicht laut "
     "ausspricht, aber die jeder kennt."),
    (17, 18, RelationType.HOSTILE,
     "Kings sehen die MOB als respektlos, MOB sieht die Kings als ueberholt. Konflikt ist "
     "symbolisch — und damit gefaehrlicher als ein Geld-Konflikt."),
    (17, 20, RelationType.RIVAL,
     "MOB streamt laut, Wolves bewegen leise — Reibung der Stile mehr als der Reviere. "
     "Mehrere Vorfaelle vor dem Restaurant Tbilisi, jedes Mal wird die Tuer repariert."),
    (19, 21, RelationType.BUSINESS,
     "Lords lassen die 49ers durch ihre Reviere — gegen Provision. Kalte Uebereinkunft, "
     "die funktioniert, weil keiner mehr will."),
    (17, 19, RelationType.HOSTILE,
     "Don Rafa verachtet den MOB-Stil. J-Stack provoziert, weil er weiss, dass es wirkt. "
     "Bisher Worte, mehr nicht."),

    # --- Inter-District ---
    (4, 13, RelationType.RIVAL,
     "Alter Streit um Hafen-Anteile in Broker, kalt seit dem letzten Winter. Manschetti und "
     "Volkov haben sich seit Jahren nicht persoenlich gesehen — sie kommunizieren ueber Mittler."),
    (4, 18, RelationType.BUSINESS,
     "Alte Uebereinkunft zwischen El Padre und Don Manschetti aus den Stadtkriegen: "
     "Konzessionen gegen Stille. Funktioniert seit acht Jahren."),
    (1, 5, RelationType.HOSTILE,
     "Bruder-Clubs, die nie mehr Brueder waren. Ungeloeste Fehde, so alt, dass die meisten "
     "Mitglieder den Ausloeser nicht mehr kennen — aber den Hass weitergeben."),
    (13, 15, RelationType.BUSINESS,
     "Bratva ist einer der groessten Kunden der Independents. Welcher Captain fuer sie "
     "arbeitet, aendert sich von Lieferung zu Lieferung — Absicht."),
    (4, 16, RelationType.BUSINESS,
     "Vertraege auf Briefpapier, die nicht aussehen wie das, was sie sind. Magnus Thorsen "
     "war einmal bei einer Beerdigung der Manschettis — als 'Sicherheitsberater'."),
    (7, 19, RelationType.ALLIED,
     "Kulturelle Bruecke. Don Rafa und Cruz Alvarez kennen sich seit der Schule — die "
     "einzige offene Allianz der beiden Bohan- und Dukes-Latinos. Ueber diese Allianz "
     "haben die Spanish Lords Verstecke und Logistik in Bohan."),
    (2, 17, RelationType.BUSINESS,
     "Junge Crews, aehnliches Mindset. Gelegentliche Kooperationen, immer informell, "
     "nie schriftlich. Cobra und J-Stack telefonieren — selten, aber direkt."),
    (10, 17, RelationType.ALLIED,
     "Beide jung, beide laut, beide Internet-orientiert. Die einzige offene Allianz quer "
     "durch die Halbinseln. Phantom postet Forty's Tracks."),
    (5, 14, RelationType.BUSINESS,
     "Pirates liefern via Wasser, LOST verteilt via Land. Logistik-Kette, die Wreck und "
     "Hook auf einer Bierdose besiegelt haben."),
    (13, 20, RelationType.NEUTRAL,
     "Zwei osteuropaeische Maechte, eine Stadt — Bratva (Broker, 40 %) und Wolves (Dukes, "
     "35 %) treffen sich nie persoenlich. Genau das ist die Uebereinkunft. Beide wissen, "
     "dass eine osteuropaeische Front in Liberty City keiner sich leisten koennte."),
    (4, 20, RelationType.RIVAL,
     "Manschettis haben ueber die Latin-Kings-Bruecke einen Aussenposten in Dukes (20 % "
     "Stadtteilmacht). Wolves (35 %) sehen das als geduldete Anwesenheit, nicht als Recht. "
     "Linie haelt — unter Spannung."),
    (4, 21, RelationType.BUSINESS,
     "49ers sind die einzige Crew der Stadt, die fuer jede der drei Algonquin-Saeulen "
     "(Mafia, Yakuza, AOD) gleichzeitig arbeiten kann. Manschetti nutzt das."),
    (6, 19, RelationType.BUSINESS,
     "Geografische Notwendigkeit: Spanish Lords betreiben Verstecke in Sequidor-Reviere. "
     "Carmen Rivera duldet das gegen einen Anteil — kein Buendnis, kalte Uebereinkunft."),
    (6, 11, RelationType.BUSINESS,
     "Yardies haben in Sued-Bohan Verteilerzentren auf Sequidor-Territorium. Selecta und "
     "La Loba haben sich vor zwei Jahren persoenlich verstaendigt."),
    (7, 11, RelationType.BUSINESS,
     "Bestehende kulturelle Schiene zwischen Aztecas und Yardies — ueber Sued-Bohan "
     "operativ verstaerkt. Gemeinsame Lieferketten ohne offene Allianz."),
]


# ----------------------------------------------------------------------------
# Story-Extraktion aus Markdown
# ----------------------------------------------------------------------------
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "gang-stories"


def extract_story(district_file: str, header_substring: str) -> str | None:
    """Extrahiert die Story-Sektion einer Crew aus der Stadtteil-MD-Datei.

    Sucht im File die ## -Sektion, deren Header den header_substring enthaelt,
    und gibt den Inhalt bis zur naechsten ## oder dem File-Ende zurueck.
    """
    md_path = DOCS_DIR / f"{district_file}.md"
    if not md_path.exists():
        return None
    text = md_path.read_text(encoding="utf-8")
    # Splitte bei "## " auf Zeilenanfang
    sections = re.split(r"^## ", text, flags=re.MULTILINE)
    for sec in sections[1:]:
        # erste Zeile ist der Header
        header_line = sec.split("\n", 1)[0]
        if header_substring in header_line:
            # Header und Body zusammenfuegen
            full = "## " + sec
            # Bei "---" am Ende abschneiden, falls die naechste Sektion bereits durch eine
            # Trennlinie eingeleitet wird (passiert nicht durch unser Splitting, aber sicherheitshalber)
            return full.strip()
    return None


# ----------------------------------------------------------------------------
# Seed-Logik
# ----------------------------------------------------------------------------
async def run_seed(dry_run: bool, force: bool, no_rename: bool) -> None:
    # Hinweis: init_db() wird hier NICHT aufgerufen. Das Skript setzt voraus,
    # dass die DB bereits durch das laufende Backend migriert ist. Vermeidet
    # ungewollte Schreibvorgaenge in --dry-run.
    async with SessionLocal() as session:
        # 1. Crews laden
        result = await session.execute(select(Crew).order_by(Crew.id))
        crews_by_id: dict[int, Crew] = {c.id: c for c in result.scalars().all()}

        print(f"\n=== {len(crews_by_id)} Crews in DB gefunden ===\n")

        # 2. Crew-Umbenennung (Ziel: TARGET_CREW3_NAME)
        if not no_rename:
            crew3 = crews_by_id.get(3)
            if crew3 is None:
                print("WARN: Crew ID 3 nicht in DB — Umbenennung uebersprungen.")
            elif crew3.name == TARGET_CREW3_NAME:
                print(f"[name] ID 3 heisst bereits '{TARGET_CREW3_NAME}' — kein Update noetig.")
            else:
                print(f"[name] ID 3: '{crew3.name}' -> '{TARGET_CREW3_NAME}'")
                if not dry_run:
                    crew3.name = TARGET_CREW3_NAME

        # 3. Stories einspielen
        print()
        story_updates = 0
        story_skipped = 0
        for crew_id, header_sub, district in CREW_STORY_MAP:
            crew = crews_by_id.get(crew_id)
            if crew is None:
                print(f"  WARN: Crew ID {crew_id} ('{header_sub}') nicht in DB.")
                continue
            story = extract_story(district, header_sub)
            if story is None:
                print(f"  WARN: Keine Story-Sektion fuer '{header_sub}' in {district}.md gefunden.")
                continue

            existing = crew.story_background or ""
            has_existing = bool(existing.strip())

            if has_existing and not force:
                print(f"  [skip] ID {crew_id} '{crew.name}' hat bereits Story "
                      f"({len(existing)} Zeichen) — --force zum Ueberschreiben.")
                story_skipped += 1
                continue

            action = "UPDATE" if has_existing else "INSERT"
            print(f"  [{action.lower()}] ID {crew_id} '{crew.name}' "
                  f"<- {len(story)} Zeichen aus {district}.md")
            if not dry_run:
                crew.story_background = story
            story_updates += 1

        print(f"\n  Stories: {story_updates} aktualisiert, {story_skipped} uebersprungen.\n")

        # 4. Relations einspielen (insert if missing; --force aktualisiert auch Notes/Type)
        existing_rows = await session.execute(select(CrewRelation))
        existing_by_pair: dict[tuple[int, int], CrewRelation] = {
            (r.crew_a_id, r.crew_b_id): r for r in existing_rows.scalars().all()
        }

        rel_inserts = 0
        rel_updates = 0
        rel_skipped = 0
        for a_id, b_id, rtype, notes in RELATIONS:
            if a_id >= b_id:
                print(f"  WARN: Relation ({a_id}, {b_id}) hat a_id >= b_id — bitte sortieren.")
                continue
            if a_id not in crews_by_id or b_id not in crews_by_id:
                print(f"  WARN: Relation ({a_id}, {b_id}) referenziert unbekannte Crew.")
                continue
            existing = existing_by_pair.get((a_id, b_id))
            if existing is None:
                print(f"  [insert] ({a_id}, {b_id}) {rtype.value:10s} "
                      f"{crews_by_id[a_id].name} <-> {crews_by_id[b_id].name}")
                if not dry_run:
                    session.add(CrewRelation(
                        crew_a_id=a_id, crew_b_id=b_id,
                        relation_type=rtype, notes=notes,
                    ))
                rel_inserts += 1
                continue
            # Bestehende Beziehung — nur bei --force aktualisieren, und auch nur wenn etwas anders ist
            type_changed = existing.relation_type != rtype
            notes_changed = (existing.notes or "") != notes
            if not (type_changed or notes_changed):
                rel_skipped += 1
                continue
            if not force:
                rel_skipped += 1
                continue
            diff_parts = []
            if type_changed:
                diff_parts.append(f"type {existing.relation_type.value}->{rtype.value}")
            if notes_changed:
                diff_parts.append("notes")
            print(f"  [update] ({a_id}, {b_id}) {rtype.value:10s} "
                  f"{crews_by_id[a_id].name} <-> {crews_by_id[b_id].name}  "
                  f"[{', '.join(diff_parts)}]")
            if not dry_run:
                if type_changed:
                    existing.relation_type = rtype
                if notes_changed:
                    existing.notes = notes
            rel_updates += 1

        print(f"\n  Relations: {rel_inserts} neu, {rel_updates} aktualisiert, "
              f"{rel_skipped} unveraendert.\n")

        # 5. Commit oder Rollback
        if dry_run:
            print("=== DRY-RUN: keine Aenderungen gespeichert ===")
            await session.rollback()
        else:
            await session.commit()
            print("=== Aenderungen gespeichert ===")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Zeigt nur, was gemacht wuerde.")
    parser.add_argument("--force", action="store_true",
                        help="Ueberschreibt vorhandene story_background-Eintraege.")
    parser.add_argument("--no-rename", action="store_true",
                        help="Ueberspringt 'Asiatische Yakuza' -> 'Jade Lotus Triad'.")
    args = parser.parse_args()

    print(f"Modus: {'DRY-RUN' if args.dry_run else 'LIVE'}"
          f"{', --force' if args.force else ''}"
          f"{', --no-rename' if args.no_rename else ''}")

    asyncio.run(run_seed(args.dry_run, args.force, args.no_rename))


if __name__ == "__main__":
    main()
