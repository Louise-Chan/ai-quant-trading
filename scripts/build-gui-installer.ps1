# =============================================================================
# build-gui-installer.ps1
#
# Build Electron GUI installer EXE:
#   1) build core NSIS installer (SilentSigma-Setup-*.exe)
#   2) copy core installer to installer_gui/payload/SilentSigma-Core-Setup.exe
#   3) build outer Electron GUI installer (portable single EXE)
#
# Usage:
#   pwsh scripts/build-gui-installer.ps1
#   pwsh scripts/build-gui-installer.ps1 -SkipCore
#   pwsh scripts/build-gui-installer.ps1 -SkipPython
# =============================================================================

param(
    [switch]$SkipCore,
    [switch]$SkipPython,
    [switch]$ForcePython,
    [switch]$UseChinaMirror
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

Write-Host ""
Write-Host "============================================================"
Write-Host "   SilentSigma - Build Electron GUI Installer"
Write-Host "============================================================"
Write-Host ""

if (-not (Test-Path (Join-Path $projectRoot 'node_modules'))) {
    Write-Host "[prep] node_modules not found, running npm install ..."
    npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
}

# Ensure icon files are generated before building GUI installer.
Write-Host "[icon] Generating app icons from SilentSigmaLogo.png ..."
npm run generate:icons
if ($LASTEXITCODE -ne 0) { throw "icon generation failed (npm run generate:icons)" }

if (-not $SkipCore) {
    Write-Host "[1/3] Building core NSIS installer ..."
    $args = @()
    if ($SkipPython) { $args += '-SkipPython' }
    if ($ForcePython) { $args += '-ForcePython' }
    if ($UseChinaMirror) { $args += '-UseChinaMirror' }
    & "$PSScriptRoot\build-installer.ps1" @args
    if ($LASTEXITCODE -ne 0) { throw "build-installer.ps1 failed" }
} else {
    Write-Host "[1/3] Skip core NSIS build (-SkipCore)"
}

$distDir = Join-Path $projectRoot 'dist'
$coreSetup = Get-ChildItem -Path $distDir -Filter 'SilentSigma-Setup-*.exe' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $coreSetup) {
    throw "Core installer not found: dist\\SilentSigma-Setup-*.exe"
}

$payloadDir = Join-Path $projectRoot 'installer_gui\payload'
if (-not (Test-Path $payloadDir)) {
    New-Item -ItemType Directory -Path $payloadDir | Out-Null
}

$payloadExe = Join-Path $payloadDir 'SilentSigma-Core-Setup.exe'
Write-Host "[2/3] Copying core installer to payload ..."
Copy-Item -Path $coreSetup.FullName -Destination $payloadExe -Force

Write-Host "[3/3] Building Electron GUI installer ..."
$env:BUILD_TS = Get-Date -Format "yyyyMMdd-HHmmss"
npx electron-builder --config installer_gui/electron-builder.gui.json --win portable
if ($LASTEXITCODE -ne 0) { throw "GUI installer build failed" }

$guiDist = Join-Path $projectRoot 'dist-installer-gui'
$guiSetup = Get-ChildItem -Path $guiDist -Filter 'SilentSigma-Installer-GUI-*.exe' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

Write-Host ""
Write-Host "============================================================"
if ($guiSetup) {
    $sizeMB = [math]::Round($guiSetup.Length / 1MB, 1)
    Write-Host "   GUI installer ready: $($guiSetup.FullName)"
    Write-Host "   File size: $sizeMB MB"
} else {
    Write-Host "   Build finished. Please check dist-installer-gui/ folder."
}
Write-Host "============================================================"
