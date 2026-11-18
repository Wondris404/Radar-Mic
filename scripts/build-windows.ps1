$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& .\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE) { throw 'Tests failed' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name RADAR-MIC scripts\entry.py
if ($LASTEXITCODE) { throw 'Build failed' }
$smoke = Start-Process -FilePath "$PWD\dist\RADAR-MIC\RADAR-MIC.exe" -ArgumentList '--smoke-test' -Wait -PassThru
if ($smoke.ExitCode -ne 0) { throw 'Packaged application smoke test failed' }
Compress-Archive -Path dist\RADAR-MIC -DestinationPath dist\RADAR-MIC-Windows.zip -Force
