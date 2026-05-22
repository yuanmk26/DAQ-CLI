from pathlib import Path
from typing import Annotated

import typer

from daq_cli.application.acquire_service import AcquireService
from daq_cli.cli.common import ProfileOption
from daq_cli.presentation.console.printers import print_single_acquire_result

app = typer.Typer(no_args_is_help=True, help="Acquisition commands.")


@app.command("single")
def acquire_single(
    device: Annotated[str, typer.Argument(help="Logical device name from the profile.")],
    events: Annotated[
        int,
        typer.Option("--events", "-n", min=1, help="Number of events to capture."),
    ] = 1000,
    timeout_s: Annotated[
        float,
        typer.Option("--timeout", help="TCP socket timeout in seconds."),
    ] = 10.0,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help="Base output directory for run folders. Defaults to profile defaults.",
        ),
    ] = None,
    profile: ProfileOption = Path("profiles/example.yaml"),
) -> None:
    """Capture raw mode-2 packets from one device."""
    service = AcquireService()
    result = service.capture_single(
        device_name=device,
        profile_path=profile,
        events=events,
        timeout_s=timeout_s,
        output_base_dir=output_dir,
    )
    print_single_acquire_result(result)
