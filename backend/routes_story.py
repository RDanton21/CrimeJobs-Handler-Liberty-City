"""Story-Editor: liest/schreibt die Kern-Story-Markdown-Files unter docs/.

Whitelist-only — nur die hier definierten Files können gelesen oder
geschrieben werden (verhindert Path-Traversal). Beim Speichern wird die
vorherige Version als `.bak` neben der Datei abgelegt."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .ai import get_provider
from .auth import require_admin
from .config import settings as app_settings
from .db import get_session
from .quest_givers_ai import apply_recommendation, check_quest_givers_consistency
from .settings_store import get as settings_get

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
    "QUEST_PERSONNEL.md": "🎭 NPC-Pool",
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


# Welche Story-Files in den Konsistenz-Check einfliessen
_CONSISTENCY_STORY_FILES = [
    "EVENT_BRIEFING.md",
    "EVENT_TIMELINE.md",
    "CITY_PUBLIC_BRIEFING.md",
]


@router.post("/quest-givers/consistency-check")
async def quest_givers_consistency_check(
    session: AsyncSession = Depends(get_session),
):
    """Vergleicht QUEST_GIVERS.md mit der aktuellen Event-Story
    (EVENT_BRIEFING + TIMELINE + CITY_PUBLIC_BRIEFING) und liefert einen
    Markdown-Report: passen die Mittler noch? Wo gibt es Lücken?

    Antwort: { report: '<markdown>' }
    """
    givers_path = DOCS_DIR / "QUEST_GIVERS.md"
    if not givers_path.exists():
        raise HTTPException(404, "QUEST_GIVERS.md existiert nicht")
    givers_md = givers_path.read_text(encoding="utf-8")

    # Story-Files zusammenstellen (nur die, die existieren)
    parts: list[str] = []
    for fname in _CONSISTENCY_STORY_FILES:
        p = DOCS_DIR / fname
        if p.exists():
            parts.append(f"## {fname}\n\n{p.read_text(encoding='utf-8')}")
    if not parts:
        raise HTTPException(404, "Keine Story-Files vorhanden (EVENT_BRIEFING / TIMELINE / CITY_PUBLIC_BRIEFING)")
    story_md = "\n\n---\n\n".join(parts)

    # Default-Provider auflösen
    keys = {
        "anthropic": await settings_get(session, "anthropic_api_key", app_settings.anthropic_api_key),
        "openai": await settings_get(session, "openai_api_key", app_settings.openai_api_key),
    }
    models = {
        "claude": await settings_get(session, "default_claude_model", app_settings.default_claude_model),
        "openai": await settings_get(session, "default_openai_model", app_settings.default_openai_model),
    }
    provider_name = await settings_get(session, "default_provider", app_settings.default_ai_provider)
    try:
        provider = await get_provider(provider_name, keys=keys, models=models)
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc

    try:
        report, recommendations = await check_quest_givers_consistency(
            provider, story_md, givers_md
        )
    except Exception as exc:
        raise HTTPException(502, f"KI-Check fehlgeschlagen: {exc}") from exc
    if not report:
        raise HTTPException(502, "KI hat keinen Report generiert")
    return {
        "report": report,
        "recommendations": recommendations,
        "story_files_used": [f for f in _CONSISTENCY_STORY_FILES if (DOCS_DIR / f).exists()],
        "givers_size": len(givers_md),
    }


class ApplyRecommendationRequest(BaseModel):
    instruction: str


@router.post("/quest-givers/apply-recommendation")
async def apply_quest_givers_recommendation(
    payload: ApplyRecommendationRequest,
    session: AsyncSession = Depends(get_session),
):
    """Lässt die KI eine konkrete Edit-Anweisung auf QUEST_GIVERS.md anwenden.
    Returnt den NEUEN Datei-Inhalt — wird NICHT direkt gespeichert. Das
    Frontend zeigt eine Vorschau, der User bestätigt, dann über den
    normalen PUT /file/QUEST_GIVERS.md gespeichert."""
    instruction = (payload.instruction or "").strip()
    if not instruction:
        raise HTTPException(400, "instruction darf nicht leer sein")

    givers_path = DOCS_DIR / "QUEST_GIVERS.md"
    if not givers_path.exists():
        raise HTTPException(404, "QUEST_GIVERS.md existiert nicht")
    current = givers_path.read_text(encoding="utf-8")

    # Story-Kontext für besseren Edit (KI sieht, in welches Universum das passen muss)
    parts: list[str] = []
    for fname in _CONSISTENCY_STORY_FILES:
        p = DOCS_DIR / fname
        if p.exists():
            parts.append(f"## {fname}\n\n{p.read_text(encoding='utf-8')}")
    story_md = "\n\n---\n\n".join(parts)

    # Provider auflösen
    keys = {
        "anthropic": await settings_get(session, "anthropic_api_key", app_settings.anthropic_api_key),
        "openai": await settings_get(session, "openai_api_key", app_settings.openai_api_key),
    }
    models = {
        "claude": await settings_get(session, "default_claude_model", app_settings.default_claude_model),
        "openai": await settings_get(session, "default_openai_model", app_settings.default_openai_model),
    }
    provider_name = await settings_get(session, "default_provider", app_settings.default_ai_provider)
    try:
        provider = await get_provider(provider_name, keys=keys, models=models)
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc

    try:
        new_content = await apply_recommendation(
            provider, current, instruction, story_md
        )
    except Exception as exc:
        raise HTTPException(502, f"KI-Edit fehlgeschlagen: {exc}") from exc
    if not new_content:
        raise HTTPException(502, "KI hat keinen neuen Inhalt generiert")

    return {
        "new_content": new_content,
        "old_size": len(current),
        "new_size": len(new_content),
    }
