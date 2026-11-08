param()
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$projectRoot = Split-Path $PSScriptRoot -Parent
$venvRoot = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvRoot 'Scripts/python.exe'
$externalTempRoot = [IO.Path]::GetTempPath()
$localPath = Join-Path $PSScriptRoot 'python-path.local.txt'
if (-not (Test-Path -LiteralPath $localPath -PathType Leaf)) {
    throw 'Missing scripts/python-path.local.txt. Record a verified Python 3.11+ path first.'
}
$basePython = (Get-Content -LiteralPath $localPath -Raw).Trim()
if (-not (Test-Path -LiteralPath $basePython -PathType Leaf)) {
    throw 'The recorded Python interpreter no longer exists. Refresh python-path.local.txt.'
}

$script:setupLog = $null
function Write-SetupLog([string]$Message) {
    Write-Host $Message
    if ($script:setupLog) { Add-Content -LiteralPath $script:setupLog -Value $Message -Encoding utf8 }
}
function Invoke-Checked([string]$File, [string[]]$ArgumentList) {
    if ($File -eq $basePython -or $File -eq $venvPython) { $ArgumentList = @('-X','utf8') + $ArgumentList }
    Write-SetupLog ('> ' + $File + ' ' + (ConvertTo-Json -InputObject $ArgumentList -Compress))
    $nativeOutput = & $File @ArgumentList 2>&1
    $nativeExitCode = $LASTEXITCODE
    foreach ($line in $nativeOutput) { Write-SetupLog ([string]$line) }
    Write-SetupLog "exit_code=$nativeExitCode"
    if ($nativeExitCode -ne 0) { throw "Setup command failed with exit code $nativeExitCode ($File)." }
}

# Do not use inherited source paths or write Python caches into the checkout.
$environmentNames = @('PYTHONPATH','PYTHONHOME','PYTHONDONTWRITEBYTECODE','PYTHONUTF8','PYTHONIOENCODING','TEMP','TMP')
$savedEnvironment = @{}
foreach ($name in $environmentNames) { $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
Push-Location $projectRoot
try {
    [Environment]::SetEnvironmentVariable('PYTHONPATH', $null, 'Process')
    [Environment]::SetEnvironmentVariable('PYTHONHOME', $null, 'Process')
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    Invoke-Checked $basePython @('-I','-B','-c','import sys; print(sys.executable); print(sys.version); sys.exit(0 if sys.version_info >= (3, 11) else 1)')
    $createEnvironment = -not (Test-Path -LiteralPath $venvPython -PathType Leaf)
    if ($createEnvironment -and (Test-Path -LiteralPath $venvRoot)) { throw 'Incomplete .venv exists. Inspect it before choosing a new environment; setup never deletes it.' }
    $runId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
    $runRoot = Join-Path $venvRoot "setup-runs/$runId"
    $null = New-Item -ItemType Directory -Path (Join-Path $runRoot 'tmp') -Force
    $script:setupLog = Join-Path $runRoot 'setup.log'
    $env:TEMP = Join-Path $runRoot 'tmp'
    $env:TMP = $env:TEMP
    Write-SetupLog "setup_run=$runId (local time); project=$projectRoot"
    if ($createEnvironment) { Invoke-Checked $basePython @('-I','-B','-m','venv',$venvRoot) }
    $checkEnvironment = @'
import json, pathlib, sqlite3, sys
expected = pathlib.Path(sys.argv[1]).resolve()
if sys.version_info < (3, 11) or sys.prefix == sys.base_prefix or pathlib.Path(sys.prefix).resolve() != expected:
    raise SystemExit('Expected isolated project .venv with Python >=3.11')
print(json.dumps({'python': sys.executable, 'version': sys.version, 'prefix': sys.prefix, 'base_prefix': sys.base_prefix, 'sqlite': sqlite3.sqlite_version}, ensure_ascii=False))
'@
    Invoke-Checked $venvPython @('-I','-B','-c',$checkEnvironment,$venvRoot)
    Invoke-Checked $venvPython @('-I','-B','-m','pip','--version')

    # Reuse only the configured runtime's installed setuptools and IANA data.
    # Rebuild a local wheel with new RECORD hashes; never enable system-site-packages.
    $bootstrapWheel = @'
import base64, csv, hashlib, importlib.metadata as metadata, io, pathlib, sys, zipfile
package = sys.argv[2]
dist = metadata.distribution(package)
version = dist.version
if package == 'setuptools' and int(version.split('.')[0]) < 68:
    raise SystemExit('Configured runtime setuptools does not meet pyproject setuptools>=68')
wheel_metadata = dist.read_text('WHEEL') or ''
if 'Root-Is-Purelib: true' not in wheel_metadata or 'Tag: py3-none-any' not in wheel_metadata:
    raise SystemExit('Bootstrap accepts only installed pure-Python distributions')
wheelhouse = pathlib.Path(sys.argv[1])
wheelhouse.mkdir(parents=True, exist_ok=True)
target = wheelhouse / f'{package}-{version}-py3-none-any.whl'
records = []
with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as wheel:
    for item in sorted(dist.files or [], key=str):
        name = item.as_posix()
        path = pathlib.PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts:
            raise SystemExit(f'Unsafe installed distribution path: {name}')
        if '__pycache__' in path.parts or path.suffix == '.pyc' or path.name in {'RECORD', 'INSTALLER', 'REQUESTED', 'direct_url.json'}:
            continue
        data = pathlib.Path(dist.locate_file(item)).read_bytes()
        wheel.writestr(name, data)
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode('ascii')
        records.append((name, f'sha256={digest}', str(len(data))))
    record_path = f'{package}-{version}.dist-info/RECORD'
    records.append((record_path, '', ''))
    record = io.StringIO(newline='')
    csv.writer(record, lineterminator='\n').writerows(records)
    wheel.writestr(record_path, record.getvalue())
print(f'Bootstrap source: {dist.locate_file("")}; {package}={version}; local wheel={target}')
'@
    $wheelhouse = Join-Path $venvRoot 'wheelhouse'
    foreach ($package in @('setuptools','tzdata')) {
        Invoke-Checked $basePython @('-I','-B','-c',$bootstrapWheel,$wheelhouse,$package)
    }
    Invoke-Checked $venvPython @('-I','-B','-m','pip','--isolated','install','--no-cache-dir','--no-index','--no-compile','--find-links',$wheelhouse,'setuptools==84.2.1')

    # Build from an exact source snapshot under .venv, so setuptools never creates
    # build/ or src/*.egg-info in the shared checkout. This is a normal installation.
    $stageSource = @'
import hashlib, json, pathlib, shutil, sys
project, destination = map(pathlib.Path, sys.argv[1:])
destination.mkdir(parents=True)
shutil.copy2(project / 'pyproject.toml', destination / 'pyproject.toml')
shutil.copytree(project / 'src', destination / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.egg-info'))
manifest = {str(path.relative_to(destination)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(destination.rglob('*')) if path.is_file()}
(destination.parent / 'source-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Staged {len(manifest)} source files at {destination}; source-manifest.json records exact bytes')
'@
    $stageRoot = Join-Path $runRoot 'package-source'
    Invoke-Checked $venvPython @('-I','-B','-c',$stageSource,$projectRoot,$stageRoot)
    Invoke-Checked $venvPython @('-I','-B','-m','pip','--isolated','install','--no-cache-dir','--no-index','--no-build-isolation','--no-compile','--find-links',$wheelhouse,'--force-reinstall',$stageRoot)
    Invoke-Checked $venvPython @('-I','-B','-m','pip','--isolated','check')
    $checkInstalled = @'
import importlib.metadata as metadata, json, pathlib, sys
from importlib.resources import files
from zoneinfo import ZoneInfo
import market_intel
location = pathlib.Path(market_intel.__file__).resolve()
expected = (pathlib.Path(sys.prefix) / 'Lib' / 'site-packages').resolve()
if not location.is_relative_to(expected):
    raise SystemExit(f'Package was not imported from isolated site-packages: {location}')
if not files('market_intel.transport').joinpath('fetch.mjs').is_file():
    raise SystemExit('Packaged optional Node transport worker is missing')
print(json.dumps({'installed_version': metadata.version('market-intel-agent'), 'module_file': str(location), 'setuptools': metadata.version('setuptools'), 'tzdata': metadata.version('tzdata'), 'iana_zones': [str(ZoneInfo('Asia/Shanghai')), str(ZoneInfo('America/New_York'))]}, ensure_ascii=False))
'@
    Invoke-Checked $venvPython @('-I','-B','-c',$checkInstalled)
    $console = Join-Path $venvRoot 'Scripts/market-intel.exe'
    if (-not (Test-Path -LiteralPath $console -PathType Leaf)) { throw 'Installed market-intel console entry point is missing.' }
    # Verify the installed console command from an empty directory outside the
    # checkout. All outputs and test temp files still target the project .venv.
    $externalCwd = Join-Path $externalTempRoot ('market-intel-installed-check-' + [guid]::NewGuid().ToString('N'))
    $null = New-Item -ItemType Directory -Path $externalCwd
    Write-SetupLog "installed_check_cwd=$externalCwd"
    Push-Location $externalCwd
    try {
        Invoke-Checked $console @('--help')
        Invoke-Checked $console @('demo','--workspace',(Join-Path $runRoot 'demo'))
        Invoke-Checked $venvPython @('-I','-B','-m','unittest','discover','-s',(Join-Path $projectRoot 'tests'),'-v')
    } finally {
        Pop-Location
        if (@(Get-ChildItem -LiteralPath $externalCwd -Force).Count -eq 0) { Remove-Item -LiteralPath $externalCwd }
        else { Write-SetupLog "Unexpected files in external check directory; retained for inspection: $externalCwd" }
    }
    Write-SetupLog "PASS: isolated normal installation, console help, synthetic demo and offline tests. Evidence: $runRoot"
} finally {
    foreach ($name in $environmentNames) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
    Pop-Location
}
