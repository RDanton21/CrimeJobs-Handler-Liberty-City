# =============================================================================
# Migrate ALL Bot-.envs vom Dedicated zum VPS (v2)
# =============================================================================
# Merged:
#   - Liberty (D:\V2026_Kofi_Twitch_Script_sanitized\.env)  -> LIBERTY_*
#   - Countdown (D:\Countdown\.env)                          -> COUNTDOWN_*
#   - Ticket   (D:\Ticket Tool\.env)                         -> TICKET_*
#   - Whitelist (D:\bot\.env)                                -> WHITELIST_*
# Behaelt existierende CRIME_* und KZ_* aus aktueller VPS-.env.
#
# Ausfuehrung:
#   powershell -File D:\Crime-Automation\docker\push_bots_to_vps.ps1
# =============================================================================

$ErrorActionPreference = "Stop"

$VpsUser  = "sekt6r"
$VpsHost  = "72.62.63.148"
$RemoteEnv = "/home/$VpsUser/sekt6r-stack/docker/.env"

$LibertyEnv   = "D:\V2026_Kofi_Twitch_Script_sanitized\.env"
$CountdownEnv = "D:\Countdown\.env"
$TicketEnv    = "D:\Ticket Tool\.env"
$WhitelistEnv = "D:\bot\.env"

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

Write-Host "===== Bot-Envs Migration (Dedicated -> VPS) =====" -ForegroundColor Cyan

# 1. Lokale Envs einlesen
Write-Host ""
Write-Host "[1/5] Lokale .env-Dateien einlesen..." -ForegroundColor Yellow
$liberty   = Read-EnvFile $LibertyEnv
$countdown = Read-EnvFile $CountdownEnv
$ticket    = Read-EnvFile $TicketEnv
$whitelist = Read-EnvFile $WhitelistEnv
Write-Host "  Liberty:   $($liberty.Count) Keys"
Write-Host "  Countdown: $($countdown.Count) Keys"
Write-Host "  Ticket:    $($ticket.Count) Keys"
Write-Host "  Whitelist: $($whitelist.Count) Keys"

# 2. Aktuelle VPS-.env runterladen (fuer CRIME_* + KZ_* zu behalten)
Write-Host ""
Write-Host "[2/5] Aktuelle VPS-.env runterladen (fuer Backup + CRIME/KZ)..." -ForegroundColor Yellow
$TmpDir = New-Item -ItemType Directory -Path "$env:TEMP\bots-migrate-$(Get-Date -Format yyyyMMddHHmmss)" -Force
$RemoteEnvTmp = Join-Path $TmpDir "current-vps.env"
scp -o StrictHostKeyChecking=accept-new "${VpsUser}@${VpsHost}:${RemoteEnv}" $RemoteEnvTmp
if ($LASTEXITCODE -ne 0) { Write-Error "Konnte aktuelle VPS-.env nicht laden"; exit 1 }
$currentVps = Read-EnvFile $RemoteEnvTmp
Write-Host "  VPS-.env aktuell: $($currentVps.Count) Keys"

# 3. Neues .env zusammenbauen
Write-Host ""
Write-Host "[3/5] Neues .env mergen..." -ForegroundColor Yellow

function Get-OrKeep {
    param($LocalMap, [string]$LocalKey, [string]$TargetKey, $CurrentVps)
    if ($LocalMap.ContainsKey($LocalKey) -and $LocalMap[$LocalKey] -ne "") {
        return $LocalMap[$LocalKey]
    } elseif ($CurrentVps.ContainsKey($TargetKey)) {
        return $CurrentVps[$TargetKey]
    }
    return ""
}

$lines = @()
$lines += "# Auto-generiert am $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
$lines += "# Merged aus 5 Dedicated-.env-Files (Crime, Liberty, Countdown, Ticket, Whitelist)"
$lines += ""

# --- Kommandozentrale (behalten) ---
$lines += "# Kommandozentrale"
$lines += "KZ_ADMIN_USERNAME=$($currentVps['KZ_ADMIN_USERNAME'])"
$lines += "KZ_ADMIN_PASSWORD=$($currentVps['KZ_ADMIN_PASSWORD'])"
$lines += ""

# --- Crime (behalten) ---
$lines += "# Crime-Automation (Il Padrino)"
$crimeKeys = @("CRIME_DISCORD_BOT_TOKEN","CRIME_DISCORD_GUILD_ID","CRIME_ANTHROPIC_API_KEY","CRIME_OPENAI_API_KEY","CRIME_DEFAULT_AI_PROVIDER","CRIME_DEFAULT_CLAUDE_MODEL","CRIME_DEFAULT_OPENAI_MODEL","CRIME_ADMIN_USERNAME","CRIME_ADMIN_PASSWORD")
foreach ($k in $crimeKeys) { $lines += "$k=$($currentVps[$k])" }
$lines += ""

# --- Liberty (aus V2026_Kofi_Twitch_Script_sanitized) ---
$lines += "# Liberty (Ko-Fi + Twitch + Discord)"
$libMap = @{
  "DISCORD_WEBHOOK_URL"        = "LIBERTY_DISCORD_WEBHOOK_URL"
  "DISCORD_USERNAME"           = "LIBERTY_DISCORD_USERNAME"
  "DISCORD_AVATAR_URL"         = "LIBERTY_DISCORD_AVATAR_URL"
  "LIBERTY_EMOJI"              = "LIBERTY_EMOJI"
  "GOAL_NETTO_EUR"             = "LIBERTY_GOAL_NETTO_EUR"
  "PROGRESS_BAR_LENGTH"        = "LIBERTY_PROGRESS_BAR_LENGTH"
  "TWITCH_CLIENT_ID"           = "LIBERTY_TWITCH_CLIENT_ID"
  "TWITCH_CLIENT_SECRET"       = "LIBERTY_TWITCH_CLIENT_SECRET"
  "TWITCH_BROADCASTER_LOGIN"   = "LIBERTY_TWITCH_BROADCASTER_LOGIN"
  "TWITCH_BROADCASTER_ID"      = "LIBERTY_TWITCH_BROADCASTER_ID"
  "TWITCH_EVENTSUB_SECRET"     = "LIBERTY_TWITCH_EVENTSUB_SECRET"
  "KOFI_VERIFICATION_TOKEN"    = "LIBERTY_KOFI_VERIFICATION_TOKEN"
  "KOFI_FEE_PERCENT"           = "LIBERTY_KOFI_FEE_PERCENT"
  "PAYPAL_FEE_PERCENT"         = "LIBERTY_PAYPAL_FEE_PERCENT"
  "PAYPAL_FEE_FIXED"           = "LIBERTY_PAYPAL_FEE_FIXED"
  "OBS_OVERLAY_ORIGIN"         = "LIBERTY_OBS_OVERLAY_ORIGIN"
  "ADMIN_USER"                 = "LIBERTY_ADMIN_USER"
  "ADMIN_PASS"                 = "LIBERTY_ADMIN_PASS"
  "TEBEX_SECRET_KEY"           = "LIBERTY_TEBEX_SECRET_KEY"
  "LEADERBOARD_CACHE_TTL"      = "LIBERTY_LEADERBOARD_CACHE_TTL"
  "STATUS_REPOST_TO_BOTTOM"    = "LIBERTY_STATUS_REPOST_TO_BOTTOM"
  "STATUS_REPOST_COOLDOWN_SEC" = "LIBERTY_STATUS_REPOST_COOLDOWN_SEC"
  "LOG_MAX_BYTES"              = "LIBERTY_LOG_MAX_BYTES"
  "LOG_BACKUP_COUNT"           = "LIBERTY_LOG_BACKUP_COUNT"
}
foreach ($pair in $libMap.GetEnumerator()) {
  $lines += "$($pair.Value)=$(Get-OrKeep $liberty $pair.Key $pair.Value $currentVps)"
}
$lines += ""

# --- Countdown ---
$lines += "# Countdown-Bot"
$lines += "COUNTDOWN_DISCORD_TOKEN=$(Get-OrKeep $countdown 'DISCORD_TOKEN' 'COUNTDOWN_DISCORD_TOKEN' $currentVps)"
$lines += ""

# --- Ticket (aus Ticket Tool) ---
$lines += "# Ticket-Bot"
$ticketMap = @{
  "DISCORD_TOKEN"           = "TICKET_DISCORD_TOKEN"
  "ANTHROPIC_API_KEY"       = "TICKET_ANTHROPIC_API_KEY"
  "DISCORD_GUILD_ID"        = "TICKET_DISCORD_GUILD_ID"
  "TICKET_CHANNEL_ID"       = "TICKET_CHANNEL_ID"
  "MOD_ROLE_ID"             = "TICKET_MOD_ROLE_ID"
  "TICKET_ACCESS_ROLE_ID"   = "TICKET_ACCESS_ROLE_ID"
  "TICKET_CATEGORY_ID"      = "TICKET_CATEGORY_ID"
  "TICKET_ARCHIVE_CHANNEL_ID" = "TICKET_ARCHIVE_CHANNEL_ID"
  "CLAUDE_MODEL"            = "TICKET_CLAUDE_MODEL"
  "EMBED_MODEL"             = "TICKET_EMBED_MODEL"
  "CONFIDENCE_THRESHOLD"    = "TICKET_CONFIDENCE_THRESHOLD"
  "MAX_TOKENS"              = "TICKET_MAX_TOKENS"
  "TOP_K"                   = "TICKET_TOP_K"
  "SNIPPET_THRESHOLD"       = "TICKET_SNIPPET_THRESHOLD"
  "SILENT_MENTIONS"         = "TICKET_SILENT_MENTIONS"
  "ADMIN_USER"              = "TICKET_ADMIN_USER"
  "ADMIN_PASSWORD"          = "TICKET_ADMIN_PASSWORD"
}
foreach ($pair in $ticketMap.GetEnumerator()) {
  $lines += "$($pair.Value)=$(Get-OrKeep $ticket $pair.Key $pair.Value $currentVps)"
}
$lines += ""

# --- Whitelist (aus D:\bot) ---
$lines += "# Whitelist-Bot"
$whitelistMap = @{
  "BOT_TOKEN"        = "WHITELIST_BOT_TOKEN"
  "DB_HOST"          = "WHITELIST_DB_HOST"
  "DB_NAME"          = "WHITELIST_DB_NAME"
  "DB_USER"          = "WHITELIST_DB_USER"
  "DB_PASS"          = "WHITELIST_DB_PASS"
  "GUILD_ID"         = "WHITELIST_GUILD_ID"
  "WHITELIST_ROLE_ID" = "WHITELIST_ROLE_ID"
}
foreach ($pair in $whitelistMap.GetEnumerator()) {
  $lines += "$($pair.Value)=$(Get-OrKeep $whitelist $pair.Key $pair.Value $currentVps)"
}

# 4. Neue .env schreiben und pushen
Write-Host "[4/5] Neue .env hochladen..." -ForegroundColor Yellow
$NewEnv = Join-Path $TmpDir "new.env"
[System.IO.File]::WriteAllLines($NewEnv, $lines, (New-Object System.Text.UTF8Encoding($false)))

# Backup der alten .env auf VPS
$BackupCmd = "cp $RemoteEnv $RemoteEnv.bak.`$(date +%Y%m%d-%H%M%S)"
ssh -o StrictHostKeyChecking=accept-new "${VpsUser}@${VpsHost}" $BackupCmd
if ($LASTEXITCODE -ne 0) { Write-Error "Backup fehlgeschlagen"; exit 1 }

scp -o StrictHostKeyChecking=accept-new $NewEnv "${VpsUser}@${VpsHost}:${RemoteEnv}"
if ($LASTEXITCODE -ne 0) { Write-Error "Upload fehlgeschlagen"; exit 1 }

Remove-Item -Recurse -Force $TmpDir

# 5. Docker Compose recreate fuer die 4 Bots
Write-Host ""
Write-Host "[5/5] Docker-Compose Restart auf VPS (Liberty/Countdown/Ticket/Whitelist)..." -ForegroundColor Yellow
$ComposeCmd = "cd ~/sekt6r-stack/docker && docker compose up -d liberty-relay countdown-bot ticket-bot whitelist-bot"
ssh -o StrictHostKeyChecking=accept-new "${VpsUser}@${VpsHost}" $ComposeCmd
if ($LASTEXITCODE -ne 0) { Write-Warning "Compose-Restart hatte einen Fehler"; }

Write-Host ""
Write-Host "===== FERTIG =====" -ForegroundColor Green
Write-Host "Naechster Schritt auf VPS:"
Write-Host "  docker compose ps"
Write-Host "  docker compose logs --tail=20 liberty-relay"
Write-Host ""
Write-Host "Wenn alle 4 als 'Up' laufen: native LibertyCityRelay auf Dedicated stoppen mit:"
Write-Host "  Stop-Service LibertyCityRelay"
Write-Host "  Set-Service LibertyCityRelay -StartupType Manual"
