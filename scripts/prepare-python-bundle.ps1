# =============================================================================
# prepare-python-bundle.ps1
#
# Prepare portable Python runtime in python_runtime/:
#   1) download Python embeddable package (Windows x64)
#   2) enable site-packages via python*._pth
#   3) bootstrap pip with get-pip.py
#   4) install backend/requirements.txt dependencies
#
# Usage:
#   pwsh scripts/prepare-python-bundle.ps1
#   pwsh scripts/prepare-python-bundle.ps1 -Force
# =============================================================================

param(
    [switch]$Force,
    [string]$PythonVersion = '3.11.9'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir  = Join-Path $projectRoot 'python_runtime'
$reqFile     = Join-Path $projectRoot 'backend\requirements.txt'

$embedZipName = "python-$PythonVersion-embed-amd64.zip"
$embedUrl     = "https://www.python.org/ftp/python/$PythonVersion/$embedZipName"
$getPipUrl    = 'https://bootstrap.pypa.io/get-pip.py'

Write-Host ""
Write-Host "==========================================================="
Write-Host "  SilentSigma - Prepare portable Python runtime"
Write-Host "  Python version : $PythonVersion (embeddable, x64)"
Write-Host "  Runtime dir    : $runtimeDir"
Write-Host "  Requirements   : $reqFile"
Write-Host "==========================================================="
Write-Host ""

if (-not (Test-Path $reqFile)) {
    throw "requirements.txt not found: $reqFile"
}

if (Test-Path $runtimeDir) {
    if ($Force) {
        Write-Host "[clean] remove old python_runtime ..."
        Remove-Item -Recurse -Force $runtimeDir
    } else {
        $marker = Join-Path $runtimeDir '.silentsigma_ready'
        if (Test-Path $marker) {
            Write-Host "[skip] python_runtime already ready. Use -Force to rebuild."
            return
        }
        Write-Host "[clean] python_runtime exists but not ready. Rebuild ..."
        Remove-Item -Recurse -Force $runtimeDir
    }
}

New-Item -ItemType Directory -Path $runtimeDir | Out-Null

# ---- 1. download and extract embeddable ----
$tempZip = Join-Path $env:TEMP $embedZipName
Write-Host "[1/4] downloading $embedUrl ..."
Invoke-WebRequest -Uri $embedUrl -OutFile $tempZip -UseBasicParsing

Write-Host "[1/4] extracting to $runtimeDir ..."
Expand-Archive -Path $tempZip -DestinationPath $runtimeDir -Force
Remove-Item $tempZip -Force

# ---- 2. enable site-packages ----
$pthFile = Get-ChildItem -Path $runtimeDir -Filter 'python*._pth' | Select-Object -First 1
if (-not $pthFile) {
    throw "python*._pth not found in embeddable package"
}
Write-Host "[2/4] patching $($pthFile.Name) to enable site-packages ..."
$pthLines = Get-Content $pthFile.FullName
$pthLines = $pthLines | ForEach-Object {
    if ($_ -match '^\s*#\s*import\s+site\s*$') { 'import site' } else { $_ }
}
$siteRel = 'Lib\site-packages'
if (-not ($pthLines -contains $siteRel)) {
    $pthLines += $siteRel
}
Set-Content -Path $pthFile.FullName -Value $pthLines -Encoding ASCII

# ---- 3. bootstrap pip ----
$pythonExe = Join-Path $runtimeDir 'python.exe'
if (-not (Test-Path $pythonExe)) {
    throw "python.exe not found after extraction: $pythonExe"
}

$getPipPath = Join-Path $runtimeDir 'get-pip.py'
Write-Host "[3/4] downloading get-pip.py ..."
Invoke-WebRequest -Uri $getPipUrl -OutFile $getPipPath -UseBasicParsing

Write-Host "[3/4] bootstrapping pip ..."
& $pythonExe $getPipPath --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "pip bootstrap failed (exit=$LASTEXITCODE)" }
Remove-Item $getPipPath -Force

# ---- 4. install dependencies ----
Write-Host "[4/4] installing backend requirements (this may take a while) ..."
& $pythonExe -m pip install --upgrade pip setuptools wheel --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "pip/setuptools/wheel upgrade failed" }

& $pythonExe -m pip install --no-warn-script-location -r $reqFile
if ($LASTEXITCODE -ne 0) { throw "requirements install failed (exit=$LASTEXITCODE)" }

# ---- 5. smoke test and marker ----
Write-Host ""
Write-Host "[verify] checking critical imports ..."
& $pythonExe -c "import fastapi, uvicorn, sqlalchemy, numpy, pandas, sklearn, scipy; print('OK', fastapi.__version__, numpy.__version__, pandas.__version__)"
if ($LASTEXITCODE -ne 0) { throw "import smoke test failed" }

Write-Host "[verify] cleaning __pycache__ / tests ..."
Get-ChildItem -Path $runtimeDir -Recurse -Directory -Force |
    Where-Object { $_.Name -in @('__pycache__','tests','test') } |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName -ErrorAction SilentlyContinue }

$markerPath = Join-Path $runtimeDir '.silentsigma_ready'
Set-Content -Path $markerPath -Value (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') -Encoding ASCII

$totalSize = (Get-ChildItem -Path $runtimeDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
$totalMB = [math]::Round($totalSize / 1MB, 1)

Write-Host ""
Write-Host "==========================================================="
Write-Host "  Done. python_runtime size: $totalMB MB"
Write-Host "  python.exe: $pythonExe"
Write-Host "==========================================================="
