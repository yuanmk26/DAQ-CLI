$ErrorActionPreference = "Stop"

# Build standalone executables (daq-gui.exe + daq.exe) with PyInstaller.
# Usage:  .\scripts\build_exe.ps1
# Output: dist-exe\daq-gui.exe, dist-exe\daq.exe

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "Installing PyInstaller if missing..."
python -m pip install pyinstaller -q

Write-Host "Building executables (this takes a few minutes)..."

python -m PyInstaller packaging\daq.spec `
    --distpath dist-exe `
    --workpath .tmp-pyinstaller `
    --noconfirm

Write-Host ""
Write-Host "Build complete:"
Get-ChildItem .\dist-exe | Select-Object Name, @{N="SizeMB"; E={[math]::Round($_.Length/1MB,1)}}, LastWriteTime | Format-Table -AutoSize