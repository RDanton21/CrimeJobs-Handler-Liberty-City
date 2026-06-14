#!/usr/bin/env bash
# =============================================================================
# SEKT6R Migration — Source-Files in Docker-Build-Contexts kopieren
# =============================================================================
# Kopiert die Bot-Source-Codes von ihren Original-Pfaden in die docker/X/src/-
# Verzeichnisse. Wird VOR `docker compose build` aufgerufen.
#
# Wo läuft das Script?
#   - Auf Windows-Dev-PC (Git Bash): zur Vorbereitung des Repo-Pushs
#   - Auf VPS (Bash): falls Sources direkt dort liegen (selten)
#
# Sicherheit: kopiert KEINE .env-Files (Tokens kommen direkt aus VPS-.env)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$SCRIPT_DIR"

# Source-Pfade (Windows-Style mit /d/ statt D:/ für Git Bash)
LIBERTY_SRC="${LIBERTY_SRC:-/d/V2026_Kofi_Twitch_Script_sanitized}"
WHITELIST_SRC="${WHITELIST_SRC:-/d/bot}"
TICKET_SRC="${TICKET_SRC:-/d/Ticket Tool}"
COUNTDOWN_SRC="${COUNTDOWN_SRC:-/d/Countdown}"

# Color output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[migrate]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*" >&2; }
err() { echo -e "${RED}[error]${NC} $*" >&2; }

# -----------------------------------------------------------------------------
# Hilfsfunktion: Source-Files kopieren, .env / venv / cache ausschließen
# -----------------------------------------------------------------------------
copy_clean() {
    local src="$1"
    local dst="$2"

    if [ ! -d "$src" ]; then
        warn "Source nicht gefunden: $src — übersprungen"
        return 1
    fi

    mkdir -p "$dst"
    rm -rf "$dst"/* "$dst"/.[!.]* 2>/dev/null || true

    # rsync mit Excludes
    if command -v rsync >/dev/null 2>&1; then
        rsync -a \
            --exclude='.env' \
            --exclude='.env.local' \
            --exclude='.env.production' \
            --exclude='.git' \
            --exclude='__pycache__' \
            --exclude='*.pyc' \
            --exclude='venv' \
            --exclude='.venv' \
            --exclude='*.log' \
            --exclude='logs' \
            --exclude='data' \
            "$src/" "$dst/"
    else
        # Fallback ohne rsync (cp)
        cp -r "$src/." "$dst/"
        find "$dst" -name '.env' -delete 2>/dev/null || true
        find "$dst" -name '.env.local' -delete 2>/dev/null || true
        find "$dst" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
        find "$dst" -type d -name 'venv' -exec rm -rf {} + 2>/dev/null || true
        find "$dst" -type d -name '.venv' -exec rm -rf {} + 2>/dev/null || true
        find "$dst" -type d -name '.git' -exec rm -rf {} + 2>/dev/null || true
        find "$dst" -name '*.pyc' -delete 2>/dev/null || true
        find "$dst" -name '*.log' -delete 2>/dev/null || true
    fi

    local n_files=$(find "$dst" -type f | wc -l | tr -d ' ')
    log "  $src → $dst  (${n_files} Dateien)"
    return 0
}

# -----------------------------------------------------------------------------
# Special: Ticket-Bot — src/-Inhalt + requirements.txt in dst kopieren
# -----------------------------------------------------------------------------
copy_ticket() {
    local src="$1"
    local dst="$2"

    if [ ! -d "$src" ]; then
        warn "Ticket-Source nicht gefunden: $src"
        return 1
    fi

    mkdir -p "$dst"
    rm -rf "$dst"/* "$dst"/.[!.]* 2>/dev/null || true

    # src/ kopieren (Python-Dateien direkt nach $dst/)
    if [ -d "$src/src" ]; then
        cp -r "$src/src/"*.py "$dst/" 2>/dev/null || true
    fi

    # requirements.txt aus Root mitnehmen
    if [ -f "$src/requirements.txt" ]; then
        cp "$src/requirements.txt" "$dst/requirements.txt"
    fi

    # kb/ Knowledge-Base als initialer Seed (wird zur Laufzeit per Volume gemounted)
    if [ -d "$src/kb" ]; then
        mkdir -p "$dst/initial-kb"
        cp -r "$src/kb/." "$dst/initial-kb/" 2>/dev/null || true
    fi

    # Aufräumen
    find "$dst" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
    find "$dst" -name '*.pyc' -delete 2>/dev/null || true

    local n_files=$(find "$dst" -type f | wc -l | tr -d ' ')
    log "  $src → $dst  (${n_files} Dateien)"
    return 0
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
echo "================================================================================"
echo "  SEKT6R Source Migration"
echo "================================================================================"
echo ""

log "Liberty (Du bist Liberty)..."
copy_clean "$LIBERTY_SRC" "$DOCKER_DIR/liberty/src" || warn "Liberty: skipped"
echo ""

log "Whitelist Bot (S6-WLH-Bot)..."
copy_clean "$WHITELIST_SRC" "$DOCKER_DIR/whitelist/src" || warn "Whitelist: skipped"
echo ""

log "Ticket Bot..."
copy_ticket "$TICKET_SRC" "$DOCKER_DIR/ticket/src" || warn "Ticket: skipped"
echo ""

log "Countdown..."
copy_clean "$COUNTDOWN_SRC" "$DOCKER_DIR/countdown/src" || warn "Countdown: skipped"
echo ""

log "FERTIG. Nächster Schritt:"
echo "  cd $DOCKER_DIR"
echo "  cp .env.example .env"
echo "  nano .env  # Tokens eintragen"
echo "  docker compose up -d --build"
