# Builds the portable Windows package: dist\C3SCOPE-portable.zip
# Usage: powershell -ExecutionPolicy Bypass -File build_portable.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

python -m pip install -r requirements.txt pyinstaller
if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path dist\C3SCOPE) { Remove-Item dist\C3SCOPE -Recurse -Force }

python -m PyInstaller --noconfirm --onedir --name C3SCOPE `
    --add-data "viewer;viewer" `
    --collect-all esptool `
    --hidden-import serial.tools.list_ports_windows `
    app.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

Copy-Item README.md, viewer\LICENSE -Destination dist\C3SCOPE
if (Test-Path dist\C3SCOPE-portable.zip) { Remove-Item dist\C3SCOPE-portable.zip }
Compress-Archive -Path dist\C3SCOPE -DestinationPath dist\C3SCOPE-portable.zip
Write-Host "Done: dist\C3SCOPE-portable.zip"
