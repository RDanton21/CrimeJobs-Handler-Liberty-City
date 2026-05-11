"""Hinzufuegen einer einzelnen Firma/Crew zum Crime-Automation-System.

Workflow:
1. Validiert: Stadtteil-Name muss in DISTRICTS sein (Algonquin/Bohan/Broker/
   Colony Island/Dukes).
2. Crew anlegen (falls nicht existiert) mit Stadtteil + Default-Farbe.
3. Story aus File oder stdin einlesen -> in crews.story_background eingespielt.
4. Optional: Story-Sektion an docs/gang-stories/<district>.md anhaengen
   (mit --append-to-md).

Beispiele (PowerShell):

  # 1) Story-File schon geschrieben, alles in einem Schritt:
  python -m backend.add_firm `
      --name "Pizza Express" `
      --district "Algonquin" `
      --story-file "C:\\path\\zur\\pizza-express.md" `
      --append-to-md

  # 2) Schnelltest mit Story aus stdin:
  echo "## Pizza Express`n`nKurze Story..." | python -m backend.add_firm `
      --name "Pizza Express" --district "Algonquin" --story-stdin

  # 3) Nur Discord-IDs nachtragen, ohne Story zu aendern:
  python -m backend.add_firm --name "Pizza Express" --district "Algonquin" `
      --discord-channel-id "12345..." --info-channel-id "67890..."

Schalter:
  --name <NAME>                  Name der Crew (erforderlich, eindeutig)
  --district <STADTTEIL>         Algonquin / Bohan / Broker / Colony Island / Dukes
  --story-file <PFAD>            Pfad zur Markdown-Story (## Header + Body)
  --story-stdin                  Story von stdin lesen statt aus File
  --color-hex <#xxxxxx>          Optional: eigene Farbe (default: Stadtteil-Farbe)
  --discord-channel-id <ID>      Optional: Auftrags-Channel-ID
  --info-channel-id <ID>         Optional: Info-Channel-ID
  --force                        Story ueberschreiben, auch wenn bereits befuellt
  --append-to-md                 Story zusaetzlich an docs/gang-stories/<district>.md
                                 anhaengen (mit --- Trennung)
  --dry-run                      Zeigt nur, was gemacht wuerde, schreibt nichts
"""
import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

from .db import SessionLocal
from .models import Crew


VALID_DISTRICTS = {"Algonquin", "Bohan", "Broker", "Colony Island", "Dukes"}

DISTRICT_COLOR_DEFAULT = {
    "Algonquin":     "#b91c1c",
    "Bohan":         "#ffffff",
    "Broker":        "#ff00bb",
    "Colony Island": "#001eff",
    "Dukes":         "#00fffb",
}

DISTRICT_TO_FILE = {
    "Algonquin":     "algonquin",
    "Bohan":         "bohan",
    "Broker":        "broker",
    "Colony Island": "colony-island",
    "Dukes":         "dukes",
}

ROOT_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT_DIR / "docs" / "gang-stories"


def read_story(args: argparse.Namespace) -> str | None:
    """Liest Story aus --story-file oder --story-stdin. None wenn keins gesetzt."""
    if args.story_file:
        path = Path(args.story_file)
        if not path.exists():
            print(f"FEHLER: Story-File nicht gefunden: {path}")
            sys.exit(1)
        return path.read_text(encoding="utf-8").strip()
    if args.story_stdin:
        story = sys.stdin.read().strip()
        if not story:
            print("FEHLER: --story-stdin gesetzt, aber stdin war leer.")
            sys.exit(1)
        return story
    return None


def append_story_to_district_md(district: str, name: str, story: str, dry_run: bool) -> bool:
    """Haengt die Story-Sektion an docs/gang-stories/<district>.md an.
    Stellt sicher, dass ein "## "-Header vorhanden ist (falls Story den nicht enthaelt,
    wird einer mit dem Namen vorne ergaenzt).
    """
    slug = DISTRICT_TO_FILE.get(district)
    if not slug:
        print(f"WARN: Kein Stadtteil-File-Mapping fuer '{district}'.")
        return False
    md_path = DOCS_DIR / f"{slug}.md"
    if not md_path.exists():
        print(f"WARN: {md_path} existiert nicht. Skip --append-to-md.")
        return False

    # Sicherstellen, dass die Story einen ## -Header hat
    story_block = story.strip()
    if not story_block.startswith("## "):
        story_block = f"## {name}\n\n{story_block}"

    addition = f"\n\n---\n\n{story_block}\n"
    print(f"  [md-append] Haenge Story an {md_path} an ({len(addition)} Zeichen).")

    if not dry_run:
        with md_path.open("a", encoding="utf-8") as f:
            f.write(addition)
    return True


async def run_add(args: argparse.Namespace) -> None:
    name = args.name.strip()
    district = args.district.strip()
    if district not in VALID_DISTRICTS:
        print(f"FEHLER: Unbekannter Stadtteil '{district}'. Erlaubt: {sorted(VALID_DISTRICTS)}")
        sys.exit(1)

    color = args.color_hex or DISTRICT_COLOR_DEFAULT[district]
    story = read_story(args)

    print(f"Modus: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print(f"  Name: {name!r}")
    print(f"  Stadtteil: {district!r}")
    print(f"  Farbe: {color}")
    print(f"  Story: {len(story) if story else 0} Zeichen")
    print(f"  Discord-Channel: {args.discord_channel_id or '-'}")
    print(f"  Info-Channel: {args.info_channel_id or '-'}")
    print()

    async with SessionLocal() as session:
        # Lookup
        result = await session.execute(select(Crew).where(Crew.name == name))
        crew = result.scalar_one_or_none()

        if crew is None:
            # Neu anlegen
            print(f"[create] Lege Crew '{name}' an (Stadtteil: {district}, Farbe: {color}).")
            if not args.dry_run:
                crew = Crew(
                    name=name,
                    district=district,
                    color_hex=color,
                    discord_channel_id=args.discord_channel_id or "",
                    info_channel_id=args.info_channel_id or "",
                    story_background=story or "",
                )
                session.add(crew)
                await session.flush()
                print(f"  -> ID {crew.id} vergeben.")
        else:
            print(f"[exists] Crew '{name}' existiert bereits (ID {crew.id}).")
            # Felder updaten, wenn explizit gesetzt
            updated_fields = []
            if args.color_hex and crew.color_hex != color:
                if not args.dry_run:
                    crew.color_hex = color
                updated_fields.append(f"color_hex={color}")
            if args.discord_channel_id is not None and crew.discord_channel_id != args.discord_channel_id:
                if not args.dry_run:
                    crew.discord_channel_id = args.discord_channel_id
                updated_fields.append(f"discord_channel_id={args.discord_channel_id}")
            if args.info_channel_id is not None and crew.info_channel_id != args.info_channel_id:
                if not args.dry_run:
                    crew.info_channel_id = args.info_channel_id
                updated_fields.append(f"info_channel_id={args.info_channel_id}")
            if crew.district != district:
                if not args.dry_run:
                    crew.district = district
                updated_fields.append(f"district={district!r}")

            # Story-Update
            if story is not None:
                has_existing = bool((crew.story_background or "").strip())
                if has_existing and not args.force:
                    print(f"  [skip-story] Crew hat bereits Story "
                          f"({len(crew.story_background)} Zeichen). --force zum Ueberschreiben.")
                else:
                    action = "update" if has_existing else "set"
                    print(f"  [story-{action}] {len(story)} Zeichen.")
                    if not args.dry_run:
                        crew.story_background = story

            if updated_fields:
                print(f"  [fields] {', '.join(updated_fields)}")
            elif story is None:
                print("  Nichts zu aktualisieren.")

        # Optional: Story an Stadtteil-MD anhaengen
        if story and args.append_to_md:
            append_story_to_district_md(district, name, story, args.dry_run)

        if args.dry_run:
            print("\n=== DRY-RUN: keine Aenderungen gespeichert ===")
            await session.rollback()
        else:
            await session.commit()
            print("\n=== Aenderungen gespeichert ===")
            if crew and crew.id:
                print(f"   Crew-ID: {crew.id}  (sichtbar im Dashboard und auf der Lore-Seite)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--name", required=True, help="Crew-Name (eindeutig)")
    parser.add_argument("--district", required=True,
                        help="Algonquin | Bohan | Broker | Colony Island | Dukes")
    parser.add_argument("--story-file", help="Pfad zur Markdown-Story-Datei")
    parser.add_argument("--story-stdin", action="store_true",
                        help="Story von stdin lesen (statt --story-file)")
    parser.add_argument("--color-hex", help="Hex-Farbe (default: Stadtteil-Farbe)")
    parser.add_argument("--discord-channel-id", help="Discord Auftrags-Channel-ID")
    parser.add_argument("--info-channel-id", help="Discord Info-/Boss-Channel-ID")
    parser.add_argument("--force", action="store_true",
                        help="Story ueberschreiben, auch wenn bereits befuellt")
    parser.add_argument("--append-to-md", action="store_true",
                        help="Story an docs/gang-stories/<district>.md anhaengen")
    parser.add_argument("--dry-run", action="store_true",
                        help="Zeigt nur, was gemacht wuerde, schreibt nichts")
    args = parser.parse_args()

    asyncio.run(run_add(args))


if __name__ == "__main__":
    main()
