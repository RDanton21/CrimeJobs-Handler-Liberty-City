# =============================================================================
# Migrate to Hostinger VPS - Windows Skript (ASCII-only, PowerShell 5.1 kompatibel)
# =============================================================================
# Ausfuehrung auf dem Dedicated:
#   powershell -File D:\Crime-Automation\docker\push_to_vps.ps1
#
# Voraussetzungen:
# - OpenSSH-Client (Windows 10/11 vorinstalliert)
# - sekt6r-User auf VPS existiert
# =============================================================================

$ErrorActionPreference = "Stop"

$VpsUser = "sekt6r"
$VpsHost = "72.62.63.148"
$SourceEnv = "D:\Crime-Automation\.env"
$SourceDb  = "D:\Crime-Automation\data\crime.db"

Write-Host "===== Docker-Migration Dedicated -> Hostinger VPS =====" -ForegroundColor Cyan

if (-not (Test-Path $SourceEnv)) { Write-Error "Nicht gefunden: $SourceEnv"; exit 1 }
if (-not (Test-Path $SourceDb))  { Write-Error "Nicht gefunden: $SourceDb"; exit 1 }

# 1. .env auslesen und Werte extrahieren
Write-Host ""
Write-Host "[1/5] .env vom Dedicated lesen..." -ForegroundColor Yellow
$rawEnv = Get-Content $SourceEnv -Encoding UTF8
$vals = @{}
foreach ($line in $rawEnv) {
    if ($line -match "^([A-Z_]+)=(.*)$") {
        $vals[$matches[1]] = $matches[2].Trim('"')
    }
}

# 2. Docker-.env erzeugen
Write-Host "[2/5] Docker-.env erzeugen..." -ForegroundColor Yellow
$KzPassword = "Crime$(Get-Random -Minimum 100000 -Maximum 999999)$(Get-Random -Minimum 100 -Maximum 999)!"

$dockerEnvLines = @()
$dockerEnvLines += "# Auto-generiert am $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
$dockerEnvLines += ""
$dockerEnvLines += "# Kommandozentrale (Login fuer bots.sektorrp.eu)"
$dockerEnvLines += "KZ_ADMIN_USERNAME=admin"
$dockerEnvLines += "KZ_ADMIN_PASSWORD=$KzPassword"
$dockerEnvLines += ""
$dockerEnvLines += "# Crime-Automation (Il Padrino)"
$dockerEnvLines += "CRIME_DISCORD_BOT_TOKEN=$($vals.DISCORD_BOT_TOKEN)"
$dockerEnvLines += "CRIME_DISCORD_GUILD_ID=$($vals.DISCORD_GUILD_ID)"
$dockerEnvLines += "CRIME_ANTHROPIC_API_KEY=$($vals.ANTHROPIC_API_KEY)"
$dockerEnvLines += "CRIME_OPENAI_API_KEY=$($vals.OPENAI_API_KEY)"
$dockerEnvLines += "CRIME_DEFAULT_AI_PROVIDER=anthropic"
$dockerEnvLines += "CRIME_DEFAULT_CLAUDE_MODEL=claude-sonnet-4-5-20250929"
$dockerEnvLines += "CRIME_DEFAULT_OPENAI_MODEL=gpt-4o"
$dockerEnvLines += "CRIME_ADMIN_USERNAME=$($vals.ADMIN_USERNAME)"
$dockerEnvLines += "CRIME_ADMIN_PASSWORD=$($vals.ADMIN_PASSWORD)"
$dockerEnvLines += ""
$dockerEnvLines += "# Andere Bots (leer, wenn nicht mitmigriert)"
$dockerEnvLines += "LIBERTY_DISCORD_WEBHOOK_URL="
$dockerEnvLines += "LIBERTY_TWITCH_CLIENT_ID="
$dockerEnvLines += "LIBERTY_TWITCH_CLIENT_SECRET="
$dockerEnvLines += "LIBERTY_TWITCH_BROADCASTER_LOGIN="
$dockerEnvLines += "LIBERTY_TWITCH_BROADCASTER_ID="
$dockerEnvLines += "LIBERTY_TWITCH_EVENTSUB_SECRET="
$dockerEnvLines += "LIBERTY_KOFI_VERIFICATION_TOKEN="
$dockerEnvLines += "LIBERTY_ADMIN_USER=admin"
$dockerEnvLines += "LIBERTY_ADMIN_PASS=CHANGE_ME"
$dockerEnvLines += "TICKET_DISCORD_TOKEN="
$dockerEnvLines += "TICKET_ANTHROPIC_API_KEY=$($vals.ANTHROPIC_API_KEY)"
$dockerEnvLines += "TICKET_DISCORD_GUILD_ID=$($vals.DISCORD_GUILD_ID)"
$dockerEnvLines += "TICKET_CHANNEL_ID="
$dockerEnvLines += "TICKET_MOD_ROLE_ID="
$dockerEnvLines += "TICKET_ACCESS_ROLE_ID="
$dockerEnvLines += "TICKET_CATEGORY_ID="
$dockerEnvLines += "TICKET_ADMIN_USER=admin"
$dockerEnvLines += "TICKET_ADMIN_PASSWORD=CHANGE_ME"
$dockerEnvLines += "COUNTDOWN_DISCORD_TOKEN="
$dockerEnvLines += "WHITELIST_BOT_TOKEN="
$dockerEnvLines += "WHITELIST_DB_HOST="
$dockerEnvLines += "WHITELIST_DB_NAME="
$dockerEnvLines += "WHITELIST_DB_USER="
$dockerEnvLines += "WHITELIST_DB_PASS="
$dockerEnvLines += "WHITELIST_GUILD_ID=$($vals.DISCORD_GUILD_ID)"
$dockerEnvLines += "WHITELIST_ROLE_ID="

$TmpDir = New-Item -ItemType Directory -Path "$env:TEMP\crime-migrate-$(Get-Date -Format yyyyMMddHHmmss)" -Force
$TmpEnv = Join-Path $TmpDir ".env"
[System.IO.File]::WriteAllLines($TmpEnv, $dockerEnvLines, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "  Kommandozentrale-Passwort generiert: $KzPassword" -ForegroundColor Green

# 3. crime.db kopieren
Write-Host ""
Write-Host "[3/5] crime.db kopieren (Snapshot)..." -ForegroundColor Yellow
$TmpDb = Join-Path $TmpDir "crime.db"
Copy-Item $SourceDb $TmpDb -Force
$dbSizeKB = [math]::Round((Get-Item $TmpDb).Length / 1024, 0)
Write-Host "  Snapshot: $dbSizeKB KB"

# 4. Upload via scp
Write-Host ""
Write-Host "[4/5] Upload zum VPS (2x sekt6r-Passwort eingeben)..." -ForegroundColor Yellow

Write-Host "  -> .env hoch..."
scp -o StrictHostKeyChecking=accept-new $TmpEnv "${VpsUser}@${VpsHost}:/home/${VpsUser}/sekt6r-stack/docker/.env"
if ($LASTEXITCODE -ne 0) { Write-Error ".env-Upload fehlgeschlagen"; exit 1 }

Write-Host "  -> crime.db hoch..."
ssh -q "${VpsUser}@${VpsHost}" "mkdir -p /home/${VpsUser}/migration"
scp -o StrictHostKeyChecking=accept-new $TmpDb "${VpsUser}@${VpsHost}:/home/${VpsUser}/migration/crime.db"
if ($LASTEXITCODE -ne 0) { Write-Error "crime.db-Upload fehlgeschlagen"; exit 1 }

Remove-Item -Recurse -Force $TmpDir

# 5. Fertig
Write-Host ""
Write-Host "[5/5] FERTIG! Auf dem VPS jetzt ausfuehren:" -ForegroundColor Green
Write-Host ""
Write-Host "  cd ~/sekt6r-stack/docker"
Write-Host "  docker compose up -d --build"
Write-Host ""
Write-Host "  # 5-15 Min warten. Dann DB reinkopieren:"
Write-Host "  docker compose stop crime-backend crime-bot"
Write-Host "  docker run --rm -v sekt6r-stack_crime_data:/data -v ~/migration:/import alpine cp /import/crime.db /data/crime.db"
Write-Host "  docker compose start crime-backend crime-bot"
Write-Host "  docker compose ps"
Write-Host ""
Write-Host "===== KOMMANDOZENTRALE-PASSWORT =====" -ForegroundColor Cyan
Write-Host "  Login unter: https://bots.sektorrp.eu"
Write-Host "  Username: admin"
Write-Host "  Password: $KzPassword" -ForegroundColor Yellow
Write-Host "  (bitte notieren!)"
