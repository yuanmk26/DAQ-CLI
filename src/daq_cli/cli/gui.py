from typing import Annotated

import typer

from daq_cli.cli.common import ProfileOption

app = typer.Typer(no_args_is_help=True, help="GUI console commands.")


@app.command()
def gui(
    profile: Annotated[
        str | None,
        typer.Option("--profile", "-p", help="Path to the DAQ profile YAML file."),
    ] = None,
) -> None:
    """Open the desktop GUI console.

    Prefer the ``daq-gui`` entry point: it selects the TkAgg matplotlib
    backend before any other import, which this subcommand cannot guarantee
    because the CLI import chain already loads pyplot.
    """
    import matplotlib

    matplotlib.use("TkAgg")  # defensive: no-op if the backend is already set

    import tkinter as tk

    from daq_cli.presentation.gui.app import DaqGuiApp

    root = tk.Tk()
    DaqGuiApp(root, profile_path=profile)
    root.mainloop()
