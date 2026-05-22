from typing import Annotated
from pathlib import Path

import typer

from daq_cli.application.board_service import BoardService
from daq_cli.cli.common import ProfileOption
from daq_cli.presentation.console.printers import print_board_info

app = typer.Typer(no_args_is_help=True, help="Single-board operations.")


@app.command("info")
def board_info(
    device: Annotated[str, typer.Argument(help="Logical device name from the profile.")],
    profile: ProfileOption = Path("profiles/example.yaml"),
) -> None:
    """Show profile-backed board information."""
    service = BoardService()
    info = service.get_board_info(device_name=device, profile_path=profile)
    print_board_info(info)


@app.command("sysmon")
def board_sysmon(
    device: Annotated[str, typer.Argument(help="Logical device name from the profile.")],
    profile: ProfileOption = Path("profiles/example.yaml"),
) -> None:
    """Placeholder for FPGA sysmon telemetry."""
    _ = device, profile
    typer.echo("Not implemented yet.")
    raise typer.Exit(code=1)


@app.command("config")
def board_config(
    device: Annotated[str, typer.Argument(help="Logical device name from the profile.")],
    profile: ProfileOption = Path("profiles/example.yaml"),
) -> None:
    """Placeholder for board configuration workflow."""
    _ = device, profile
    typer.echo("Not implemented yet.")
    raise typer.Exit(code=1)
