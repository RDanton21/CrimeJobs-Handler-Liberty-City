@echo off
title 5EKTOR StreamHub - Stopper

echo Beende 5EKTOR StreamHub Services...
echo.

REM Beende Ko-fi Relay Fenster
taskkill /FI "WINDOWTITLE eq Ko-fi Relay" /T /F >nul 2>&1

REM Beende Twitch Relay Fenster
taskkill /FI "WINDOWTITLE eq Twitch Relay" /T /F >nul 2>&1

echo Alle Relays wurden beendet!
pause
