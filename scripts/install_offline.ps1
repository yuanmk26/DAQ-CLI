param(
    [string]$ReleaseRoot = "."
)

$ErrorActionPreference = "Stop"

$resolvedRoot = Resolve-Path $ReleaseRoot
$wheelhouse = Join-Path $resolvedRoot "wheelhouse"
$mainWheel = Get-ChildItem -Path $resolvedRoot -Filter "daq_cli-*-py3-none-any.whl" | Select-Object -First 1

if ($null -eq $mainWheel) {
    throw "Could not find the main daq-cli wheel under $resolvedRoot"
}

if (-not (Test-Path $wheelhouse)) {
    throw "Could not find wheelhouse under $resolvedRoot"
}

python -m venv (Join-Path $resolvedRoot ".venv")
$activateScript = Join-Path $resolvedRoot ".venv\\Scripts\\Activate.ps1"
. $activateScript
python -m pip install --no-index --find-links $wheelhouse $mainWheel.FullName

Write-Host ""
Write-Host "Offline installation complete."
Write-Host "Next steps:"
Write-Host "  daq --help"
Write-Host "  daq profile init .\\lab-pc-01.yaml"
