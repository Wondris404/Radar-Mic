$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
py -3 -m venv .venv
if ($LASTEXITCODE) { throw 'Python 3.11+ is required. Install from python.org.' }
& .\.venv\Scripts\python.exe -m pip install -e '.[dev]'
if ($LASTEXITCODE) { throw 'Dependency installation failed' }
Write-Host 'Installed. Run .\Launch.cmd --demo or .\Launch.cmd'
