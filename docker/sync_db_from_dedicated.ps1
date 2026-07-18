# =============================================================================
# Sync Crime-Automation DB: Dedicated -> Docker (Hostinger)
# =============================================================================
# Ausführung: auf dem Dedicated als geplanter Task (oder manuell)
# Kopiert die aktuelle SQLite-DB vom Dedicated zum Hostinger-VPS.
#
# Voraussetzungen:
# - OpenSSH-Client auf Windows (bei Win10/11 vorinstalliert)
# - SSH-Key: C:\Users\RDanton\.ssh\id_ed25519 (Public auf VPS in ~/.ssh/authorized_keys)
#
# Windows-Taskplaner Beispiel (täglich 03:00):
#   Aktion: PowerShell.exe -File D:\Crime-Automation\docker\sync_db_from_dedicated.ps1
# =============================================================================

$ErrorActionPreference = "Stop"

$VpsUser = "sekt6r"
$VpsHost = "72.62.63.148"
$LocalDb = "D:\Crime-Automation\data\crime.db"
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$RemoteTmp = "/tmp/crime-from-dedicated-$Timestamp.db"

Write-Host "[$(Get-Date -Format o)] Sync-Start: Dedicated -> Docker"

# 1. DB auf VPS hochladen (in /tmp)
scp -q $LocalDb "${VpsUser}@${VpsHost}:${RemoteTmp}"
if ($LASTEXITCODE -ne 0) {
    Write-Error "scp fehlgeschlagen"
    exit 1
}

# 2. Docker-Container stoppen, DB reinkopieren, Container starten
$Cmds = @"
cd ~/sekt6r-stack/docker
docker compose stop crime-backend crime-bot
docker run --rm \
    -v sekt6r-stack_crime_data:/data \
    -v /tmp:/import \
    alpine \
    cp /import/crime-from-dedicated-$Timestamp.db /data/crime.db
docker compose start crime-backend crime-bot
rm -f $RemoteTmp
"@

ssh -q "${VpsUser}@${VpsHost}" $Cmds
if ($LASTEXITCODE -ne 0) {
    Write-Error "Remote-Restore fehlgeschlagen"
    exit 1
}

Write-Host "[$(Get-Date -Format o)] Sync-Ende OK"
