from pathlib import Path
from typing import Annotated

import typer

from daq_cli.application.acquire_service import AcquireService
from daq_cli.cli.common import ProfileOption
from daq_cli.presentation.console.printers import (
    print_multi_acquire_result,
    print_single_acquire_result,
)

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


@app.command("multi")
def acquire_multi(
    group: Annotated[str, typer.Argument(help="Logical group name from the profile.")],
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help="Base output directory for multi-board run folders. Defaults to profile defaults.",
        ),
    ] = None,
    aggregation_key: Annotated[
        str,
        typer.Option(
            "--aggregation-key",
            help="Event aggregation key: timestamp or event_count.",
            case_sensitive=False,
        ),
    ] = "timestamp",
    timestamp_match_window_ticks: Annotated[
        int,
        typer.Option(
            "--timestamp-match-window",
            min=0,
            help="Allowed timestamp skew in ticks when aggregation_key=timestamp.",
        ),
    ] = 10,
    event_timeout_ms: Annotated[
        int,
        typer.Option(
            "--event-timeout-ms",
            min=1,
            help="Flush incomplete events after this timeout in milliseconds.",
        ),
    ] = 50,
    tcp_timeout_s: Annotated[
        float,
        typer.Option(
            "--timeout",
            min=0.1,
            help="TCP socket timeout in seconds for each board receiver.",
        ),
    ] = 1.0,
    allow_start_without_ack: Annotated[
        bool,
        typer.Option(
            "--allow-start-without-ack/--require-ack",
            help="Continue even if TCM alignment does not report all ACK bits.",
        ),
    ] = False,
    profile: ProfileOption = Path("profiles/example.yaml"),
) -> None:
    """Run legacy multi-board acquisition for one logical group."""
    normalized_aggregation_key = aggregation_key.lower()
    if normalized_aggregation_key not in {"timestamp", "event_count"}:
        raise typer.BadParameter(
            "aggregation key must be 'timestamp' or 'event_count'"
        )

    service = AcquireService()
    try:
        result = service.capture_multi(
            group_name=group,
            profile_path=profile,
            output_base_dir=output_dir,
            aggregation_key=normalized_aggregation_key,
            timestamp_match_window_ticks=timestamp_match_window_ticks,
            event_timeout_ms=event_timeout_ms,
            tcp_timeout_s=tcp_timeout_s,
            allow_start_without_ack=allow_start_without_ack,
        )
    except Exception as exc:
        typer.echo(f"Multi-board acquisition failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    print_multi_acquire_result(result)
