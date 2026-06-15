#!/bin/sh
# Startet Discord-Bot (bot.py) UND Flask-Admin (admin.py) parallel.
# bot.py läuft im Foreground (PID 1), admin.py als Hintergrund-Prozess.
# Bei Container-Stop killt Docker beide via SIGTERM.

set -e

echo "[start.sh] Flask-Admin auf ${ADMIN_HOST:-0.0.0.0}:${ADMIN_PORT:-5601} starten..."
python /app/admin.py &
ADMIN_PID=$!

echo "[start.sh] Discord-Bot starten (PID 1)..."
# trap weiterleiten damit Admin sauber gekillt wird
trap "kill $ADMIN_PID 2>/dev/null; exit 0" TERM INT
exec python /app/bot.py
