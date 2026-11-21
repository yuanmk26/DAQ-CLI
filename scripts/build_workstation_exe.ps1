# Build the Windows x64 Qt workstation from its project environment.
param([string]$Python)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
$originalPath = $env:Path
try {
    if (-not $Python) { $Python = Join-Path $repo ".venv-qt\Scripts\python.exe" }
    $Python = (Get-Command $Python -ErrorAction Stop).Source
    # Qt uses the Windows ICU API. Unrelated tools on PATH can supply a
    # different icuuc.dll with the same name and incompatible exports.
    $env:Path = "$(Split-Path -Parent $Python);$env:SystemRoot\System32;$env:SystemRoot"
    $version = (Select-String -Path pyproject.toml -Pattern '^version = "([^"]+)"$').Matches[0].Groups[1].Value
    $name = "daq-workstation-$version-win64"
    $versionDir = New-Item -ItemType Directory -Force build/workstation-version
    $versionFile = Join-Path $versionDir.FullName "version.txt"
    $numbers = ($version.Split('.') + '0') -join ', '
    @"
VSVersionInfo(
    ffi=FixedFileInfo(filevers=($numbers), prodvers=($numbers), OS=0x40004, fileType=1),
    kids=[StringFileInfo([StringTable('040904B0', [
        StringStruct('FileDescription', 'DAQ Workstation'),
        StringStruct('FileVersion', '$version'),
        StringStruct('OriginalFilename', '$name.exe'),
        StringStruct('ProductName', 'DAQ Workstation'),
        StringStruct('ProductVersion', '$version')
    ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"@ | Set-Content -Encoding UTF8 $versionFile
    & $Python -c "import struct, PyInstaller, PySide6.QtWidgets, pyqtgraph, ruamel.yaml; assert struct.calcsize('P') == 8"
    if ($LASTEXITCODE -ne 0) { throw "Use a 64-bit Python with .[qt-replay] and pyinstaller installed." }
    $legacy = "src/daq_cli/_vendor/fdu_legacy"
    $options = @(
        "--clean", "--onefile", "--windowed", "--noconfirm", "--noupx", "--name", $name,
        "--version-file", $versionFile, "--paths", "src", "--paths", $legacy, "--paths", "$legacy/lib",
        "--hidden-import", "daq_cli._vendor.fdu_legacy",
        "--add-data", "${legacy};daq_cli/_vendor/fdu_legacy",
        "--add-data", "profiles/muon-imaging.yaml;workstation_defaults",
        "--collect-submodules", "ruamel.yaml"
    )
    foreach ($module in "FPGA_CTRL", "HMCAD1511", "multi_board_acquire", "mux", "si5345_16ch", "start_16CH_two_board", "lib.rbcp", "lib.i2c", "lib.spi_3wire", "lib.sysmon") {
        $options += "--hidden-import", $module
    }
    foreach ($module in "PyQt5", "PyQt6", "PySide2", "scipy", "pandas", "matplotlib", "tkinter", "numba", "IPython", "pytest", "OpenGL") {
        $options += "--exclude-module", $module
    }
    & $Python -m PyInstaller @options packaging/workstation_main.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
    Write-Host "Built $repo\dist\$name.exe"
} finally {
    $env:Path = $originalPath
    Pop-Location
}
