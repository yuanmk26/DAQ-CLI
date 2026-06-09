$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "Installing build frontend..."
python -m pip install -U build

Write-Host "Cleaning old build artifacts..."
if (Test-Path .\build) {
    Remove-Item -Recurse -Force .\build
}
if (Test-Path .\dist) {
    Remove-Item -Recurse -Force .\dist
}

Write-Host "Building wheel and sdist..."
python -m build

Write-Host ""
Write-Host "Build complete. Release artifacts:"
Get-ChildItem .\dist | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize
