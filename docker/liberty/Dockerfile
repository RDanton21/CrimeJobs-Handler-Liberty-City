# =============================================================================
# Liberty City Donations — Ko-fi + Twitch + Admin Panel
# =============================================================================
FROM python:3.13-slim

WORKDIR /app

# Source-Code wird beim Build per build-context kopiert
# (Quelle wird in deploy-script vom Windows-Pfad in den docker-context kopiert)
COPY src/ /app/

# Dependencies
RUN if [ -f requirements.txt ]; then \
        pip install --no-cache-dir --upgrade pip && \
        pip install --no-cache-dir -r requirements.txt; \
    fi

# Persistente Verzeichnisse für JSON-State + Logs
RUN mkdir -p /app/data /app/logs

# Web-Routen:
# - 8080: Ko-fi-Webhook + Admin-Panel (liberty_city_relay.py)
# - 8081: Optionales separates Dashboard (white_house_dashboard_server.py)
EXPOSE 8080 8081

# Working-Dir auf JSON-Files setzen, damit sie im Volume landen
WORKDIR /app

CMD ["python", "liberty_city_relay.py"]
