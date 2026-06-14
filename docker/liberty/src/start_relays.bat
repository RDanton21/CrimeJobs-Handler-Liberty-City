@echo off
title 5EKTOR StreamHub
cd /d "%~dp0"

echo ========= 5EKTOR StreamHub =========
echo Starte Liberty City Relay (Ko-fi + Twitch)...
echo =====================================
echo.

REM ---------- VENV ----------
set "PY=python"
if exist "venv\Scripts\python.exe" (
  set "PY=venv\Scripts\python.exe"
)

REM ---------- START ----------
start "StreamHub Relay" cmd /k ""%PY%" "liberty_city_relay.py""

echo Relay wurde gestartet!
pause
