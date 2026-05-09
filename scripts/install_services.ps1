# Installiert Backend + Bot als Windows-Dienste via NSSM.
# Voraussetzung: nssm.exe im PATH (https://nssm.cc/download)
# Aufruf als Administrator: powershell -ExecutionPolicy Bypass -File scripts\install_services.ps1

$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..").Path
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "venv Python nicht gefunden - erst scripts\setup.bat ausfuehren."
}
if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    throw "nssm.exe nicht im PATH. Download: https://nssm.cc/download - nssm.exe in C:\Windows\System32 ablegen."
}

New-Item -ItemType Directory -Force -Path (Join-Path $root "logs") | Out-Null

# Backend
nssm install CrimeAutoBackend $venvPython "-m uvicorn backend.main:app --host 127.0.0.1 --port 8000"
nssm set CrimeAutoBackend AppDirectory $root
nssm set CrimeAutoBackend Start SERVICE_AUTO_START
nssm set CrimeAutoBackend AppStdout (Join-Path $root "logs\backend.log")
nssm set CrimeAutoBackend AppStderr (Join-Path $root "logs\backend.err.log")
nssm set CrimeAutoBackend AppRotateFiles 1
nssm set CrimeAutoBackend AppRotateBytes 5242880

# Bot
nssm install CrimeAutoBot $venvPython "-m backend.bot"
nssm set CrimeAutoBot AppDirectory $root
nssm set CrimeAutoBot Start SERVICE_AUTO_START
nssm set CrimeAutoBot AppStdout (Join-Path $root "logs\bot.log")
nssm set CrimeAutoBot AppStderr (Join-Path $root "logs\bot.err.log")
nssm set CrimeAutoBot AppRotateFiles 1
nssm set CrimeAutoBot AppRotateBytes 5242880

Write-Host ""
Write-Host "Services installiert. Starten mit:" -ForegroundColor Green
Write-Host "  nssm start CrimeAutoBot"
Write-Host "  nssm start CrimeAutoBackend"
Write-Host ""
Write-Host "Status pruefen:"
Write-Host "  sc query CrimeAutoBot"
Write-Host "  sc query CrimeAutoBackend"
Write-Host ""
Write-Host "Logs unter $root\logs\"
