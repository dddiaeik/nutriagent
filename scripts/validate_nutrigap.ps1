param(
    [switch]$Live,
    [switch]$RequireSource
)
# NutriGap one-command local verification; no installs or destructive cleanup.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$venvPython = if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
    '.venv/Scripts/python.exe'
} else {
    '.venv/bin/python'
}
$python = Join-Path $root $venvPython
if (!(Test-Path $python)) {
    throw "Missing Python venv: $python. Create it with Python 3.11.9 and install requirements.txt first."
}

Write-Host "[1/4] Python version / dependencies"
& $python --version
if ($LASTEXITCODE -ne 0) { throw "Python failed" }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw "pip check failed" }

Write-Host "[2/4] K-FIND source provenance"
$xlsx = Join-Path $root 'data/raw/음식 DB.xlsx'
if (Test-Path $xlsx) {
    & $python scripts/verify_kfind_source.py $xlsx
    if ($LASTEXITCODE -ne 0) { throw "K-FIND source check failed" }
} elseif ($RequireSource) {
    throw "Required original workbook missing: $xlsx"
} else {
    Write-Host "SKIP: original XLSX absent; curated JSON validation still runs in pytest."
}

Write-Host "[3/4] Python compile and offline pytest"
& $python -m compileall -q app.py agent.py nutrition.py nutrigap.py kfind_catalog.py scripts tests
if ($LASTEXITCODE -ne 0) { throw "Compilation failed" }
$env:NUTRIAGENT_MODE = "MOCK"
$env:NUTRIAGENT_LIVE_OLLAMA = "0"
& $python -m pytest -q -rs
if ($LASTEXITCODE -ne 0) { throw "Offline regression tests failed" }

Write-Host "[4/4] Real Ollama integration"
if ($Live) {
    $env:NUTRIAGENT_MODE = "OLLAMA"
    $env:NUTRIAGENT_LIVE_OLLAMA = "1"
    & $python -m pytest -q -rs -k live_qwen_inference
    if ($LASTEXITCODE -ne 0) { throw "Live Ollama integration failed" }
} else {
    Write-Host "SKIP: live inference not requested. Use -Live on a PC with qwen3:8b installed."
}

Write-Host "Verification finished. See PASS/SKIP results above."
