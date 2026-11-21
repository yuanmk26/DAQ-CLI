"""Dedicated GUI entry point.

This entry point exists because ``daq gui`` runs inside the typer app, whose
import chain already pulls in ``matplotlib.pyplot`` (via the monitor command
module) and locks the backend. Launching the GUI through ``daq-gui`` selects
the TkAgg backend as the very first action, which is required before any
``pyplot`` import for embedding figures in the tkinter window.
"""

import argparse
import multiprocessing
import sys
from pathlib import Path

import matplotlib

matplotlib.use("TkAgg")  # must precede every other matplotlib import
# Chinese labels in embedded figures (source labels / titles) need a CJK
# font; DejaVu Sans renders them as tofu.
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False


def main() -> None:
    from daq_cli.presentation.gui.fonts import enable_dpi_awareness

    # Tk does not mark the process DPI-aware; on a scaled laptop that makes
    # the default UI font physically tiny.  Must run before the first tk.Tk().
    enable_dpi_awareness()

    # PyInstaller + multiprocessing spawn on Windows: the frozen child
    # re-executes this entry point, so this must run before argparse or any
    # GUI construction.  Without it, capture backends (decode / wave watch)
    # would spawn extra GUI windows or hang.
    multiprocessing.freeze_support()

    parser = argparse.ArgumentParser(description="daq-cli GUI console")
    parser.add_argument(
        "--profile",
        "-p",
        default=None,
        help="Path to the DAQ profile YAML file to load at startup.",
    )
    args = parser.parse_args()

    profile_path = args.profile
    if profile_path is None:
        from daq_cli.presentation.gui.startup import discover_profile

        base_dir = (
            Path(sys.executable).resolve().parent
            if getattr(sys, "frozen", False)
            else Path.cwd()
        )
        discovered = discover_profile(base_dir)
        if discovered is not None:
            profile_path = str(discovered)

    import tkinter as tk

    from daq_cli.presentation.gui.app import DaqGuiApp

    root = tk.Tk()
    DaqGuiApp(root, profile_path=profile_path)
    root.mainloop()


if __name__ == "__main__":
    main()
