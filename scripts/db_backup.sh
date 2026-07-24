#!/bin/bash
# =============================================================================
# Taegliches DB-Backup fuer den sekt6r-stack (crime.db + jobs.db).
#
# Konsistent auch bei laufenden Schreibzugriffen: nutzt die Online-Backup-API
# des Python-sqlite3-Moduls im Container (ein blosses `docker cp` der Datei
# koennte einen halb geschriebenen WAL-Stand erwischen). sqlite3-CLI ist in
# den Images nicht vorhanden, python ist es.
#
# Backups liegen ausserhalb des Repos unter $BACKUP_DIR, gzip-komprimiert,
# mit Rotation ($KEEP_DAYS Tage). Einrichtung als root-crontab:
#   0 4 * * * /home/sekt6r/sekt6r-stack/scripts/db_backup.sh >> /home/sekt6r/db-backups/backup.log 2>&1
# =============================================================================
set -euo pipefail

BACKUP_DIR=/home/sekt6r/db-backups
KEEP_DAYS=14
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$BACKUP_DIR"

backup_db() {
  local container=$1 dbpath=$2 name=$3
  if ! docker ps --format '{{.Names}}' | grep -qx "$container"; then
    echo "$(date '+%F %T')  WARN: $container laeuft nicht — $name uebersprungen"
    return 0
  fi
  # Online-Backup in eine Temp-Datei im Container, dann rauskopieren.
  docker exec "$container" python -c "import sqlite3,sys
src=sqlite3.connect('$dbpath'); dst=sqlite3.connect('/tmp/_bk.db')
src.backup(dst); dst.close(); src.close()"
  docker cp "$container:/tmp/_bk.db" "$BACKUP_DIR/${name}-${STAMP}.db"
  docker exec "$container" rm -f /tmp/_bk.db
  gzip -f "$BACKUP_DIR/${name}-${STAMP}.db"
  echo "$(date '+%F %T')  OK: ${name}-${STAMP}.db.gz ($(du -h "$BACKUP_DIR/${name}-${STAMP}.db.gz" | cut -f1))"
}

backup_db sekt6r-crime-backend /app/data/crime.db crime
backup_db sekt6r-jobs          /app/data/jobs.db  jobs

# Rotation: Backups aelter als KEEP_DAYS Tage entfernen
find "$BACKUP_DIR" -name "*.db.gz" -mtime +"$KEEP_DAYS" -delete
echo "$(date '+%F %T')  Rotation: aelter als ${KEEP_DAYS} Tage entfernt"
