"""Lore-Routen: liefert Stadtteil-Beschreibungen und erlaubt Editieren.

Stadtteil-Quellen:
- Default: docs/DISTRICTS.md (Repo-Datei, geteilt fuer alle)
- Override: docs/districts_overrides/{slug}.md (pro User editierbar, nicht im Repo)
  Wenn ein Override existiert, wird er statt dem Default geliefert.

Stories der einzelnen Crews kommen ueber den bestehenden /api/crews-Endpoint
(Feld story_background) — kein separater Endpoint noetig.
"""
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import require_admin

router = APIRouter(prefix="/api/lore", tags=["lore"], dependencies=[Depends(require_admin)])

ROOT_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT_DIR / "docs"
OVERRIDES_DIR = DOCS_DIR / "districts_overrides"

# Slug-Mapping fuer URL-/CSS-/Filter-Verwendung im Frontend
DISTRICT_SLUGS = {
    "Algonquin": "algonquin",
    "Bohan": "bohan",
    "Broker": "broker",
    "Colony Island": "colony-island",
    "Dukes": "dukes",
}

# Reverse-Lookup: slug -> Name (fuer PATCH-Endpoint)
SLUG_TO_NAME = {v: k for k, v in DISTRICT_SLUGS.items()}


class DistrictUpdate(BaseModel):
    content_md: str


def _district_from_default_md(name: str, body: str) -> dict:
    """Erzeugt einen District-Eintrag aus dem geparsten Markdown."""
    return {
        "name": name,
        "slug": DISTRICT_SLUGS[name],
        "content_md": f"## {name}\n\n{body.strip()}",
        "has_override": False,
    }


def _load_default_districts() -> tuple[str, dict[str, dict]]:
    """Liest docs/DISTRICTS.md und liefert (intro_md, {name: district_dict})."""
    md_path = DOCS_DIR / "DISTRICTS.md"
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="DISTRICTS.md not found")

    text = md_path.read_text(encoding="utf-8")
    parts = re.split(r"^## ", text, flags=re.MULTILINE)
    intro = parts[0].strip()

    by_name: dict[str, dict] = {}
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
        by_name[name] = _district_from_default_md(name, body)

    return intro, by_name


@router.get("/districts")
async def get_districts() -> dict:
    """Liefert die 5 Stadtteile mit ihrem Markdown-Inhalt.

    Wenn ein Override unter docs/districts_overrides/{slug}.md existiert,
    wird dieser bevorzugt geliefert (mit has_override=True).
    """
    intro, by_name = _load_default_districts()

    districts: list[dict] = []
    order = ["Algonquin", "Bohan", "Broker", "Colony Island", "Dukes"]
    for name in order:
        if name not in by_name:
            continue
        d = by_name[name]
        # Override pruefen
        override_path = OVERRIDES_DIR / f"{d['slug']}.md"
        if override_path.exists():
            d = {
                **d,
                "content_md": override_path.read_text(encoding="utf-8").strip(),
                "has_override": True,
            }
        districts.append(d)

    return {"intro_md": intro, "districts": districts}


@router.patch("/districts/{slug}")
async def update_district(slug: str, payload: DistrictUpdate) -> dict:
    """Speichert geaenderten Markdown-Inhalt eines Stadtteils als Override-File."""
    if slug not in SLUG_TO_NAME:
        raise HTTPException(404, f"Unknown district slug: {slug}")
    OVERRIDES_DIR.mkdir(parents=True, exist_ok=True)
    override_path = OVERRIDES_DIR / f"{slug}.md"
    override_path.write_text(payload.content_md.strip() + "\n", encoding="utf-8")
    return {
        "ok": True,
        "slug": slug,
        "name": SLUG_TO_NAME[slug],
        "content_md": payload.content_md.strip(),
        "has_override": True,
    }


@router.delete("/districts/{slug}/override", status_code=204)
async def delete_district_override(slug: str) -> None:
    """Loescht das Override-File und stellt den Default aus DISTRICTS.md wieder her."""
    if slug not in SLUG_TO_NAME:
        raise HTTPException(404, f"Unknown district slug: {slug}")
    override_path = OVERRIDES_DIR / f"{slug}.md"
    if override_path.exists():
        override_path.unlink()
