$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$buildPython = Join-Path $PSScriptRoot '.venv-build\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $buildPython)) {
    python -m venv .venv-build
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create build environment' }
}
& $buildPython -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'Failed to install build dependencies' }
& $buildPython -m PyInstaller --noconfirm --clean --distpath build\release nurse_backend.spec
if ($LASTEXITCODE -ne 0) { throw 'Failed to build executable' }
$deployDir = Join-Path $PSScriptRoot 'Windows'
$stagedExe = Join-Path $PSScriptRoot 'build\release\NurseBackend.exe'
# The one-file executable contains all runtime components. Keep .env and out.
$runtimeDir = Join-Path $deployDir '_internal'
if (Test-Path -LiteralPath $runtimeDir) {
    Remove-Item -LiteralPath $runtimeDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $deployDir | Out-Null
Copy-Item -LiteralPath $stagedExe -Destination $deployDir -Force
# Commit only a safe template. Never copy the developer's local API keys.
if (-not (Test-Path -LiteralPath (Join-Path $deployDir '.env'))) {
    & $buildPython -c "from env_config import ENV_EXAMPLE_TEMPLATE; from pathlib import Path; Path('Windows/.env').write_text(ENV_EXAMPLE_TEMPLATE.replace('ASR_WARMUP_ON_START=1', 'ASR_WARMUP_ON_START=0'), encoding='utf-8')"
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the external environment template' }
}
Copy-Item -LiteralPath 'EXE_README.txt' -Destination (Join-Path $deployDir 'README.txt')
Write-Host "Ready: $deployDir\NurseBackend.exe"
