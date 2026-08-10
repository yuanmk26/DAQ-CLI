"""Dedicated GUI entry point.

This entry point exists because ``daq gui`` runs inside the typer app, whose
import chain already pulls in ``matplotlib.pyplot`` (via the monitor command
module) and locks the backend. Launching the GUI through ``daq-gui`` selects
the TkAgg backend as the very first action, which is required before any
``pyplot`` import for embedding figures in the tkinter window.
"""

import argparse

import matplotlib

matplotlib.use("TkAgg")  # must precede every other matplotlib import


def main() -> None:
    parser = argparse.ArgumentParser(description="daq-cli GUI console")
    parser.add_argument(
        "--profile",
        "-p",
        default=None,
        help="Path to the DAQ profile YAML file to load at startup.",
    )
    args = parser.parse_args()

    import tkinter as tk

    from daq_cli.presentation.gui.app import DaqGuiApp

    root = tk.Tk()
    DaqGuiApp(root, profile_path=args.profile)
    root.mainloop()


if __name__ == "__main__":
    main()
