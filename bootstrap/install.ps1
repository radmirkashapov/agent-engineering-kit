$ErrorActionPreference = "Stop"
$Repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
python -m pip install --user $Repository
Write-Output "agent-kit установлен. Запустите: agent-kit doctor"
