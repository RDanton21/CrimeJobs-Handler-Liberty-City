#!/usr/bin/env bash
# =============================================================================
# Sync Crime-Automation DB: Docker (Hostinger) -> Dedicated
# =============================================================================
# Ausführung: auf dem Hostinger-VPS als sekt6r-User (per Cron oder manuell)
# Kopiert die aktuelle SQLite-DB aus dem Docker-Volume auf den Dedicated
# als Backup — damit du im Katastrophenfall zurückwechseln kannst.
#
# Voraussetzungen auf dem VPS:
# - SSH-Key des sekt6r-Users muss auf dem Dedicated (RDanton21@116.202.174.56)
#   akzeptiert sein (~/.ssh/authorized_keys)
#
# Cron-Beispiel (crontab -e):
#   0 3 * * *  bash /home/sekt6r/sync_db_to_dedicated.sh >> /home/sekt6r/logs/sync.log 2>&1
# =============================================================================

set -euo pipefail

DEDICATED_USER="RDanton21"
DEDICATED_HOST="116.202.174.56"
DEDICATED_PATH="/D/Crime-Automation/data-backup-from-docker"

VOLUME_NAME="sekt6r-stack_crime_data"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
TMPDIR="$(mktemp -d)"

echo "[$(date -Iseconds)] Sync-Start: Docker -> Dedicated"

# 1. DB aus Volume kopieren (in tmp)
docker run --rm \
    -v "${VOLUME_NAME}:/data:ro" \
    -v "${TMPDIR}:/out" \
    alpine \
    sh -c "cp /data/crime.db /out/crime-${TIMESTAMP}.db"

# 2. Optional: Images (falls du sie mit-syncen willst)
docker run --rm \
    -v "${VOLUME_NAME}:/data:ro" \
    -v "${TMPDIR}:/out" \
    alpine \
    sh -c "if [ -d /data/images ]; then tar czf /out/images-${TIMESTAMP}.tar.gz -C /data images; fi"

echo "Backup lokal: ${TMPDIR}"
ls -lh "${TMPDIR}"

# 3. Auf Dedicated hochladen via scp (SSH-Key nötig)
scp -q "${TMPDIR}"/crime-*.db "${DEDICATED_USER}@${DEDICATED_HOST}:${DEDICATED_PATH}/" || {
    echo "[FEHLER] scp fehlgeschlagen — SSH-Key auf Dedicated eingerichtet?"
    rm -rf "${TMPDIR}"
    exit 1
}
[ -f "${TMPDIR}/images-${TIMESTAMP}.tar.gz" ] && \
    scp -q "${TMPDIR}/images-${TIMESTAMP}.tar.gz" \
        "${DEDICATED_USER}@${DEDICATED_HOST}:${DEDICATED_PATH}/"

# 4. Alte Backups auf Dedicated aufräumen (nur die letzten 14 behalten)
ssh -q "${DEDICATED_USER}@${DEDICATED_HOST}" \
    "cd ${DEDICATED_PATH} && ls -t crime-*.db | tail -n +15 | xargs -r rm --" || \
    echo "[HINWEIS] Aufräumen alter Backups auf Dedicated fehlgeschlagen"

# Cleanup
rm -rf "${TMPDIR}"

echo "[$(date -Iseconds)] Sync-Ende OK"
