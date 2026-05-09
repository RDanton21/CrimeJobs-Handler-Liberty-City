@echo off
cd /d "%~dp0\.."
start "Crime-Automation Bot" cmd /k scripts\run_bot.bat
timeout /t 3 /nobreak >nul
start "Crime-Automation Backend" cmd /k scripts\run_backend.bat
echo.
echo Backend  → http://127.0.0.1:8000
echo Bot HTTP → http://127.0.0.1:8001/health
echo.
pause
