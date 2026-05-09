@echo off
REM Smoke-Test: prueft Python, venv, Imports, .env

cd /d "%~dp0\.."

echo [verify] Python-Version:
where python || (echo Python nicht im PATH! && exit /b 1)
python --version

if not exist .venv (
  echo [verify] FEHLER: .venv fehlt. Erst scripts\setup.bat ausfuehren.
  exit /b 1
)

call .venv\Scripts\activate.bat

echo.
echo [verify] Module importieren...
python -c "import fastapi, uvicorn, sqlalchemy, aiosqlite, pydantic, anthropic, openai, discord, httpx, aiofiles; print('  OK: alle Deps importiert')" || exit /b 1

echo.
echo [verify] Backend-Module:
python -c "from backend import config, db, models, schemas, prompts, ai, auth, settings_store; print('  OK: Backend-Imports')" || exit /b 1
python -c "from backend.routes_crews import router as r1; from backend.routes_missions import router as r2; from backend.routes_settings import router as r3; print('  OK: Routes')" || exit /b 1
python -c "from backend import bot; print('  OK: Bot-Modul')" || exit /b 1

echo.
echo [verify] .env:
if not exist .env (
  echo   WARNUNG: .env fehlt — bitte aus .env.example kopieren und befuellen.
) else (
  python -c "from backend.config import settings; print('  ADMIN_USERNAME =', settings.admin_username); print('  DISCORD_BOT_TOKEN =', 'gesetzt' if settings.discord_bot_token else 'FEHLT'); print('  ANTHROPIC_API_KEY =', 'gesetzt' if settings.anthropic_api_key else 'leer (UI)'); print('  OPENAI_API_KEY =', 'gesetzt' if settings.openai_api_key else 'leer (UI)')"
)

echo.
echo [verify] DB-Init testen...
python -c "import asyncio; from backend.db import init_db; asyncio.run(init_db()); print('  OK: SQLite init + tables')" || exit /b 1

echo.
echo [verify] FERTIG.
pause
