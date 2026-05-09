# Crime Automation — Desktop-Icon Installer
# Erstellt: il_padrino.ico im Projekt + Desktop-Shortcut "Crime Automation"
#
# Aufruf auf Dedicated:
#   cd D:\Crime-Automation
#   powershell -ExecutionPolicy Bypass -File scripts\install_desktop.ps1

$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..").Path
$iconPng = Join-Path $root "frontend\il_padrino.png"
$iconIco = Join-Path $root "frontend\il_padrino.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$publicDesktop = [Environment]::GetFolderPath("CommonDesktopDirectory")

Write-Host "[desktop] Crime Automation Installer"

# --- 1. Avatar herunterladen (falls noch nicht da) ---
$avatarUrl = "https://d8j0ntlcm91z4.cloudfront.net/user_31gZYbm98wO1gSRAXPz2ZY0iWI0/hf_20260509_075740_6bb9706b-e5b2-4c32-9167-bb3a16f6eea8.png"

if (-not (Test-Path $iconPng)) {
    Write-Host "  Avatar herunterladen..."
    try {
        Invoke-WebRequest -Uri $avatarUrl -OutFile $iconPng -UseBasicParsing
        Write-Host "    OK: $iconPng"
    } catch {
        Write-Host "    FEHLER beim Download: $_" -ForegroundColor Red
        Write-Host "    Bitte avatar manuell als $iconPng ablegen und Skript erneut starten."
        exit 1
    }
} else {
    Write-Host "  Avatar bereits vorhanden: $iconPng"
}

# --- 2. PNG -> ICO konvertieren ---
Write-Host "  PNG -> ICO konvertieren..."
Add-Type -AssemblyName System.Drawing

$bmpSrc = [System.Drawing.Bitmap]::FromFile($iconPng)
$bmpResized = New-Object System.Drawing.Bitmap 256, 256
$g = [System.Drawing.Graphics]::FromImage($bmpResized)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
$g.DrawImage($bmpSrc, 0, 0, 256, 256)
$g.Dispose()
$bmpSrc.Dispose()

# Multi-size ICO bauen
$sizes = @(16, 32, 48, 64, 128, 256)
$iconStreams = @()
$pngBytes = @()

foreach ($size in $sizes) {
    $resized = New-Object System.Drawing.Bitmap $size, $size
    $g2 = [System.Drawing.Graphics]::FromImage($resized)
    $g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g2.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $g2.DrawImage($bmpResized, 0, 0, $size, $size)
    $g2.Dispose()

    $ms = New-Object System.IO.MemoryStream
    $resized.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    $pngBytes += ,$ms.ToArray()
    $resized.Dispose()
    $ms.Dispose()
}
$bmpResized.Dispose()

# ICO Header + Directory + PNG-Daten schreiben
$fs = [System.IO.File]::Create($iconIco)
$bw = New-Object System.IO.BinaryWriter($fs)

# ICONDIR
$bw.Write([UInt16]0)              # Reserved
$bw.Write([UInt16]1)              # Type: 1=icon
$bw.Write([UInt16]$sizes.Count)   # Count

$offset = 6 + (16 * $sizes.Count)
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $size = $sizes[$i]
    $bytes = $pngBytes[$i]
    $w = if ($size -eq 256) { [byte]0 } else { [byte]$size }
    $h = $w
    $bw.Write([byte]$w)            # Width
    $bw.Write([byte]$h)            # Height
    $bw.Write([byte]0)             # ColorCount
    $bw.Write([byte]0)             # Reserved
    $bw.Write([UInt16]1)           # Planes
    $bw.Write([UInt16]32)          # BitCount
    $bw.Write([UInt32]$bytes.Length) # BytesInRes
    $bw.Write([UInt32]$offset)     # ImageOffset
    $offset += $bytes.Length
}
foreach ($bytes in $pngBytes) {
    $bw.Write($bytes)
}
$bw.Close()
$fs.Close()
Write-Host "    OK: $iconIco"

# --- 3. Desktop-Shortcut erstellen ---
Write-Host "  Desktop-Shortcut erstellen..."

# Alte Verknuepfungen entfernen falls vorhanden
foreach ($old in @("Crime Automation.url", "Crime Automation starten.lnk")) {
    $p = Join-Path $desktop $old
    if (Test-Path $p) { Remove-Item $p -Force }
}

# Smart-Launcher: startet Services (falls down) + oeffnet Browser
$launcher = Join-Path $root "scripts\launcher.bat"
$shortcut = Join-Path $desktop "Crime Automation.lnk"
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($shortcut)
$lnk.TargetPath = $launcher
$lnk.WorkingDirectory = $root
$lnk.IconLocation = "$iconIco,0"
$lnk.Description = "Crime Automation: Services starten + Dashboard oeffnen"
$lnk.WindowStyle = 7  # minimiert (kein cmd-Fenster blockiert)
$lnk.Save()
Write-Host "    OK: $shortcut"

# --- 4. Hinweis Auto-Start ---
Write-Host ""
Write-Host "[desktop] FERTIG." -ForegroundColor Green
Write-Host ""
Write-Host "Desktop-Icon: 'Crime Automation' (Il-Padrino-Avatar)"
Write-Host "  -> startet Services falls down + oeffnet Browser"
Write-Host ""
Write-Host "Fuer Auto-Start mit Windows-Boot (empfohlen, kein Login noetig):" -ForegroundColor Cyan
Write-Host "  1. NSSM herunterladen: https://nssm.cc/download (nssm.exe in C:\Windows\System32 ablegen)"
Write-Host "  2. Als Administrator:"
Write-Host "       powershell -ExecutionPolicy Bypass -File scripts\install_services.ps1"
Write-Host "       nssm start CrimeAutoBot"
Write-Host "       nssm start CrimeAutoBackend"
Write-Host ""
Write-Host "Danach: Desktop-Icon doppelklicken -> Browser geht direkt auf laufendes System."
