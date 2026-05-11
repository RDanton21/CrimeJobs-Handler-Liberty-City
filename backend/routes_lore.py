"""Lore-Routen: liefert Stadtteil-Beschreibungen aus docs/DISTRICTS.md
fuer die Lore-Seite im Dashboard.

Stories der einzelnen Crews kommen ueber den bestehenden /api/crews-Endpoint
(Feld story_background) — kein separater Endpoint noetig.
"""
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from .auth import require_admin

router = APIRouter(prefix="/api/lore", tags=["lore"], dependencies=[Depends(require_admin)])

ROOT_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT_DIR / "docs"

# Slug-Mapping fuer URL-/CSS-/Filter-Verwendung im Frontend
DISTRICT_SLUGS = {
    "Algonquin": "algonquin",
    "Bohan": "bohan",
    "Broker": "broker",
    "Colony Island": "colony-island",
    "Dukes": "dukes",
}


@router.get("/districts")
async def get_districts() -> dict:
    """Liefert die 5 Stadtteile mit ihrem Markdown-Inhalt.

    Splittet docs/DISTRICTS.md an den `## `-Headern und filtert nur die
    Stadtteil-Sektionen (kein Footer-/Intro-Block).
    """
    md_path = DOCS_DIR / "DISTRICTS.md"
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="DISTRICTS.md not found")

    text = md_path.read_text(encoding="utf-8")
    parts = re.split(r"^## ", text, flags=re.MULTILINE)
    intro = parts[0].strip()  # globaler Header (Quelle-der-Wahrheit-Block)

    districts = []
    for raw in parts[1:]:
        lines = raw.split("\n", 1)
        if len(lines) < 2:
            continue
        name = lines[0].strip()
        if name not in DISTRICT_SLUGS:
            continue
        body = lines[1]
        # Footer- und horizontalen Trenner entfernen
        body = re.sub(
            r"\n*\*Stadtteil-Lore vollständig:.*?\*\n*$",
            "",
            body,
            flags=re.DOTALL,
        )
        body = re.sub(r"\n*---\n*$", "", body)
        districts.append({
            "name": name,
            "slug": DISTRICT_SLUGS[name],
            "content_md": f"## {name}\n\n{body.strip()}",
        })

    # Sortierung wie in der Karte / im Frontend ueblich
    order = ["Algonquin", "Bohan", "Broker", "Colony Island", "Dukes"]
    districts.sort(key=lambda d: order.index(d["name"]) if d["name"] in order else 99)

    return {"intro_md": intro, "districts": districts}
