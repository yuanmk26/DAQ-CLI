from pathlib import Path
from typing import Annotated

import typer

from daq_cli.application.acquire_service import AcquireService, SingleAcquireProgress
from daq_cli.application.profile_service import ProfileService
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
        int | None,
        typer.Option("--events", "-n", min=1, help="Number of events to capture."),
    ] = None,
    timeout_s: Annotated[
        float | None,
        typer.Option("--timeout", help="TCP socket timeout in seconds."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help="Base output directory for run folders. Defaults to profile defaults.",
        ),
    ] = None,
    decode_json: Annotated[
        bool | None,
        typer.Option(
            "--decode-json/--raw-only",
            help="Also decode packets to JSON during capture without replacing raw files.",
        ),
    ] = None,
    decoded_output_dir: Annotated[
        Path | None,
        typer.Option(
            "--decoded-output-dir",
            help="Directory for decoded JSON files when --decode-json is enabled. Defaults to <run_dir>/decoded.",
        ),
    ] = None,
    watch_every: Annotated[
        int | None,
        typer.Option(
            "--watch-every",
            min=1,
            help="Show a waveform watch window using every Nth captured event as a low-rate sample.",
        ),
    ] = None,
    progress_every: Annotated[
        int | None,
        typer.Option(
            "--progress-every",
            min=1,
            help="Print one live progress line every N captured events.",
        ),
    ] = None,
    profile: ProfileOption = Path("profiles/example.yaml"),
) -> None:
    """Capture raw TCP_SENT packets from one device."""
    profile_data = ProfileService().load_profile(profile)
    resolved = _resolve_single_acquire_options(
        defaults=profile_data.defaults,
        events=events,
        timeout_s=timeout_s,
        output_dir=output_dir,
        decode_json=decode_json,
        decoded_output_dir=decoded_output_dir,
        watch_every=watch_every,
        progress_every=progress_every,
    )
    service = AcquireService()
    last_printed_events = 0

    def on_progress(progress: SingleAcquireProgress) -> None:
        nonlocal last_printed_events
        should_print = (
            progress.captured_events == 0
            or progress.captured_events == progress.requested_events
            or progress.captured_events - last_printed_events >= resolved["progress_every"]
        )
        if not should_print:
            return
        output_dir = str(progress.output_dir) if progress.output_dir is not None else "pending"
        hit_mask = (
            f"0x{progress.hit_mask:04X}" if progress.hit_mask is not None else "pending"
        )
        packet_bytes = (
            str(progress.packet_bytes) if progress.packet_bytes is not None else "pending"
        )
        status_line = (
            f"{device} "
            f"events={progress.captured_events}/{progress.requested_events} "
            f"rate={progress.event_rate_hz:.2f}Hz "
            f"hit_mask={hit_mask} "
            f"bytes={packet_bytes} "
            f"out={output_dir}"
        )
        typer.echo(status_line)
        last_printed_events = progress.captured_events

    on_progress(
        SingleAcquireProgress(
            captured_events=0,
            requested_events=resolved["events"],
            packet_bytes=None,
            hit_mask=None,
            output_dir=None,
            event_rate_hz=0.0,
        )
    )
    result = service.capture_single(
        device_name=device,
        profile_path=profile,
        events=resolved["events"],
        timeout_s=resolved["timeout_s"],
        output_base_dir=resolved["output_dir"],
        decode_json=resolved["decode_json"],
        decoded_output_dir=resolved["decoded_output_dir"],
        watch_every=resolved["watch_every"],
        progress_callback=on_progress,
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


def _resolve_single_acquire_options(
    *,
    defaults: dict[str, object],
    events: int | None,
    timeout_s: float | None,
    output_dir: Path | None,
    decode_json: bool | None,
    decoded_output_dir: Path | None,
    watch_every: int | None,
    progress_every: int | None,
) -> dict[str, object]:
    acquire_defaults = defaults.get("acquire_single")
    if not isinstance(acquire_defaults, dict):
        acquire_defaults = {}

    def _path_from_default(key: str) -> Path | None:
        value = acquire_defaults.get(key)
        if value in (None, ""):
            return None
        return Path(str(value))

    return {
        "events": events if events is not None else int(acquire_defaults.get("events", 1000)),
        "timeout_s": (
            timeout_s if timeout_s is not None else float(acquire_defaults.get("timeout_s", 10.0))
        ),
        "output_dir": output_dir if output_dir is not None else _path_from_default("output_dir"),
        "decode_json": (
            decode_json if decode_json is not None else bool(acquire_defaults.get("decode_json", False))
        ),
        "decoded_output_dir": (
            decoded_output_dir
            if decoded_output_dir is not None
            else _path_from_default("decoded_output_dir")
        ),
        "watch_every": (
            watch_every
            if watch_every is not None
            else (
                int(acquire_defaults["watch_every"])
                if acquire_defaults.get("watch_every") is not None
                else None
            )
        ),
        "progress_every": (
            progress_every
            if progress_every is not None
            else int(acquire_defaults.get("progress_every", 50))
        ),
    }
