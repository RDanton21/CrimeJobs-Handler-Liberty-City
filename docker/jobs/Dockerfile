# =============================================================================
# SEKTOR Personal-Boerse — Jobs-Dashboard
# Spieler loggen sich mit Discord ein und tragen sich in Personal-Slots
# der Crime-Auftraege ein (10-Tage-Event-Board).
# =============================================================================
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY src/ /app/src/

# Datenverzeichnis fuer jobs.db (im Compose als Volume mounten!)
RUN mkdir -p /app/data

EXPOSE 8080

# --proxy-headers: Traefik terminiert TLS; X-Forwarded-Proto/-For uebernehmen,
# damit request.url.scheme https ist. Port 8080 ist nur im Docker-Netz erreichbar,
# daher ist forwarded-allow-ips=* hier vertretbar (nur Traefik kommt ran).
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
