from importlib import resources
from pathlib import Path

import typer

from daq_cli.application.profile_service import ProfileService
from daq_cli.cli.common import RequiredProfileOption

app = typer.Typer(no_args_is_help=True, help="Manage DAQ profiles.")


@app.command("show")
def show_profile(profile: RequiredProfileOption = ...) -> None:
    """Show a profile summary."""
    service = ProfileService()
    loaded = service.load_profile(profile)
    typer.echo(f"profile: {profile}")
    typer.echo(f"devices: {len(loaded.devices)}")
    typer.echo(f"groups: {len(loaded.groups)}")


@app.command("validate")
def validate_profile(profile: RequiredProfileOption = ...) -> None:
    """Validate a profile file."""
    service = ProfileService()
    loaded = service.load_profile(profile)
    typer.echo(
        f"Profile OK: devices={len(loaded.devices)} groups={len(loaded.groups)}"
    )


@app.command("init")
def init_profile(
    output: Path = typer.Argument(help="Output path for the generated profile template.")
) -> None:
    """Write the bundled example profile template to a target path."""
    template = resources.files("daq_cli.profile_templates").joinpath("example.template.yaml")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    typer.echo(f"Wrote profile template: {output}")
