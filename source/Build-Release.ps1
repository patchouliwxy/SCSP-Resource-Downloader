$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
& .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed' }
& .\.venv\Scripts\python.exe build_release.py
if ($LASTEXITCODE -ne 0) { throw 'Release build failed' }
