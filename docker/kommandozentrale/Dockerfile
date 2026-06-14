# =============================================================================
# Kommandozentrale — Web-Dashboard für alle Bots
# Kommuniziert mit Docker-Engine über /var/run/docker.sock
# =============================================================================
FROM python:3.13-slim

WORKDIR /app

# Install: FastAPI + uvicorn + Docker-SDK
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        'fastapi>=0.110' \
        'uvicorn[standard]>=0.30' \
        'docker>=7.0' \
        'jinja2>=3.1' \
        'python-multipart' \
        'psutil>=5.9'

# Backend + Frontend
COPY backend /app/backend
COPY frontend /app/frontend

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend.main:app", \
     "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
