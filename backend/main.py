from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .auth import require_admin
from .config import settings
from .db import init_db
from .routes_crews import router as crews_router
from .routes_expiry import router as expiry_router
from .routes_lore import router as lore_router
from .routes_missions import router as missions_router
from .routes_reaction import router as reaction_router
from .routes_settings import router as settings_router
from .routes_system_prompts import router as system_prompts_router

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


@app.get("/api/health")
async def health():
    return {"ok": True}


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


@app.get("/favicon.ico")
async def favicon():
    return RedirectResponse("/static/favicon.svg")
