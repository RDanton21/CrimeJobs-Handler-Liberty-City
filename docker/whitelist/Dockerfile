# =============================================================================
# Whitelist Bot (S6-WLH-Bot)
# Discord ↔ sektorrp.eu Webseiten-DB Sync
# =============================================================================
FROM python:3.13-slim

WORKDIR /app

# Source-Code wird durch migrate_sources.sh aus D:\bot\ kopiert
COPY src/ /app/

# Dependencies (discord.py, mysql-connector-python, python-dotenv)
RUN if [ -f requirements.txt ]; then \
        pip install --no-cache-dir --upgrade pip && \
        pip install --no-cache-dir -r requirements.txt; \
    else \
        pip install --no-cache-dir \
            'discord.py>=2.3.0' \
            'mysql-connector-python>=8.0.0' \
            'python-dotenv>=1.0.0'; \
    fi

# Kein Web-UI, läuft nur als Discord-Bot
CMD ["python", "bot.py"]
