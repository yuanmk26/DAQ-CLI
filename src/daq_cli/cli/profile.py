from pathlib import Path

import typer

from daq_cli.application.profile_service import ProfileService

app = typer.Typer(no_args_is_help=True, help="Manage DAQ profiles.")


@app.command("show")
def show_profile(profile: Path = Path("profiles/example.yaml")) -> None:
    """Show a profile summary."""
    service = ProfileService()
    loaded = service.load_profile(profile)
    typer.echo(f"profile: {profile}")
    typer.echo(f"devices: {len(loaded.devices)}")
    typer.echo(f"groups: {len(loaded.groups)}")


@app.command("validate")
def validate_profile(profile: Path = Path("profiles/example.yaml")) -> None:
    """Validate a profile file."""
    service = ProfileService()
    loaded = service.load_profile(profile)
    typer.echo(
        f"Profile OK: devices={len(loaded.devices)} groups={len(loaded.groups)}"
    )
