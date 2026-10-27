# Build dist\C3SCOPE-portable.zip. Other files in dist are never removed.
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
Set-Location -LiteralPath $projectRoot
$distRoot = Join-Path $projectRoot 'dist'
$buildRoot = Join-Path $projectRoot 'build'
$out = Join-Path $distRoot 'C3SCOPE'
$sourceRoot = Join-Path $buildRoot 'portable-source'

function Assert-WorkspaceChild([string] $target) {
    $absolute = [IO.Path]::GetFullPath($target)
    if (-not $absolute.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Build target escapes the project: $absolute"
    }
    if ((Test-Path -LiteralPath $absolute) -and ((Get-Item -LiteralPath $absolute).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to build through a junction or symlink: $absolute"
    }
}
foreach ($path in @($distRoot, $buildRoot, $out, $sourceRoot)) { Assert-WorkspaceChild $path }
New-Item -ItemType Directory -Force $distRoot, $buildRoot | Out-Null
# Only these generated directories are replaced, after absolute-path checks.
foreach ($path in @($out, $sourceRoot)) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
}
New-Item -ItemType Directory -Force "$out\python", "$out\app", "$sourceRoot\C3SCOPE" | Out-Null

$runtime = Get-Content -Raw -LiteralPath 'packaging\windows-runtime.json' | ConvertFrom-Json
$embed = Join-Path $buildRoot "python-$($runtime.version)-embed-amd64.zip"
if (-not (Test-Path -LiteralPath $embed) -or (Get-FileHash -LiteralPath $embed -Algorithm SHA256).Hash.ToLowerInvariant() -ne $runtime.sha256) {
    Invoke-WebRequest $runtime.url -OutFile $embed
}
if ((Get-FileHash -LiteralPath $embed -Algorithm SHA256).Hash.ToLowerInvariant() -ne $runtime.sha256) {
    throw 'Official Python runtime checksum mismatch.'
}
Expand-Archive -LiteralPath $embed -DestinationPath "$out\python"
Set-Content "$out\python\python$($runtime.python_tag)._pth" @("python$($runtime.python_tag).zip", '.', 'Lib\site-packages', '..\app') -Encoding ascii

# Match wheels to the embedded runtime, not to the Python running this builder.
$pythonMinor = ($runtime.version -split '\.')[0..1] -join '.'
$wheelhouse = Join-Path $buildRoot 'portable-wheels'
$esptoolPin = Get-Content requirements-lock.txt | Where-Object { $_ -match '^esptool==' }
python -m pip wheel --quiet --no-deps --wheel-dir $wheelhouse $esptoolPin
if ($LASTEXITCODE -ne 0) { throw 'Building the pure-Python esptool wheel failed.' }
python -m pip install --quiet --find-links $wheelhouse --only-binary=:all: --platform win_amd64 --implementation cp --python-version $pythonMinor --abi "cp$($runtime.python_tag)" --no-compile --target "$out\python\Lib\site-packages" -r requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Installing pinned portable dependencies failed.' }

$appFiles = @('app.py', 'app_instance.py', 'app_lifecycle.py', 'firmware_setup.py', 'serial_policy.py')
Copy-Item -LiteralPath $appFiles -Destination "$out\app"
Copy-Item -LiteralPath viewer -Destination "$out\app\viewer" -Recurse
Copy-Item -LiteralPath third_party -Destination "$out\third_party" -Recurse
Copy-Item -LiteralPath 'THIRD_PARTY.md', 'COPYING.md', 'SECURITY.md', 'MODIFICATIONS.md', 'requirements-lock.txt' -Destination $out
Copy-Item -LiteralPath portable-readme.txt -Destination "$out\README.txt"
if (Test-Path -LiteralPath LICENSE) { Copy-Item -LiteralPath LICENSE -Destination $out }
else { Copy-Item -LiteralPath 'viewer\LICENSE' -Destination "$out\LICENSE-ESP-WebSDR" }

# Ship a source snapshot without .git, private environment files or old builds.
$source = "$sourceRoot\C3SCOPE"
Copy-Item -LiteralPath $appFiles -Destination $source
Get-ChildItem -LiteralPath $projectRoot -Filter 'test_*.py' | Copy-Item -Destination $source
Copy-Item -LiteralPath 'README.md', 'DEVELOPMENT.md', 'BASELINE.md', 'THIRD_PARTY.md', 'COPYING.md', 'SECURITY.md', 'MODIFICATIONS.md', 'portable-readme.txt', 'requirements.txt', 'requirements-lock.txt', 'build_portable.ps1' -Destination $source
foreach ($directory in @('viewer', 'docs', 'packaging', 'third_party', 'tools')) {
    Copy-Item -LiteralPath $directory -Destination (Join-Path $source $directory) -Recurse
}
if (Test-Path -LiteralPath LICENSE) { Copy-Item -LiteralPath LICENSE -Destination $source }
# Published beside the portable zip on the release, not inside it, to keep the download small.
python tools/package_zip.py $source (Join-Path $distRoot 'C3SCOPE-source.zip')
if ($LASTEXITCODE -ne 0) { throw 'Source packaging failed.' }

Set-Content "$out\C3SCOPE.bat" @(
    '@echo off', 'title C3SCOPE', 'cd /d "%~dp0app"',
    '"%~dp0python\python.exe" app.py %*', 'if errorlevel 1 pause'
) -Encoding ascii

# Exercise shipped interpreter and native wheels before producing a release.
& "$out\python\python.exe" -c "import flask, flask_sock, serial, esptool, cryptography, cffi, yaml; import app; from firmware_setup import package; package(app.ROOT); print('Portable runtime and firmware checks passed')"
if ($LASTEXITCODE -ne 0) { throw 'Portable runtime smoke check failed.' }

$sourceCommit = 'unversioned source archive'
$sourceDirty = $false
if ((Test-Path -LiteralPath '.git') -and (Get-Command git -ErrorAction SilentlyContinue)) {
    $sourceCommit = git rev-parse HEAD
    $sourceDirty = [bool](git status --porcelain)
}
$sourceHash = (Get-FileHash -LiteralPath (Join-Path $distRoot 'C3SCOPE-source.zip') -Algorithm SHA256).Hash.ToLowerInvariant()
$info = [ordered]@{ python = $runtime.version; python_sha256 = $runtime.sha256; built_utc = [DateTime]::UtcNow.ToString('o'); source_commit = $sourceCommit; source_has_local_changes = $sourceDirty; source_archive_sha256 = $sourceHash; dependencies = @(Get-Content requirements-lock.txt | Where-Object { $_ -and -not $_.StartsWith('#') }) }
$info | ConvertTo-Json -Depth 4 | Set-Content "$out\BUILD-INFO.json" -Encoding utf8
$zip = Join-Path $distRoot 'C3SCOPE-portable.zip'
python tools/package_zip.py $out $zip
if ($LASTEXITCODE -ne 0) { throw 'Portable packaging failed.' }
$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content (Join-Path $distRoot 'C3SCOPE-portable.zip.sha256') "$hash  C3SCOPE-portable.zip" -Encoding ascii
Write-Host "Done: $zip"
