#Requires -Version 5.1
<#
.SYNOPSIS
    Build the Momentum Lab Windows installer end to end.

.DESCRIPTION
    Produces desktop\release\MomentumLab-Setup-<version>.exe — a double-click
    installer that bundles the Electron UI and a frozen FastAPI backend, so the
    end user needs neither Python nor Node.

    Run this on a Windows 11 machine (or Windows CI). It:
      1. Freezes the backend to a standalone .exe (PyInstaller).
      2. Builds the renderer + Electron main.
      3. Packages the NSIS installer (electron-builder).

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

Write-Host "== Momentum Lab — Windows installer build ==" -ForegroundColor Cyan
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

if (-not (Test-Path desktop\build\backend\mrp-backend.exe)) {
    throw "backend freeze failed: desktop\build\backend\mrp-backend.exe not found"
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
Write-Host "`n[3/3] Packaging Windows installer..." -ForegroundColor Cyan
npx electron-builder --win
Set-Location $RepoRoot

Write-Host "`nDone. Installer:" -ForegroundColor Green
Get-ChildItem desktop\release\*.exe | Select-Object Name, @{N = "MB"; E = { [math]::Round($_.Length / 1MB, 1) } }
