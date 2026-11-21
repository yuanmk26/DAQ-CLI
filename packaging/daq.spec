# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for daq-cli.

Builds two standalone one-file executables:
  - daq-gui.exe  (windowed GUI console)
  - daq.exe      (console CLI)

Key detail: the vendored legacy scripts under
src/daq_cli/_vendor/fdu_legacy/ are loaded at runtime via importlib
(importlib.import_module("FPGA_CTRL"), "multi_board_acquire", "lib.rbcp", ...)
after sys.path insertion. PyInstaller's static analysis cannot see them, so
the whole directory is shipped as data files (including the .py sources);
the runtime sys.path insertion then resolves them with the normal file
finder.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

REPO_ROOT = Path(SPECPATH).parent
SRC = REPO_ROOT / "src"

_datas = [
    (str(SRC / "daq_cli" / "_vendor" / "fdu_legacy"), "daq_cli/_vendor/fdu_legacy"),
    (str(SRC / "daq_cli" / "monitoring_samples"), "daq_cli/monitoring_samples"),
    (str(SRC / "daq_cli" / "profile_templates"), "daq_cli/profile_templates"),
]

_hiddenimports = collect_submodules("daq_cli")

# The app uses numpy + matplotlib + tkinter only. PyInstaller's hooks
# otherwise pull in scipy/pandas/numba/llvmlite; llvmlite alone is ~120 MB
# uncompressed and dominates onefile startup time.
_excludes = ["scipy", "pandas", "numba", "llvmlite", "pytest", "IPython"]


# ---------------------------------------------------------------- GUI

_gui_analysis = Analysis(
    [str(SRC / "daq_cli" / "gui_main.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=_excludes,
    noarchive=False,
)
_gui_pyz = PYZ(_gui_analysis.pure)
_gui_exe = EXE(
    _gui_pyz,
    _gui_analysis.scripts,
    _gui_analysis.binaries,
    _gui_analysis.datas,
    [],
    name="daq-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

# ---------------------------------------------------------------- CLI

_cli_analysis = Analysis(
    [str(SRC / "daq_cli" / "main.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=_excludes,
    noarchive=False,
)
_cli_pyz = PYZ(_cli_analysis.pure)
_cli_exe = EXE(
    _cli_pyz,
    _cli_analysis.scripts,
    _cli_analysis.binaries,
    _cli_analysis.datas,
    [],
    name="daq",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
)
