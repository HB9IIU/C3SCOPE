# Builds the portable Windows package: dist\C3SCOPE-portable.zip
# Bundles the official embeddable Python plus the app, so no PyInstaller exe is
# produced (unsigned PyInstaller exes are often flagged by Windows Defender).
# Usage (needs internet, and Python 3.11 64-bit on this PC to fetch wheels):
#   powershell -File build_portable.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$pyVersion = '3.11.9'
$out = 'dist\C3SCOPE'
if (Test-Path dist) { Remove-Item dist -Recurse -Force }
New-Item -ItemType Directory -Force "$out\python", "$out\app" | Out-Null

$embed = "dist\python-embed.zip"
Invoke-WebRequest "https://www.python.org/ftp/python/$pyVersion/python-$pyVersion-embed-amd64.zip" -OutFile $embed
Expand-Archive $embed "$out\python"
Remove-Item $embed

# Embeddable Python ignores PYTHONPATH; list the search paths in its ._pth file.
Set-Content "$out\python\python311._pth" @('python311.zip', '.', 'Lib\site-packages', '..\app') -Encoding ascii

python -m pip install --quiet --target "$out\python\Lib\site-packages" -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

Copy-Item app.py, app_instance.py, app_lifecycle.py, firmware_setup.py -Destination "$out\app"
Copy-Item viewer -Destination "$out\app\viewer" -Recurse -Exclude '__pycache__'
Copy-Item README.md, viewer\LICENSE -Destination $out

Set-Content "$out\C3SCOPE.bat" @(
    '@echo off',
    'title C3SCOPE',
    'cd /d "%~dp0app"',
    '"%~dp0python\python.exe" app.py %*',
    'if errorlevel 1 pause'
) -Encoding ascii

Compress-Archive -Path $out -DestinationPath dist\C3SCOPE-portable.zip
Write-Host "Done: dist\C3SCOPE-portable.zip"
