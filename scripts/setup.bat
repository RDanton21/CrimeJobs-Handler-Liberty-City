@echo off
REM Erst-Setup: venv anlegen, requirements installieren, .env kopieren

cd /d "%~dp0\.."

REM Runtime-Ordner sicherstellen
if not exist data mkdir data
if not exist data\images mkdir data\images
if not exist logs mkdir logs

if not exist .venv (
  echo [setup] virtuelles Environment anlegen...
  py -3.11 -m venv .venv || py -3.12 -m venv .venv || python -m venv .venv
  if errorlevel 1 (
    echo FEHLER: konnte venv nicht anlegen. Python 3.11 oder 3.12 installieren.
    exit /b 1
  )
)

call .venv\Scripts\activate.bat

echo [setup] pip upgrade...
python -m pip install --upgrade pip

echo [setup] requirements installieren...
pip install -r requirements.txt
if errorlevel 1 (
  echo FEHLER bei pip install. Pruefe Verbindung oder fehlende Build-Tools.
  exit /b 1
)

if not exist .env (
  echo [setup] .env aus .env.example anlegen
  copy .env.example .env
  echo.
  echo .env wurde angelegt — bitte DISCORD_BOT_TOKEN + ADMIN_PASSWORD eintragen!
)

echo.
echo [setup] FERTIG.
echo   Naechste Schritte:
echo     1. .env oeffnen + DISCORD_BOT_TOKEN, ADMIN_PASSWORD setzen
echo     2. scripts\verify.bat
echo     3. scripts\run_all.bat
echo.
pause
