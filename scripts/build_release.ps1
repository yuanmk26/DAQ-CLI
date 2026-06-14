$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$pyproject = Get-Content .\pyproject.toml
$versionMatch = $pyproject | Select-String '^version = "([^"]+)"$'
if ($null -eq $versionMatch) {
    throw "Could not determine project version from pyproject.toml"
}
$version = $versionMatch.Matches[0].Groups[1].Value
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$distRoot = Join-Path $repoRoot "dist"
$stagingRoot = Join-Path $distRoot "staging-$stamp"
$offlineRoot = Join-Path $repoRoot "dist\daq_cli-$version-offline-win-amd64"
$wheelhouse = Join-Path $offlineRoot "wheelhouse"
$mainWheel = Join-Path $stagingRoot "daq_cli-$version-py3-none-any.whl"
$offlineZip = Join-Path $repoRoot "dist\daq_cli-$version-offline-win-amd64.zip"
$buildTemp = Join-Path $repoRoot ".tmp-build"

Write-Host "Installing build frontend..."
python -m pip install -U build

Write-Host "Cleaning old build artifacts..."
if (Test-Path .\build) {
    Remove-Item -Recurse -Force .\build
}
if (-not (Test-Path $distRoot)) {
    New-Item -ItemType Directory -Force $distRoot | Out-Null
}
if (Test-Path $stagingRoot) {
    Remove-Item -Recurse -Force $stagingRoot
}
if (Test-Path $offlineRoot) {
    Remove-Item -Recurse -Force $offlineRoot
}
if (-not (Test-Path $buildTemp)) {
    New-Item -ItemType Directory -Force $buildTemp | Out-Null
}

$env:TMP = $buildTemp
$env:TEMP = $buildTemp

Write-Host "Building wheel and sdist..."
python -m build --no-isolation --outdir $stagingRoot

if (-not (Test-Path $mainWheel)) {
    throw "Main wheel was not created: $mainWheel"
}

Write-Host "Preparing offline release directory..."
New-Item -ItemType Directory -Force $wheelhouse | Out-Null
Copy-Item $mainWheel $offlineRoot
Copy-Item .\scripts\install_offline.ps1 $offlineRoot
Copy-Item .\profiles\example.template.yaml $offlineRoot
Copy-Item .\docs\install-on-new-pc.md $offlineRoot
Copy-Item .\README.md $offlineRoot

Write-Host "Downloading dependency wheels..."
python -m pip download --only-binary=:all: --dest $wheelhouse `
    "matplotlib>=3.8" `
    "pyyaml>=6.0" `
    "typer>=0.12,<1.0" `
    "rich>=13.0"

Write-Host "Creating offline release archive..."
if (Test-Path $offlineZip) {
    Remove-Item $offlineZip -Force
}
Compress-Archive -Path "$offlineRoot\*" -DestinationPath $offlineZip

Write-Host ""
Write-Host "Build complete. Release artifacts:"
Get-ChildItem .\dist | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize
