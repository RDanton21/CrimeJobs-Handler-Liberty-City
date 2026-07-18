# =============================================================================
# DB-Admin — sqlite-web fuer die Crime-Datenbank (Read-Only)
# =============================================================================
# Web-UI zum Browsen der crime.db: Tabellen, Zeilen, SQL-Abfragen, Export.
# Das SQLite-Gegenstueck zu phpMyAdmin.
#
# Absicherung (mehrschichtig):
#   1. Traefik Basic-Auth vor der Route (db.bots.sektorrp.eu)
#   2. sqlite_web laeuft mit -r / --read-only: kein INSERT/UPDATE/DELETE,
#      keine Schema-Aenderungen ueber das UI
#
# Das Volume wird bewusst schreibbar gemountet: SQLite braucht auch beim
# Lesen Schreibzugriff auf die WAL-/SHM-Dateien im selben Verzeichnis.
# Der Schutz gegen Datenaenderungen kommt aus dem --read-only-Flag.
# =============================================================================
FROM python:3.13-slim

RUN pip install --no-cache-dir sqlite-web==0.6.4

WORKDIR /data

EXPOSE 8080

# -x = kein Browser-Autostart, -r = read-only
CMD ["sqlite_web", "-H", "0.0.0.0", "-p", "8080", "-x", "-r", "/data/crime.db"]
