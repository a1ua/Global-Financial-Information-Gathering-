param([ValidateSet('test','demo')][string]$Action = 'test')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$candidates = @()
if ($env:MARKET_INTEL_PYTHON) { $candidates += $env:MARKET_INTEL_PYTHON }
$projectVenvPython = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (Test-Path -LiteralPath $projectVenvPython -PathType Leaf) { $candidates += $projectVenvPython }
$localPythonPath = Join-Path $PSScriptRoot 'python-path.local.txt'
if (Test-Path -LiteralPath $localPythonPath) { $candidates += (Get-Content -LiteralPath $localPythonPath -Raw).Trim() }
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCommand) { $candidates += $pythonCommand.Source }
$runtimeRoot = Join-Path $env:ProgramFiles 'WindowsApps'
$runtimeDirs = Get-ChildItem -LiteralPath $runtimeRoot -Directory -Filter 'OpenAI.CodexPrimaryRuntime*' -ErrorAction SilentlyContinue | Sort-Object Name -Descending
foreach ($runtimeDir in $runtimeDirs) { $candidates += Join-Path $runtimeDir.FullName 'dependencies/python/python.exe' }
$interpreter = $null
foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        & $candidate -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $interpreter = $candidate; break }
    }
}
if (-not $interpreter) { throw 'No Python 3.11+ found. Set MARKET_INTEL_PYTHON to a verified interpreter path.' }
$previousPythonPath = $env:PYTHONPATH
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
Push-Location $projectRoot
try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    if ($Action -eq 'test') {
        $testTemp = Join-Path $projectRoot 'out/test-temp'
        $null = New-Item -ItemType Directory -Path $testTemp -Force
        $env:TEMP = $testTemp
        $env:TMP = $testTemp
    }
    if ($Action -eq 'test') { & $interpreter -X utf8 -m unittest discover -s tests -v }
    else { & $interpreter -X utf8 -m market_intel demo --workspace out/demo }
    if ($LASTEXITCODE -ne 0) { throw "Python command failed with exit code $LASTEXITCODE" }
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
    Pop-Location
}
