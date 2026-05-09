# Crime Automation Patch
# - ⊘ -> ❌ (Discord akzeptiert ⊘ nicht)
# - app.js: Auto-Refresh Polling alle 5 Sek
# - Labels: "angenommen" -> "Erledigt", "abgelehnt" -> "Fehlgeschlagen"
#
# Aufruf direkt von Dev-PC via RDP-tsclient auf Dedicated:
#   powershell -ExecutionPolicy Bypass -File "\\tsclient\J\MSC5Projects\Crime-Automation\Crime-Automation-fix-emoji.ps1"
# Standard-Ziel: D:\Crime-Automation. Anderer Pfad mit -ProjectRoot:
#   powershell -ExecutionPolicy Bypass -File "..." -ProjectRoot "C:\Apps\Crime-Automation"

param(
    [string]$ProjectRoot = "D:\Crime-Automation"
)

$ErrorActionPreference = "Stop"
$root = $ProjectRoot
if (-not (Test-Path (Join-Path $root "backend"))) {
    Write-Host "FEHLER: Projekt-Root '$root' enthaelt kein backend\ Verzeichnis." -ForegroundColor Red
    Write-Host "Mit -ProjectRoot anderen Pfad angeben." -ForegroundColor Red
    exit 1
}
Write-Host "[fix] Ziel-Root: $root"

$cancelOld = [char]0x2298   # ⊘
$cancelNew = [char]0x274C   # ❌

function Patch-File($rel, [scriptblock]$transform) {
    $full = Join-Path $root $rel
    if (-not (Test-Path $full)) { throw "fehlt: $full" }
    $text = [System.IO.File]::ReadAllText($full, [System.Text.Encoding]::UTF8)
    $new = & $transform $text
    if ($new -ne $text) {
        [System.IO.File]::WriteAllText($full, $new, [System.Text.UTF8Encoding]::new($false))
        Write-Host "  patched: $rel"
    } else {
        Write-Host "  unchanged: $rel"
    }
}

Write-Host "[fix] Stoppe Services..."
Stop-Service CrimeAutoBot -ErrorAction SilentlyContinue
Stop-Service CrimeAutoBackend -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Write-Host "[fix] Patche Files..."

# bot.py — emoji
Patch-File "backend\bot.py" {
    param($t)
    $t -replace [regex]::Escape($cancelOld), $cancelNew
}

# crew.html — emoji
Patch-File "frontend\crew.html" {
    param($t)
    $t -replace [regex]::Escape($cancelOld), $cancelNew
}

# prompts.py — emoji + labels
Patch-File "backend\prompts.py" {
    param($t)
    $t = $t -replace [regex]::Escape($cancelOld), $cancelNew
    $t = $t -replace ([regex]::Escape("👍 angenommen")), "👍 Erledigt"
    $t = $t -replace ([regex]::Escape("👎 abgelehnt")), "👎 Fehlgeschlagen"
    $t
}

# app.js — emoji + labels + polling
Patch-File "frontend\app.js" {
    param($t)
    $t = $t -replace [regex]::Escape($cancelOld), $cancelNew
    $t = $t -replace ([regex]::Escape("👍 angenommen")), "👍 Erledigt"
    $t = $t -replace ([regex]::Escape("👎 abgelehnt")), "👎 Fehlgeschlagen"

    # Auto-Refresh hinzufuegen wenn noch nicht drin
    if ($t -notmatch 'setInterval\(.*loadMissions') {
        $literalOld = 'await Promise.all([this.loadCrew(), this.loadAllCrews(), this.loadRelations(), this.loadMissions()]);'
        $oldInit = [regex]::Escape($literalOld)
        $newInit = "await Promise.all([this.loadCrew(), this.loadAllCrews(), this.loadRelations(), this.loadMissions()]);`n      // Auto-Refresh Missionen alle 5 Sek (fuer Discord-Reaktions-Updates)`n      setInterval(() => { this.loadMissions().catch(() => {}); }, 5000);"
        $t = $t -replace $oldInit, $newInit
    }
    $t
}

Write-Host "[fix] Starte Services neu..."
Start-Service CrimeAutoBot
Start-Service CrimeAutoBackend
Start-Sleep -Seconds 3

Get-Service CrimeAutoBot, CrimeAutoBackend | Format-Table Name, Status

Write-Host ""
Write-Host "[fix] FERTIG." -ForegroundColor Green
Write-Host "Browser F5 -> Crew-Seite refresht jetzt automatisch alle 5 Sek."
Write-Host "Reaktions-Test: in Discord 👍/👎/❌ klicken -> Status erscheint nach max 5 Sek im UI."
