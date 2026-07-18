# =============================================================================
# FULL MIGRATION Dedicated -> Docker (VPS) - v3
# =============================================================================
# Migriert komplett:
#   1. Native Liberty-Service stoppen
#   2. Crime-images/, Liberty-JSONs, Countdown-JSONs, Ticket-data+kb packen
#   3. Alle .env-Files (5 Bots) in ein VPS-.env mergen
#   4. Alles per scp zum VPS
#   5. Auf VPS in richtige Docker-Volumes entpacken
#   6. Docker-Compose recreate
#
# Der Cloudflare-Tunnel bleibt vorerst auf Dedicated — separater Schritt.
#
# Ausfuehrung (Admin-PowerShell auf Dedicated):
#   powershell -File D:\Crime-Automation\docker\push_full_migration_to_vps.ps1
# =============================================================================

$ErrorActionPreference = "Stop"

$VpsUser  = "sekt6r"
$VpsHost  = "72.62.63.148"
$RemoteEnv = "/home/$VpsUser/sekt6r-stack/docker/.env"
$RemoteMigrate = "/home/$VpsUser/migration"

$LibertyDir   = "D:\V2026_Kofi_Twitch_Script_sanitized"
$CountdownDir = "D:\Countdown"
$TicketDir    = "D:\Ticket Tool"
$WhitelistEnv = "D:\bot\.env"
$CrimeImages  = "D:\Crime-Automation\data\images"

$TmpDir = New-Item -ItemType Directory -Path "$env:TEMP\full-migrate-$(Get-Date -Format yyyyMMddHHmmss)" -Force

Write-Host "===== FULL MIGRATION: Dedicated -> VPS Docker =====" -ForegroundColor Cyan

# --- 1. Native Liberty-Service stoppen (JSONs koennten sonst waehrend Copy geschrieben werden) ---
Write-Host ""
Write-Host "[1/7] Native LibertyCityRelay stoppen..." -ForegroundColor Yellow
try {
    Stop-Service LibertyCityRelay -ErrorAction Stop
    Write-Host "  Gestoppt."
} catch {
    Write-Warning "  Konnte nicht gestoppt werden: $_"
}

# --- 2. Tar-Archive erstellen ---
Write-Host ""
Write-Host "[2/7] Daten-Archive erstellen..." -ForegroundColor Yellow

# Crime images
if (Test-Path $CrimeImages) {
    & tar.exe -czf "$TmpDir\crime-images.tar.gz" -C "D:\Crime-Automation\data" images
    if ($LASTEXITCODE -eq 0) { Write-Host "  crime-images.tar.gz erstellt" } else { Write-Warning "  crime tar failed" }
}

# Liberty state (nur wichtige JSONs, ohne .bak.)
$libertyKeepFiles = @("stats.json", "stats_backup.json", "dedupe.json", "tebex_seen.json", "user_token.json", "admin_config.json", "goal_message.json", "goal_reached.json", "goal_reached_state.json", "status_message.json", "status_meta.json")
$libStageDir = New-Item -ItemType Directory -Path "$TmpDir\liberty-stage" -Force
foreach ($f in $libertyKeepFiles) {
    $src = Join-Path $LibertyDir $f
    if (Test-Path $src) { Copy-Item $src -Destination $libStageDir }
}
& tar.exe -czf "$TmpDir\liberty-state.tar.gz" -C $libStageDir .
if ($LASTEXITCODE -eq 0) { Write-Host "  liberty-state.tar.gz erstellt ($((Get-ChildItem $libStageDir).Count) Files)" }

# Countdown
$cdStageDir = New-Item -ItemType Directory -Path "$TmpDir\countdown-stage" -Force
foreach ($f in @("countdowns.json", "state.json")) {
    $src = Join-Path $CountdownDir $f
    if (Test-Path $src) { Copy-Item $src -Destination $cdStageDir }
}
& tar.exe -czf "$TmpDir\countdown-state.tar.gz" -C $cdStageDir .
if ($LASTEXITCODE -eq 0) { Write-Host "  countdown-state.tar.gz erstellt" }

# Ticket data (ohne bot.lock / bot.pid — die kommen vom Docker neu)
$tkDataStage = New-Item -ItemType Directory -Path "$TmpDir\ticket-data-stage" -Force
Get-ChildItem "$TicketDir\data" -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -notmatch '^(bot\.lock|bot\.pid)$' } | ForEach-Object {
    Copy-Item $_.FullName -Destination $tkDataStage -Recurse -Force
}
& tar.exe -czf "$TmpDir\ticket-data.tar.gz" -C $tkDataStage .
if ($LASTEXITCODE -eq 0) { Write-Host "  ticket-data.tar.gz erstellt" }

# Ticket kb
if (Test-Path "$TicketDir\kb") {
    & tar.exe -czf "$TmpDir\ticket-kb.tar.gz" -C "$TicketDir\kb" .
    if ($LASTEXITCODE -eq 0) { Write-Host "  ticket-kb.tar.gz erstellt" }
}

# --- 3. .env mergen ---
Write-Host ""
Write-Host "[3/7] .env-Files einlesen und mergen..." -ForegroundColor Yellow

function Read-EnvFile {
    param([string]$Path)
    $result = @{}
    if (-not (Test-Path $Path)) { return $result }
    foreach ($line in Get-Content $Path -Encoding UTF8) {
        if ($line -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$') {
            $key = $matches[1]
            $val = $matches[2].Trim()
            if ($val -match '^"(.*)"$') { $val = $matches[1] }
            elseif ($val -match "^'(.*)'$") { $val = $matches[1] }
            $result[$key] = $val
        }
    }
    return $result
}

$liberty   = Read-EnvFile (Join-Path $LibertyDir ".env")
$countdown = Read-EnvFile (Join-Path $CountdownDir ".env")
$ticket    = Read-EnvFile (Join-Path $TicketDir ".env")
$whitelist = Read-EnvFile $WhitelistEnv

Write-Host "  Liberty:   $($liberty.Count) Keys"
Write-Host "  Countdown: $($countdown.Count) Keys"
Write-Host "  Ticket:    $($ticket.Count) Keys"
Write-Host "  Whitelist: $($whitelist.Count) Keys"

# aktuelle VPS-.env runterladen (fuer CRIME_* + KZ_* zu behalten)
Write-Host "  Aktuelle VPS-.env holen..."
$RemoteEnvTmp = Join-Path $TmpDir "current-vps.env"
scp -o StrictHostKeyChecking=accept-new "${VpsUser}@${VpsHost}:${RemoteEnv}" $RemoteEnvTmp
if ($LASTEXITCODE -ne 0) { Write-Error "Konnte VPS-.env nicht laden"; exit 1 }
$currentVps = Read-EnvFile $RemoteEnvTmp

function Get-OrKeep {
    param($LocalMap, [string]$LocalKey, [string]$TargetKey, $CurrentVps)
    if ($LocalMap.ContainsKey($LocalKey) -and $LocalMap[$LocalKey] -ne "") { return $LocalMap[$LocalKey] }
    if ($CurrentVps.ContainsKey($TargetKey)) { return $CurrentVps[$TargetKey] }
    return ""
}

$lines = @()
$lines += "# Auto-generiert am $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
$lines += "# Merged aus 5 Dedicated-.env-Files"
$lines += ""
$lines += "# Kommandozentrale"
$lines += "KZ_ADMIN_USERNAME=$($currentVps['KZ_ADMIN_USERNAME'])"
$lines += "KZ_ADMIN_PASSWORD=$($currentVps['KZ_ADMIN_PASSWORD'])"
$lines += ""
$lines += "# Crime-Automation"
foreach ($k in @("CRIME_DISCORD_BOT_TOKEN","CRIME_DISCORD_GUILD_ID","CRIME_ANTHROPIC_API_KEY","CRIME_OPENAI_API_KEY","CRIME_DEFAULT_AI_PROVIDER","CRIME_DEFAULT_CLAUDE_MODEL","CRIME_DEFAULT_OPENAI_MODEL","CRIME_ADMIN_USERNAME","CRIME_ADMIN_PASSWORD")) {
    $lines += "$k=$($currentVps[$k])"
}
$lines += ""

$libMap = [ordered]@{
  "DISCORD_WEBHOOK_URL"="LIBERTY_DISCORD_WEBHOOK_URL"; "DISCORD_USERNAME"="LIBERTY_DISCORD_USERNAME"; "DISCORD_AVATAR_URL"="LIBERTY_DISCORD_AVATAR_URL"
  "LIBERTY_EMOJI"="LIBERTY_EMOJI"; "GOAL_NETTO_EUR"="LIBERTY_GOAL_NETTO_EUR"; "PROGRESS_BAR_LENGTH"="LIBERTY_PROGRESS_BAR_LENGTH"
  "TWITCH_CLIENT_ID"="LIBERTY_TWITCH_CLIENT_ID"; "TWITCH_CLIENT_SECRET"="LIBERTY_TWITCH_CLIENT_SECRET"
  "TWITCH_BROADCASTER_LOGIN"="LIBERTY_TWITCH_BROADCASTER_LOGIN"; "TWITCH_BROADCASTER_ID"="LIBERTY_TWITCH_BROADCASTER_ID"
  "TWITCH_EVENTSUB_SECRET"="LIBERTY_TWITCH_EVENTSUB_SECRET"; "KOFI_VERIFICATION_TOKEN"="LIBERTY_KOFI_VERIFICATION_TOKEN"
  "KOFI_FEE_PERCENT"="LIBERTY_KOFI_FEE_PERCENT"; "PAYPAL_FEE_PERCENT"="LIBERTY_PAYPAL_FEE_PERCENT"; "PAYPAL_FEE_FIXED"="LIBERTY_PAYPAL_FEE_FIXED"
  "OBS_OVERLAY_ORIGIN"="LIBERTY_OBS_OVERLAY_ORIGIN"; "ADMIN_USER"="LIBERTY_ADMIN_USER"; "ADMIN_PASS"="LIBERTY_ADMIN_PASS"
  "TEBEX_SECRET_KEY"="LIBERTY_TEBEX_SECRET_KEY"; "LEADERBOARD_CACHE_TTL"="LIBERTY_LEADERBOARD_CACHE_TTL"
  "STATUS_REPOST_TO_BOTTOM"="LIBERTY_STATUS_REPOST_TO_BOTTOM"; "STATUS_REPOST_COOLDOWN_SEC"="LIBERTY_STATUS_REPOST_COOLDOWN_SEC"
  "LOG_MAX_BYTES"="LIBERTY_LOG_MAX_BYTES"; "LOG_BACKUP_COUNT"="LIBERTY_LOG_BACKUP_COUNT"
}
$lines += "# Liberty"
foreach ($p in $libMap.GetEnumerator()) { $lines += "$($p.Value)=$(Get-OrKeep $liberty $p.Key $p.Value $currentVps)" }
$lines += ""

$lines += "# Countdown"
$lines += "COUNTDOWN_DISCORD_TOKEN=$(Get-OrKeep $countdown 'DISCORD_TOKEN' 'COUNTDOWN_DISCORD_TOKEN' $currentVps)"
$lines += ""

$ticketMap = [ordered]@{
  "DISCORD_TOKEN"="TICKET_DISCORD_TOKEN"; "ANTHROPIC_API_KEY"="TICKET_ANTHROPIC_API_KEY"; "DISCORD_GUILD_ID"="TICKET_DISCORD_GUILD_ID"
  "TICKET_CHANNEL_ID"="TICKET_CHANNEL_ID"; "MOD_ROLE_ID"="TICKET_MOD_ROLE_ID"; "TICKET_ACCESS_ROLE_ID"="TICKET_ACCESS_ROLE_ID"
  "TICKET_CATEGORY_ID"="TICKET_CATEGORY_ID"; "TICKET_ARCHIVE_CHANNEL_ID"="TICKET_ARCHIVE_CHANNEL_ID"
  "CLAUDE_MODEL"="TICKET_CLAUDE_MODEL"; "EMBED_MODEL"="TICKET_EMBED_MODEL"; "CONFIDENCE_THRESHOLD"="TICKET_CONFIDENCE_THRESHOLD"
  "MAX_TOKENS"="TICKET_MAX_TOKENS"; "TOP_K"="TICKET_TOP_K"; "SNIPPET_THRESHOLD"="TICKET_SNIPPET_THRESHOLD"
  "SILENT_MENTIONS"="TICKET_SILENT_MENTIONS"; "ADMIN_USER"="TICKET_ADMIN_USER"; "ADMIN_PASSWORD"="TICKET_ADMIN_PASSWORD"
}
$lines += "# Ticket"
foreach ($p in $ticketMap.GetEnumerator()) { $lines += "$($p.Value)=$(Get-OrKeep $ticket $p.Key $p.Value $currentVps)" }
$lines += ""

$whitelistMap = [ordered]@{
  "BOT_TOKEN"="WHITELIST_BOT_TOKEN"; "DB_HOST"="WHITELIST_DB_HOST"; "DB_NAME"="WHITELIST_DB_NAME"
  "DB_USER"="WHITELIST_DB_USER"; "DB_PASS"="WHITELIST_DB_PASS"; "GUILD_ID"="WHITELIST_GUILD_ID"
  "WHITELIST_ROLE_ID"="WHITELIST_ROLE_ID"
}
$lines += "# Whitelist"
foreach ($p in $whitelistMap.GetEnumerator()) { $lines += "$($p.Value)=$(Get-OrKeep $whitelist $p.Key $p.Value $currentVps)" }

$NewEnv = Join-Path $TmpDir "new.env"
[System.IO.File]::WriteAllLines($NewEnv, $lines, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "  Neue .env gebaut ($($lines.Count) Zeilen)"

# --- 4. Upload zum VPS ---
Write-Host ""
Write-Host "[4/7] Upload zum VPS (mehrfach Passwort noetig)..." -ForegroundColor Yellow

# Backup existierende VPS-.env
ssh -o StrictHostKeyChecking=accept-new "${VpsUser}@${VpsHost}" "cp $RemoteEnv $RemoteEnv.bak.`$(date +%Y%m%d-%H%M%S) && mkdir -p $RemoteMigrate"

# .env hoch
scp -o StrictHostKeyChecking=accept-new $NewEnv "${VpsUser}@${VpsHost}:${RemoteEnv}"

# Tar-Files hoch
Get-ChildItem "$TmpDir\*.tar.gz" | ForEach-Object {
    Write-Host "  Uploading $($_.Name)..."
    scp -o StrictHostKeyChecking=accept-new $_.FullName "${VpsUser}@${VpsHost}:${RemoteMigrate}/"
}

# --- 5. Auf VPS in Volumes entpacken ---
Write-Host ""
Write-Host "[5/7] Auf VPS in Docker-Volumes entpacken..." -ForegroundColor Yellow
$RemoteScript = @'
set -e
cd ~/sekt6r-stack/docker

echo "--> Betroffene Container stoppen..."
docker compose stop crime-backend crime-bot liberty-relay countdown-bot ticket-bot whitelist-bot 2>/dev/null || true

echo "--> Crime-Images..."
[ -f ~/migration/crime-images.tar.gz ] && \
  docker run --rm -v docker_crime_data:/data -v ~/migration:/import alpine sh -c "cd /data && tar xzf /import/crime-images.tar.gz" && \
  echo "    entpackt"

echo "--> Liberty state..."
[ -f ~/migration/liberty-state.tar.gz ] && \
  docker run --rm -v docker_liberty_data:/data -v ~/migration:/import alpine sh -c "cd /data && tar xzf /import/liberty-state.tar.gz" && \
  echo "    entpackt"

echo "--> Countdown state..."
[ -f ~/migration/countdown-state.tar.gz ] && \
  docker run --rm -v docker_countdown_data:/data -v ~/migration:/import alpine sh -c "cd /data && tar xzf /import/countdown-state.tar.gz" && \
  echo "    entpackt"

echo "--> Ticket data..."
[ -f ~/migration/ticket-data.tar.gz ] && \
  docker run --rm -v docker_ticket_data:/data -v ~/migration:/import alpine sh -c "cd /data && tar xzf /import/ticket-data.tar.gz" && \
  echo "    entpackt"

echo "--> Ticket kb..."
[ -f ~/migration/ticket-kb.tar.gz ] && \
  docker run --rm -v docker_ticket_kb:/kb -v ~/migration:/import alpine sh -c "cd /kb && tar xzf /import/ticket-kb.tar.gz" && \
  echo "    entpackt"

echo ""
echo "--> Container wieder starten..."
docker compose up -d crime-backend crime-bot liberty-relay countdown-bot ticket-bot whitelist-bot

echo ""
docker compose ps
'@

$RemoteScript | ssh -o StrictHostKeyChecking=accept-new "${VpsUser}@${VpsHost}" "bash -s"

# --- 6. Cleanup lokal ---
Write-Host ""
Write-Host "[6/7] Lokale Temp-Files aufraeumen..." -ForegroundColor Yellow
Remove-Item -Recurse -Force $TmpDir

# --- 7. Fertig ---
Write-Host ""
Write-Host "===== MIGRATION ABGESCHLOSSEN =====" -ForegroundColor Green
Write-Host ""
Write-Host "Naechster Schritt: Container-Status pruefen mit:"
Write-Host "  ssh sekt6r@$VpsHost"
Write-Host "  docker compose -f ~/sekt6r-stack/docker/docker-compose.yml logs --tail=20 liberty-relay"
Write-Host ""
Write-Host "Wenn alles laeuft:"
Write-Host "  Set-Service LibertyCityRelay -StartupType Manual  # bleibt gestoppt"
Write-Host ""
Write-Host "SEPARAT: Cloudflare-Tunnel-Migration (overlay.sektorrp.eu)"
Write-Host "  Wenn kein Stream laeuft, in einem eigenen Schritt behandeln."
