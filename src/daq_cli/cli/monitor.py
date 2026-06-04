from pathlib import Path
from typing import Annotated

import typer

from daq_cli.application.monitor_service import MonitorService
from daq_cli.cli.common import ProfileOption
from daq_cli.presentation.wave_monitor_viewer import run_wave_monitor_viewer

app = typer.Typer(no_args_is_help=True, help="Monitoring commands.")


@app.command("board")
def monitor_board() -> None:
    """Placeholder for board monitoring."""
    typer.echo("Not implemented yet.")
    raise typer.Exit(code=1)


@app.command("wave")
def monitor_wave(
    device: Annotated[str, typer.Argument(help="Logical device name or preview label.")],
    demo: Annotated[
        bool,
        typer.Option(
            "--demo",
            help="Run the built-in offline waveform preview without talking to hardware.",
        ),
    ] = False,
    replay: Annotated[
        Path | None,
        typer.Option(
            "--replay",
            help="Replay waveform preview data from a structured dump file.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    profile: ProfileOption = Path("profiles/example.yaml"),
) -> None:
    """Open a 16-channel waveform monitor window."""
    if demo and replay is not None:
        raise typer.BadParameter("--demo and --replay cannot be used together.")

    service = MonitorService()
    try:
        if demo:
            context = service.open_demo_wave_session(device_name=device)
        elif replay is not None:
            context = service.open_replay_wave_session(
                device_name=device,
                replay_path=replay,
            )
        else:
            context = service.open_live_wave_session(
                device_name=device,
                profile_path=profile,
            )
        with context as session:
            run_wave_monitor_viewer(
                source_label=session.source_label,
                frame_queue=session.frame_queue,
                stop_event=session.stop_event,
            )
    except Exception as exc:
        typer.echo(f"Wave monitor failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
