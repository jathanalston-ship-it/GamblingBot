#Requires -Version 5.1
<#
.SYNOPSIS
    Build the Momentum Lab Windows installer end to end.

.DESCRIPTION
    Produces two artifacts under desktop\release\:
      * MomentumLab-Setup-<version>.exe - a double-click installer.
      * MomentumLab-Portable.zip         - a no-install portable build: extract
        and run "Momentum Lab.exe" (no registry, no installer, no uninstall;
        startup logs are written beside the executable). Identical binaries to the
        installer - only the writable data location differs. For testing release
        candidates fast.

    Both bundle the Electron UI and a frozen FastAPI backend, so the end user needs
    neither Python nor Node.

    Run this on a Windows 11 machine (or Windows CI). It:
      1. Freezes the backend to a standalone .exe (PyInstaller).
      2. Builds the renderer + Electron main.
      3. Packages the NSIS installer (electron-builder).
      4. Zips the unpacked app into the portable build.

.PREREQUISITES
    - Python 3.12+         (https://www.python.org/downloads/)
    - Node.js 18+ and npm  (https://nodejs.org/)
    Both must be on PATH.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
#>

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "== Momentum Lab - Windows installer build ==" -ForegroundColor Cyan
Write-Host "repo: $RepoRoot"

# --------------------------------------------------------------------------- #
# 1. Freeze the FastAPI backend into a standalone binary.
# --------------------------------------------------------------------------- #
Write-Host "`n[1/3] Freezing backend (PyInstaller)..." -ForegroundColor Cyan
python -m venv .venv-build
& .\.venv-build\Scripts\Activate.ps1
python -m pip install --upgrade pip | Out-Null
pip install -r requirements.txt
pip install -e .
pip install pyinstaller pillow

# (Re)generate the app icon from source (committed icon.ico is the fallback).
python desktop\build\make_icon.py

# Clean prior output, then freeze.
if (Test-Path desktop\build\backend) { Remove-Item -Recurse -Force desktop\build\backend }
pyinstaller --noconfirm `
    --distpath desktop\build\backend `
    --workpath desktop\build\.pyiwork `
    desktop\build\backend.spec

# Onedir bundle: the launcher lives inside the mrp-backend\ directory.
if (-not (Test-Path desktop\build\backend\mrp-backend\mrp-backend.exe)) {
    throw "backend freeze failed: desktop\build\backend\mrp-backend\mrp-backend.exe not found"
}
deactivate

# --------------------------------------------------------------------------- #
# 2. Build the desktop app (renderer + Electron main).
# --------------------------------------------------------------------------- #
Write-Host "`n[2/3] Building desktop app..." -ForegroundColor Cyan
Set-Location desktop
npm ci
npm run build

# --------------------------------------------------------------------------- #
# 3. Package the NSIS installer.
# --------------------------------------------------------------------------- #
Write-Host "`n[3/4] Packaging Windows installer..." -ForegroundColor Cyan
# `--publish never`: only BUILD the artifacts (installer + latest.yml + blockmap
# for auto-update). Publishing to the GitHub Release is handled by the release
# workflow (.github/workflows/release.yml), not by this build script.
npx electron-builder --win --publish never
Set-Location $RepoRoot

# --------------------------------------------------------------------------- #
# 4. Build the PORTABLE zip from the unpacked app.
#
# electron-builder leaves the fully unpacked app in desktop\release\win-unpacked
# (the exact files the installer would lay down). We copy it, drop a marker file
# beside the executable so the app runs in PORTABLE mode (writes its DB/logs/
# settings beside the exe instead of %APPDATA%), and zip it. No second
# electron-builder target is needed - the binaries are byte-identical to the
# installer's, so the portable build behaves identically.
# --------------------------------------------------------------------------- #
Write-Host "`n[4/4] Building portable zip..." -ForegroundColor Cyan
$Unpacked = "desktop\release\win-unpacked"
$Exe = Join-Path $Unpacked "Momentum Lab.exe"
if (-not (Test-Path $Exe)) {
    throw "portable build failed: $Exe not found (did electron-builder produce win-unpacked?)"
}

$Stage = "desktop\release\MomentumLab-Portable"
$Zip = "desktop\release\MomentumLab-Portable.zip"
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
if (Test-Path $Zip) { Remove-Item -Force $Zip }

Copy-Item -Recurse -Force $Unpacked $Stage
# The marker (only ever present in the zip, never in the installer) switches the
# app to portable mode. See desktop/electron/paths.ts (PORTABLE_MARKER).
@"
Momentum Lab - portable build.
This file marks the app as PORTABLE: it writes its database, logs and settings to
the MomentumLab-Data folder beside this executable (no registry, no installer).
Delete MomentumLab-Data to reset. To "uninstall", just delete this folder.
"@ | Set-Content -Encoding ASCII (Join-Path $Stage "MomentumLab.portable")

Compress-Archive -Path $Stage -DestinationPath $Zip -Force
Remove-Item -Recurse -Force $Stage

Write-Host "`nDone. Artifacts:" -ForegroundColor Green
Get-ChildItem desktop\release\MomentumLab-Setup-*.exe, $Zip |
    Select-Object Name, @{N = "MB"; E = { [math]::Round($_.Length / 1MB, 1) } }
