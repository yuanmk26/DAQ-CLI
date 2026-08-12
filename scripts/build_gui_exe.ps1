# Build the standalone GUI executable (PyInstaller onefile, windowed).
# Run from the repo root: powershell -ExecutionPolicy Bypass -File scripts/build_gui_exe.ps1
#
# Notes on the vendored legacy scripts:
#  - `daq_cli._vendor` and its `fdu_legacy` child must be explicitly
#    hidden-imported: PyInstaller's collect helpers skip the underscore
#    package under the editable install, and resources.files() needs the
#    parent package importable at runtime.
#  - The legacy scripts are loaded by bare-name dynamic imports
#    (importlib.import_module("FPGA_CTRL")) with the bundled directory
#    inserted into sys.path, so the .py files must exist as DATA files
#    under _MEIPASS (a PYZ-only module is not file-system visible).
#  - pathex must include the legacy dirs so PyInstaller can analyse the
#    stdlib imports (queue etc.) of those dynamic modules.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$version = (Get-Content .\pyproject.toml | Select-String '^version = "([^"]+)"$').Matches[0].Groups[1].Value
$name = "daq-gui-$version"

# Prefer the Python with PyInstaller installed; fall back to `python`.
$pythons = @(
    "$env:USERPROFILE\AppData\Local\Programs\Python\Python313\python.exe",
    "C:\Python313\python.exe"
)
$py = $null
foreach ($candidate in $pythons) {
    if (Test-Path $candidate) { $py = $candidate; break }
}
if (-not $py) { $py = "python" }

Write-Host "Building $name.exe with $py ..."
& $py -m PyInstaller --noconfirm --onefile --windowed --name $name `
  --paths src `
  --paths src/daq_cli/_vendor/fdu_legacy `
  --paths src/daq_cli/_vendor/fdu_legacy/lib `
  --hidden-import daq_cli._vendor `
  --hidden-import daq_cli._vendor.fdu_legacy `
  --hidden-import FPGA_CTRL `
  --hidden-import HMCAD1511 `
  --hidden-import multi_board_acquire `
  --hidden-import mux `
  --hidden-import si5345_16ch `
  --hidden-import start_16CH_two_board `
  --hidden-import capture_tcp_sent_mode2 `
  --hidden-import check_tcp_sent_mode2 `
  --hidden-import lib.rbcp `
  --hidden-import lib.i2c `
  --hidden-import lib.spi_3wire `
  --hidden-import lib.sysmon `
  --add-data "src/daq_cli/_vendor/fdu_legacy;daq_cli/_vendor/fdu_legacy" `
  --collect-all daq_cli.monitoring_samples `
  --collect-all daq_cli.profile_templates `
  --collect-submodules daq_cli `
  src/daq_cli/gui_main.py

Write-Host "Build complete: dist\$name.exe"
