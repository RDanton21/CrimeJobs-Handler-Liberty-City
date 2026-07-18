# =============================================================================
# DB-Admin (sqlite-web) einrichten: Passwort erzeugen + in VPS-.env eintragen
# =============================================================================
# Legt DBADMIN_AUTH (Basic-Auth-Hash fuer Traefik) in der VPS-.env an.
# Der Hash wird auf dem VPS per htpasswd erzeugt - das Klartext-Passwort
# verlaesst dieses Fenster nicht.
#
# Ausfuehrung (Dedicated):
#   powershell -File D:\Crime-Automation\docker\setup_dbadmin.ps1
# =============================================================================

$ErrorActionPreference = "Stop"

$VpsUser = "sekt6r"
$VpsHost = "72.62.63.148"
$RemoteEnv = "/home/$VpsUser/sekt6r-stack/docker/.env"
$DbUser = "admin"

Write-Host "===== DB-Admin Setup (db.bots.sektorrp.eu) =====" -ForegroundColor Cyan
Write-Host ""

# Passwort erzeugen (alphanumerisch, damit es sich sauber tippen laesst)
$chars = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789".ToCharArray()
$buf = New-Object byte[] 20
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buf)
$password = -join ($buf | ForEach-Object { $chars[$_ % $chars.Length] })

Write-Host "[1/2] Hash auf dem VPS erzeugen und in .env eintragen..." -ForegroundColor Yellow

# htpasswd via Docker (httpd:alpine), $ fuer docker-compose verdoppeln
$remoteScript = @"
set -e
ENV=$RemoteEnv
HASH=`$(docker run --rm httpd:2.4-alpine htpasswd -nbB '$DbUser' '$password' | tr -d '\r\n')
ESCAPED=`$(printf '%s' "`$HASH" | sed 's/\`$/\`$\`$/g')
cp "`$ENV" "`$ENV.bak.`$(date +%Y%m%d-%H%M%S)"
grep -v '^DBADMIN_AUTH=' "`$ENV" > "`$ENV.tmp" || true
mv "`$ENV.tmp" "`$ENV"
printf '\n# DB-Admin (sqlite-web) - Basic-Auth-Hash fuer Traefik\nDBADMIN_AUTH=%s\n' "`$ESCAPED" >> "`$ENV"
echo "  DBADMIN_AUTH gesetzt."
"@

$remoteScript | ssh -o StrictHostKeyChecking=accept-new "${VpsUser}@${VpsHost}" "bash -s"
if ($LASTEXITCODE -ne 0) { Write-Error "Eintragen fehlgeschlagen"; exit 1 }

Write-Host "[2/2] Fertig." -ForegroundColor Yellow
Write-Host ""
Write-Host "===== ZUGANGSDATEN (bitte notieren!) =====" -ForegroundColor Cyan
Write-Host "  URL:      https://db.bots.sektorrp.eu"
Write-Host "  Benutzer: $DbUser"
Write-Host "  Passwort: $password" -ForegroundColor Yellow
Write-Host ""
Write-Host "Naechste Schritte:" -ForegroundColor Green
Write-Host "  1. Cloudflare: CNAME 'db.bots' -> bots.sektorrp.eu (Nur DNS)"
Write-Host "  2. ssh sekt6r@$VpsHost `"cd sekt6r-stack && git pull && cd docker && docker compose up -d --build dbadmin kommandozentrale`""
