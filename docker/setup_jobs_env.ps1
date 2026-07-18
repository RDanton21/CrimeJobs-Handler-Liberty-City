# =============================================================================
# Jobs-Dashboard: .env-Werte einrichten (Dedicated + VPS)
# =============================================================================
# Fragt Discord-Client-ID/Secret interaktiv ab, generiert API-Key + Session-
# Secret, traegt alles in die VPS-.env ein und ergaenzt JOBS_API_KEY lokal.
#
# Ausfuehrung (Dedicated, normale PowerShell reicht):
#   powershell -File D:\Crime-Automation\docker\setup_jobs_env.ps1
# =============================================================================

$ErrorActionPreference = "Stop"

$VpsUser = "sekt6r"
$VpsHost = "72.62.63.148"
$RemoteEnv = "/home/$VpsUser/sekt6r-stack/docker/.env"
$LocalEnv = "D:\Crime-Automation\.env"

Write-Host "===== Jobs-Dashboard: Env-Setup =====" -ForegroundColor Cyan
Write-Host ""
Write-Host "Die beiden Discord-Werte findest du unter:" -ForegroundColor Yellow
Write-Host "  https://discord.com/developers/applications -> Il Padrino -> OAuth2"
Write-Host ""

$clientId = Read-Host "Discord CLIENT ID"
if (-not $clientId.Trim()) { Write-Error "Client ID darf nicht leer sein"; exit 1 }

$secureSecret = Read-Host "Discord CLIENT SECRET" -AsSecureString
$bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureSecret)
$clientSecret = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
if (-not $clientSecret.Trim()) { Write-Error "Client Secret darf nicht leer sein"; exit 1 }

# Zufaellige Secrets generieren
function New-Secret {
    param([int]$Bytes = 32)
    $buf = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buf)
    return ([Convert]::ToBase64String($buf) -replace '[+/=]', '').Substring(0, 40)
}

$apiKey = New-Secret
$sessionSecret = New-Secret

Write-Host ""
Write-Host "[1/3] Neue Werte generiert (API-Key + Session-Secret)" -ForegroundColor Yellow

# --- VPS-.env ergaenzen ---
Write-Host "[2/3] VPS-.env ergaenzen..." -ForegroundColor Yellow

$remoteScript = @"
set -e
ENV=$RemoteEnv
cp "`$ENV" "`$ENV.bak.`$(date +%Y%m%d-%H%M%S)"
# Alte Jobs-Zeilen entfernen (idempotent), dann neu anhaengen
grep -v -E '^(JOBS_API_KEY|JOBS_DISCORD_CLIENT_ID|JOBS_DISCORD_CLIENT_SECRET|JOBS_SESSION_SECRET)=' "`$ENV" > "`$ENV.tmp" || true
mv "`$ENV.tmp" "`$ENV"
cat >> "`$ENV" <<'JOBSEOF'

# --- Jobs-Dashboard (Personal-Boerse) ---
JOBS_API_KEY=$apiKey
JOBS_DISCORD_CLIENT_ID=$clientId
JOBS_DISCORD_CLIENT_SECRET=$clientSecret
JOBS_SESSION_SECRET=$sessionSecret
JOBSEOF
echo "  VPS-.env aktualisiert (`$(grep -c . "`$ENV") Zeilen)"
"@

$remoteScript | ssh -o StrictHostKeyChecking=accept-new "${VpsUser}@${VpsHost}" "bash -s"
if ($LASTEXITCODE -ne 0) { Write-Error "VPS-.env-Update fehlgeschlagen"; exit 1 }

# --- Lokale .env (Dedicated) ergaenzen: nur der API-Key ---
Write-Host "[3/3] Lokale .env ergaenzen (JOBS_API_KEY)..." -ForegroundColor Yellow
if (Test-Path $LocalEnv) {
    Copy-Item $LocalEnv "$LocalEnv.bak.$(Get-Date -Format yyyyMMdd-HHmmss)" -Force
    $lines = @(Get-Content $LocalEnv -Encoding UTF8 | Where-Object { $_ -notmatch '^JOBS_API_KEY=' })
    $lines += ""
    $lines += "# Public-API fuer das Jobs-Dashboard"
    $lines += "JOBS_API_KEY=$apiKey"
    [System.IO.File]::WriteAllLines($LocalEnv, $lines, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "  Lokale .env aktualisiert"
} else {
    Write-Warning "  $LocalEnv nicht gefunden - uebersprungen"
}

Write-Host ""
Write-Host "===== FERTIG =====" -ForegroundColor Green
Write-Host ""
Write-Host "Naechste Schritte:"
Write-Host "  1. Cloudflare: CNAME 'jobs.bots' -> bots.sektorrp.eu (Nur DNS)"
Write-Host "  2. Deploy:"
Write-Host "     ssh sekt6r@$VpsHost `"cd sekt6r-stack && git pull && cd docker && docker compose up -d --build jobs-dashboard crime-backend crime-bot`""
Write-Host "  3. Settings-Seite: Announce-Channel 1528109994824957992 eintragen"
Write-Host ""
Write-Host "Die Secrets stehen jetzt in der VPS-.env - nirgends sonst." -ForegroundColor Yellow
