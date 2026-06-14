# =============================================================================
# Ticket Bot — RAG-System (Discord + Claude + ChromaDB + sentence-transformers)
# =============================================================================
# Größe: ~ 3.5 GB (wegen torch + transformers)
# Build-Zeit: ~ 10-15 Min beim ersten Mal (Modell-Download beim 1. Start)
# =============================================================================
FROM python:3.12-slim AS builder

# Build-Dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libffi-dev \
    libssl-dev \
    libfreetype6-dev \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Source-Code wird durch migrate_sources.sh aus D:\Ticket Tool\ kopiert
COPY src/ /build/

# Torch CPU-only (spart 2 GB vs. CUDA-Variante)
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
        'torch>=2.0,<3.0' \
    && pip install --no-cache-dir -r requirements.txt

# -----------------------------------------------------------------------------
# Runtime-Stage — schlanker
# -----------------------------------------------------------------------------
FROM python:3.12-slim

# Runtime-Deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 \
    libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

# Python-Packages aus dem Builder kopieren
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

WORKDIR /app

# Source-Code
COPY src/ /app/

# Persistente Volumes
RUN mkdir -p /app/data /app/kb /app/logs /app/hf-cache

# Hugging-Face-Modell-Cache (vermeidet Re-Download bei Container-Restart)
ENV HF_HOME=/app/hf-cache \
    TRANSFORMERS_CACHE=/app/hf-cache \
    SENTENCE_TRANSFORMERS_HOME=/app/hf-cache

EXPOSE 5555

# bot.py startet Discord + Admin-Panel (Flask) in einem Prozess
CMD ["python", "bot.py"]
