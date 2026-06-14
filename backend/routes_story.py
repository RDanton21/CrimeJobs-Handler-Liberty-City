"""Story-Editor: liest/schreibt die Kern-Story-Markdown-Files unter docs/.

Whitelist-only — nur die hier definierten Files können gelesen oder
geschrieben werden (verhindert Path-Traversal). Beim Speichern wird die
vorherige Version als `.bak` neben der Datei abgelegt."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import require_admin

router = APIRouter(prefix="/api/story", tags=["story"], dependencies=[Depends(require_admin)])

ROOT_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT_DIR / "docs"

# Whitelist: filename -> display-label im UI
ALLOWED_STORY_FILES: dict[str, str] = {
    "EVENT_BRIEFING.md": "🎬 Eröffnungs-Kapitel",
    "EVENT_TIMELINE.md": "📅 10-Tage-Timeline",
    "EVENT_FINALE.md": "🏁 Finale",
    "EVENT_BRIEFINGS_MASS.md": "📢 Massen-Briefings",
    "CITY_PUBLIC_BRIEFING.md": "🌃 Öffentliche Grundstory",
    "QUEST_GIVERS.md": "👤 Quest-Geber",
    "DISTRICTS.md": "🗺️ Stadtteile",
    "CREW_RELATIONS.md": "🔗 Crew-Beziehungen",
}


class StoryFileUpdate(BaseModel):
    content: str


def _resolve_safe(filename: str) -> Path:
    """Whitelist-Check + Path-Traversal-Schutz."""
    if filename not in ALLOWED_STORY_FILES:
        raise HTTPException(404, "Datei nicht in Whitelist")
    path = (DOCS_DIR / filename).resolve()
    # Sicherheit: muss innerhalb DOCS_DIR bleiben
    try:
        path.relative_to(DOCS_DIR.resolve())
    except ValueError:
        raise HTTPException(400, "Ungültiger Pfad")
    return path


@router.get("/files")
async def list_story_files():
    """Liste der editierbaren Story-Files mit Label und Größe."""
    out = []
    for filename, label in ALLOWED_STORY_FILES.items():
        path = DOCS_DIR / filename
        exists = path.exists()
        out.append({
            "filename": filename,
            "label": label,
            "exists": exists,
            "size": path.stat().st_size if exists else 0,
        })
    return out


@router.get("/file/{filename}")
async def get_story_file(filename: str):
    path = _resolve_safe(filename)
    if not path.exists():
        return {"filename": filename, "content": "", "exists": False, "size": 0}
    content = path.read_text(encoding="utf-8")
    return {
        "filename": filename,
        "content": content,
        "exists": True,
        "size": path.stat().st_size,
    }


@router.put("/file/{filename}")
async def update_story_file(filename: str, payload: StoryFileUpdate):
    path = _resolve_safe(filename)
    # Backup vor dem Schreiben
    if path.exists():
        bak = path.with_suffix(path.suffix + ".bak")
        try:
            bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass  # Backup-Fehler darf den Save nicht blockieren
    path.write_text(payload.content, encoding="utf-8")
    return {"ok": True, "size": path.stat().st_size}
