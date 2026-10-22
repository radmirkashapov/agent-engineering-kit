$ErrorActionPreference = "Stop"
$Repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$GitRoot = git -C $Repository rev-parse --show-toplevel 2> $null
if ($LASTEXITCODE -ne 0 -or -not $GitRoot) {
    throw "bootstrap/install.ps1 необходимо запускать из полного Git checkout, а не из ZIP-архива."
}
$GitRoot = (Resolve-Path $GitRoot.Trim()).Path
if ($GitRoot -ne $Repository) {
    throw "bootstrap/install.ps1 необходимо запускать из корня полного Git checkout, а не из вложенного ZIP-архива."
}
python -m pip install --user $Repository
if ($LASTEXITCODE -ne 0) {
    throw "Не удалось установить Python-пакет agent-kit. repository-path не изменён."
}

# CLI использует полный checkout как канонический источник manifests и документации.
if ($env:AGENT_KIT_DATA_HOME) {
    $DataHome = $env:AGENT_KIT_DATA_HOME
} elseif ($env:LOCALAPPDATA) {
    $DataHome = Join-Path $env:LOCALAPPDATA "agent-engineering-kit"
} else {
    $DataHome = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "agent-engineering-kit"
}
$StateDirectory = Join-Path $DataHome "state"
$Pointer = Join-Path $StateDirectory "repository-path"
$PointerTemporary = "$Pointer.tmp.$PID"
New-Item -ItemType Directory -Force -Path $StateDirectory | Out-Null
[System.IO.File]::WriteAllText($PointerTemporary, "$Repository`n", (New-Object System.Text.UTF8Encoding($false)))
Move-Item -Force -Path $PointerTemporary -Destination $Pointer

Write-Output "agent-kit установлен. Канонический repository: $Repository"
Write-Output "Не перемещайте checkout без повторного запуска bootstrap/install.ps1."
Write-Output "Запустите: agent-kit resync --no-update; agent-kit validate --ci; agent-kit doctor"
