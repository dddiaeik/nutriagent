param(
    [string[]]$Models = @('qwen3:8b', 'qwen3.5:9b-q4_K_M'),
    [ValidateSet('LEGACY','SPLIT')][string[]]$Architectures = @('LEGACY','SPLIT'),
    [ValidateSet('baseline','robustness')][string[]]$Datasets = @('baseline','robustness'),
    [ValidateRange(1,100)][int]$Repeats = 3,
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venvPython = if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
    '.venv/Scripts/python.exe'
} else {
    '.venv/bin/python'
}
$python = Join-Path $root $venvPython
if (!(Test-Path -LiteralPath $python)) {
    throw "Missing Python virtual environment: $python"
}
if (!$OutputDirectory) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $id = [guid]::NewGuid().ToString().Substring(0, 8)
    $OutputDirectory = Join-Path $root "evaluation-results/tool-architecture-$stamp-$id"
}
$results = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)
$archive = "$results.zip"
if ((Test-Path -LiteralPath $archive) -or (Test-Path -LiteralPath (Join-Path $results 'metadata.json'))) {
    throw "Choose a new output directory. Existing evaluation at $results"
}

Push-Location $root
try {
    $runnerArgs = @('-m','evaluation.run_tool_architecture','--output-dir',$results,'--repeats',"$Repeats",
                    '--models') + $Models + @('--architectures') + $Architectures + @('--datasets') + $Datasets
    & $python @runnerArgs
    $runnerExit = $LASTEXITCODE
    if (!(Test-Path -LiteralPath (Join-Path $results 'metadata.json'))) {
        throw "The runner did not create metadata (exit $runnerExit)."
    }
    & $python -m evaluation.analyze_tool_architecture $results
    $analysisExit = $LASTEXITCODE
    Compress-Archive -Path (Join-Path $results '*') -DestinationPath $archive
    Write-Host "Results: $results"
    Write-Host "ZIP: $archive"
    if ($runnerExit -ne 0 -or $analysisExit -ne 0) {
        Write-Warning "The run contains infrastructure errors or incomplete results."
        exit 2
    }
} finally {
    Pop-Location
}
