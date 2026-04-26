# =============================================================================
# build-installer.ps1
#
# Build NSIS installer to dist\SilentSigma-Setup-<version>.exe
#   1) prepare python_runtime (portable Python + deps)
#   2) install npm deps if missing
#   3) run electron-builder
#
# Usage:
#   pwsh scripts/build-installer.ps1
#   pwsh scripts/build-installer.ps1 -SkipPython
#   pwsh scripts/build-installer.ps1 -ForcePython
# =============================================================================

param(
    [switch]$SkipPython,
    [switch]$ForcePython,
    [switch]$UseChinaMirror
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

Write-Host ""
Write-Host "============================================================"
Write-Host "   SilentSigma - Build NSIS Installer"
Write-Host "   Project root: $projectRoot"
Write-Host "============================================================"
Write-Host ""

# ---- 0. tool checks ----
foreach ($cmd in @('node', 'npm', 'npx')) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "Missing command: $cmd. Please install Node.js 18+ from https://nodejs.org/"
    }
}

# ---- 1. python_runtime ----
$runtimeDir = Join-Path $projectRoot 'python_runtime'
$marker = Join-Path $runtimeDir '.silentsigma_ready'

if ($SkipPython) {
    Write-Host "[1/3] Skip python_runtime preparation (-SkipPython)"
    if (-not (Test-Path $marker)) {
        Write-Warning "python_runtime is not ready. Installer may not run backend correctly."
    }
} else {
    Write-Host "[1/3] Preparing python_runtime ..."
    $args = @()
    if ($ForcePython) { $args += '-Force' }
    $global:LASTEXITCODE = 0
    & "$PSScriptRoot\prepare-python-bundle.ps1" @args
    if (($null -ne $LASTEXITCODE) -and ($LASTEXITCODE -ne 0)) {
        throw "prepare-python-bundle.ps1 failed (exit=$LASTEXITCODE)"
    }
}

# ---- 2. npm dependencies ----
Write-Host ""
Write-Host "[2/3] Checking npm dependencies ..."
if (-not (Test-Path (Join-Path $projectRoot 'node_modules'))) {
    Write-Host "       node_modules not found, running npm install ..."
    npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
} else {
    Write-Host "       node_modules found, skip npm install"
}

# ---- 2.5 generate icons from SilentSigmaLogo.png ----
Write-Host ""
Write-Host "[icon] Generating app icons from SilentSigmaLogo.png ..."
npm run generate:icons
if ($LASTEXITCODE -ne 0) { throw "icon generation failed (npm run generate:icons)" }

# ---- 3. electron-builder ----
Write-Host ""
Write-Host "[3/3] Running electron-builder ..."

# Cache/mirror settings for unstable GitHub DNS in some networks.
$env:ELECTRON_CACHE = Join-Path $projectRoot ".cache\electron"
$env:ELECTRON_BUILDER_CACHE = Join-Path $projectRoot ".cache\electron-builder"
New-Item -ItemType Directory -Force -Path $env:ELECTRON_CACHE | Out-Null
New-Item -ItemType Directory -Force -Path $env:ELECTRON_BUILDER_CACHE | Out-Null

if ($UseChinaMirror) {
    Write-Host "       Using China mirror for electron downloads ..."
    $env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
    $env:ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"
}

# Unique build stamp to avoid file-lock on existing installer EXE.
$env:BUILD_TS = Get-Date -Format "yyyyMMdd-HHmmss"

npx electron-builder --win
if ($LASTEXITCODE -ne 0) {
    # Auto retry with mirror when first attempt fails (common when github.com DNS fails).
    Write-Warning "electron-builder failed on first attempt (exit=$LASTEXITCODE)."
    Write-Host "       Retrying with China mirror ..."
    $env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
    $env:ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"
    npx electron-builder --win
}
if ($LASTEXITCODE -ne 0) {
    throw "electron-builder failed (exit=$LASTEXITCODE). Check DNS/proxy/firewall."
}

# ---- done ----
$dist = Join-Path $projectRoot 'dist'
$installer = Get-ChildItem -Path $dist -Filter 'SilentSigma-Setup-*.exe' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

Write-Host ""
Write-Host "============================================================"
if ($installer) {
    $sizeMB = [math]::Round($installer.Length / 1MB, 1)
    Write-Host "   Build complete: $($installer.FullName)"
    Write-Host "   Installer size: $sizeMB MB"
} else {
    Write-Host "   Build finished. Please check dist/ folder."
}
Write-Host "============================================================"
