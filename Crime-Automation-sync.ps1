# Crime Automation Sync — kopiert Code-Updates von Dev-PC auf Dedicated.
#
# Aufruf direkt von Dev-PC via RDP-tsclient (idempotent, beliebig oft):
#   powershell -ExecutionPolicy Bypass -File "\\tsclient\J\MSC5Projects\Crime-Automation\Crime-Automation-sync.ps1"
#
# Quelle: \\tsclient\J\MSC5Projects\Crime-Automation
# Ziel:   D:\Crime-Automation
# Behaelt: .env, data\*, .venv, logs\*  (werden NIE ueberschrieben)

param(
    [string]$Source = "\\tsclient\J\MSC5Projects\Crime-Automation",
    [string]$Dest = "D:\Crime-Automation",
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Source)) {
    Write-Host "FEHLER: Quelle '$Source' nicht erreichbar. RDP-Drive verbunden?" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $Dest)) {
    Write-Host "FEHLER: Ziel '$Dest' existiert nicht." -ForegroundColor Red
    exit 1
}

Write-Host "[sync] $Source -> $Dest"

# Services stoppen
$svcs = @("CrimeAutoBot", "CrimeAutoBackend")
$running = @()
foreach ($s in $svcs) {
    $svc = Get-Service $s -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq "Running") {
        Write-Host "  stoppe $s..."
        Stop-Service $s
        $running += $s
    }
}
Start-Sleep 2

# Robocopy code only (excludes data, .venv, logs, .env, .db files)
$rcArgs = @(
    "$Source",
    "$Dest",
    "/E",                     # subdirs incl empty
    "/XD", ".venv", "data", "logs", "__pycache__", ".git",
    "/XF", ".env", "*.db", "*.db-shm", "*.db-wal",
    "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS"
)
& robocopy @rcArgs | Out-Null
$rcExit = $LASTEXITCODE
# Robocopy: 0=nothing, 1=copied, 2=extra, 3=both. >=8 fail
if ($rcExit -ge 8) {
    Write-Host "FEHLER: robocopy exit $rcExit" -ForegroundColor Red
    exit 1
}
if ($rcExit -eq 0) {
    Write-Host "  keine Aenderungen erkannt"
} else {
    Write-Host "  Files synchronisiert (robocopy=$rcExit)" -ForegroundColor Green
}

# Services neu starten
if (-not $NoRestart) {
    foreach ($s in $running) {
        Write-Host "  starte $s..."
        Start-Service $s
    }
    Start-Sleep 3
    Get-Service $svcs -ErrorAction SilentlyContinue | Format-Table Name, Status
}

Write-Host "[sync] FERTIG." -ForegroundColor Green
