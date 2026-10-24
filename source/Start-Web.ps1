$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw '未找到本地 Python 环境，请先运行 setup.ps1。'
}
Write-Host '启动后在浏览器打开 http://127.0.0.1:8765，按 Ctrl+C 停止服务。'
& $pythonPath (Join-Path $PSScriptRoot 'scsp_web.py') @args
