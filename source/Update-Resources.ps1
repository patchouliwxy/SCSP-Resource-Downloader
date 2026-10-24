param(
    [string]$GameVersion,
    [string]$ResourceVersion,
    [string]$ConsoleLog,
    [switch]$ReloadOnly
)
$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '缺少本地Python环境，请先运行setup.ps1。' }
$updateArguments = @('-X', 'utf8', (Join-Path $PSScriptRoot 'scsp_update.py'))
if ($ReloadOnly) { $updateArguments += '--reload-only' }
elseif ($ConsoleLog) { $updateArguments += @('--console-log', (Resolve-Path -LiteralPath $ConsoleLog).Path) }
else {
    if (-not $GameVersion) { $GameVersion = Read-Host 'Game Version（例如2.18.0）' }
    if (-not $ResourceVersion) { $ResourceVersion = Read-Host '完整Resource Version（保留@后的编码）' }
    $updateArguments += @('--game-version', $GameVersion, '--resource-version', $ResourceVersion)
}
& $pythonPath @updateArguments
if ($LASTEXITCODE -ne 0) { throw "更新未完全完成，请查看上方报告（退出码$LASTEXITCODE）。" }
