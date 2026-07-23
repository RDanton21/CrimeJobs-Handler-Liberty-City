from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .auth import require_admin
from .config import settings
from .db import init_db
from .routes_crews import router as crews_router
from .routes_dashboard import router as dashboard_router
from .routes_expiry import router as expiry_router
from .routes_lore import router as lore_router
from .routes_missions import router as missions_router
from .routes_reaction import router as reaction_router
from .routes_settings import router as settings_router
from .routes_relations_survey import router as relations_survey_router
from .routes_slots import public_router as public_slots_router
from .routes_slots import router as slots_router
from .routes_story import router as story_router
from .routes_system_prompts import router as system_prompts_router
from .routes_top3_titles import router as top3_titles_router

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    Path(settings.image_dir).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Crime Automation", version="0.1.0", lifespan=lifespan)

app.include_router(crews_router)
app.include_router(missions_router)
app.include_router(settings_router)
app.include_router(expiry_router)
app.include_router(reaction_router)
app.include_router(system_prompts_router)
app.include_router(lore_router)
app.include_router(story_router)
app.include_router(top3_titles_router)
app.include_router(dashboard_router)
app.include_router(slots_router)
app.include_router(public_slots_router)
app.include_router(relations_survey_router)


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.middleware("http")
async def _revalidate_static(request, call_next):
    """Statische Assets immer revalidieren lassen.

    Ohne Cache-Control cacht der Browser /static/app.js heuristisch und
    liefert nach einem Deploy weiter die alte Datei — die neue index.html
    traf dann auf altes JS, wodurch Handler ins Leere liefen. Die manuellen
    ?v=-Strings in den HTML-Dateien wurden dabei regelmaessig vergessen.

    'no-cache' heisst nicht 'nicht cachen', sondern 'vor Benutzung nachfragen':
    StaticFiles liefert ETag + Last-Modified, die Rueckfrage endet also in
    aller Regel bei einem billigen 304.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# Frontend static
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
app.mount("/images", StaticFiles(directory=str(Path(settings.image_dir))), name="images")


@app.get("/")
async def root(_user: str = Depends(require_admin)):
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/crew/{crew_id}")
async def crew_page(crew_id: int, _user: str = Depends(require_admin)):
    return FileResponse(str(FRONTEND_DIR / "crew.html"))


@app.get("/settings")
async def settings_page(_user: str = Depends(require_admin)):
    return FileResponse(str(FRONTEND_DIR / "settings.html"))


@app.get("/archive")
async def archive_page(_user: str = Depends(require_admin)):
    return FileResponse(str(FRONTEND_DIR / "archive.html"))


@app.get("/lore")
async def lore_page(_user: str = Depends(require_admin)):
    return FileResponse(str(FRONTEND_DIR / "lore.html"))


@app.get("/ranking")
async def ranking_page(_user: str = Depends(require_admin)):
    return FileResponse(str(FRONTEND_DIR / "ranking.html"))


@app.get("/beziehungen")
async def relations_page(_user: str = Depends(require_admin)):
    return FileResponse(str(FRONTEND_DIR / "relations.html"))


@app.get("/story")
async def story_page(_user: str = Depends(require_admin)):
    return FileResponse(str(FRONTEND_DIR / "story.html"))


@app.get("/mittler")
async def quest_givers_page(_user: str = Depends(require_admin)):
    """Read-Only-Ansicht der Quest-Geber (Mittler) + NPC-Pool."""
    return FileResponse(str(FRONTEND_DIR / "quest_givers.html"))


@app.get("/personnel")
async def personnel_page(_user: str = Depends(require_admin)):
    """Personal-Bedarf: Live-Widget, früher im Dashboard, jetzt eigener Reiter."""
    return FileResponse(str(FRONTEND_DIR / "personnel.html"))


@app.get("/favicon.ico")
async def favicon():
    return RedirectResponse("/static/favicon.svg")
