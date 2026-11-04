$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$buildPython = Join-Path $PSScriptRoot '.venv-build\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $buildPython)) {
    python -m venv .venv-build
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create build environment' }
}
& $buildPython -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'Failed to install build dependencies' }
& $buildPython -m PyInstaller --noconfirm --distpath build\release nurse_backend.spec
if ($LASTEXITCODE -ne 0) { throw 'Failed to build executable' }
$deployDir = Join-Path $PSScriptRoot 'dist\NurseBackend'
$stagedDir = Join-Path $PSScriptRoot 'build\release\NurseBackend'
# Update executable components without removing existing .env, models or out.
New-Item -ItemType Directory -Force -Path (Join-Path $deployDir '_internal') | Out-Null
Copy-Item -LiteralPath (Join-Path $stagedDir 'NurseBackend.exe') -Destination $deployDir -Force
Copy-Item -Path (Join-Path $stagedDir '_internal\*') -Destination (Join-Path $deployDir '_internal') -Recurse -Force
# Local keys are copied only to the external configuration, never bundled.
if (-not (Test-Path -LiteralPath (Join-Path $deployDir '.env'))) {
    if (Test-Path -LiteralPath '.env') {
        Copy-Item -LiteralPath '.env' -Destination (Join-Path $deployDir '.env')
    } else {
        & $buildPython -c "from env_config import ENV_EXAMPLE_TEMPLATE; from pathlib import Path; Path('dist/NurseBackend/.env').write_text(ENV_EXAMPLE_TEMPLATE, encoding='utf-8')"
    }
}
$modelRoot = Join-Path $env:USERPROFILE '.cache\huggingface\hub\models--Systran--faster-whisper-medium\snapshots'
$modelSnapshot = Get-ChildItem -LiteralPath $modelRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'model.bin') } |
    Select-Object -First 1
$targetModel = Join-Path $deployDir 'models\whisper-medium'
New-Item -ItemType Directory -Force -Path $targetModel | Out-Null
if ($modelSnapshot) {
    Copy-Item -Path (Join-Path $modelSnapshot.FullName '*') -Destination $targetModel -Recurse -Force
} else {
    & $buildPython -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-medium', local_dir='dist/NurseBackend/models/whisper-medium')"
    if ($LASTEXITCODE -ne 0) { throw 'Failed to download ASR model' }
}
Copy-Item -LiteralPath 'EXE_README.txt' -Destination (Join-Path $deployDir 'README.txt')
Write-Host "Ready: $deployDir\NurseBackend.exe"
