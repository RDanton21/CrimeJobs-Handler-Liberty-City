# =============================================================================
# Countdown Bot — Discord + Flask Admin (Pillow für Bild-Render)
# =============================================================================
FROM python:3.13-slim

# Pillow braucht libfreetype + libjpeg für TTF + JPG-Render
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 \
    libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Source-Code wird durch migrate_sources.sh aus D:\Countdown\ kopiert
COPY src/ /app/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Persistent: countdowns.json + state.json
RUN mkdir -p /app/data /app/logs

# Symlinks setzen, damit Code-State-Files im Volume landen
# (Original-Code schreibt sie direkt ins WORKDIR)
RUN ln -sf /app/data/countdowns.json /app/countdowns.json \
    && ln -sf /app/data/state.json /app/state.json

EXPOSE 5601

# Startet bot.py (Discord) — admin.py wird vom bot.py als Thread gestartet
CMD ["python", "bot.py"]
