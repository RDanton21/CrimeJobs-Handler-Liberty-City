@echo off
REM Crime Automation Launcher
REM - startet Services falls noch nicht laufend (kein Effekt wenn schon up)
REM - oeffnet Browser zu Admin-Dashboard

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { Start-Service CrimeAutoBackend, CrimeAutoBot -ErrorAction SilentlyContinue } catch {}"

timeout /t 1 /nobreak >nul

start "" "http://127.0.0.1:8000"
