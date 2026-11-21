from pathlib import Path
from typing import Annotated

import typer

from daq_cli.application.acquire_service import AcquireService, SingleAcquireProgress
from daq_cli.application.acquire_options import (
    resolve_multi_acquire_options,
    resolve_single_acquire_options,
)
from daq_cli.application.profile_service import ProfileService
from daq_cli.cli.common import RequiredProfileOption
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
    storage: Annotated[
        str | None,
        typer.Option(
            "--storage",
            help=(
                "Single-board storage mode: aggregate (complete_events.dat, "
                "default), rate (rate.csv/monitor.jsonl only), or legacy "
                "(per-event raw/JSON/TXT files)."
            ),
        ),
    ] = None,
    rate_interval: Annotated[
        float | None,
        typer.Option(
            "--rate-interval",
            min=0.1,
            help="Rate-log sample interval in seconds (aggregate/rate modes).",
        ),
    ] = None,
    profile: RequiredProfileOption = ...,
) -> None:
    """Capture raw TCP_SENT packets from one device."""
    profile_data = ProfileService().load_profile(profile)
    try:
        resolved = resolve_single_acquire_options(
            defaults=profile_data.defaults,
            events=events,
            timeout_s=timeout_s,
            output_dir=output_dir,
            decode_json=decode_json,
            decoded_output_dir=decoded_output_dir,
            watch_every=watch_every,
            progress_every=progress_every,
            storage=storage,
            rate_interval=rate_interval,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    storage_mode = resolved["storage_mode"]
    if storage_mode != "legacy" and (
        resolved["outputs"].json.enabled or resolved["outputs"].text.enabled
    ):
        typer.echo(
            "Warning: JSON/TXT outputs are only available in legacy storage "
            "mode; they are ignored in aggregate/rate mode.",
            err=True,
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
        outputs=resolved["outputs"],
        watch_every=resolved["watch_every"],
        progress_callback=on_progress,
        storage_mode=storage_mode,
        rate_interval_s=float(resolved["rate_interval_s"]),
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
        str | None,
        typer.Option(
            "--aggregation-key",
            help="Event aggregation key: timestamp or event_count.",
            case_sensitive=False,
        ),
    ] = None,
    timestamp_match_window_ticks: Annotated[
        int | None,
        typer.Option(
            "--timestamp-match-window",
            min=0,
            help="Allowed timestamp skew in ticks when aggregation_key=timestamp.",
        ),
    ] = None,
    event_timeout_ms: Annotated[
        int | None,
        typer.Option(
            "--event-timeout-ms",
            min=1,
            help="Flush incomplete events after this timeout in milliseconds.",
        ),
    ] = None,
    tcp_timeout_s: Annotated[
        float | None,
        typer.Option(
            "--timeout",
            min=0.1,
            help="TCP socket timeout in seconds for each board receiver.",
        ),
    ] = None,
    allow_start_without_ack: Annotated[
        bool | None,
        typer.Option(
            "--allow-start-without-ack/--require-ack",
            help="Continue even if TCM alignment does not report all ACK bits.",
        ),
    ] = None,
    decode_json: Annotated[
        bool | None,
        typer.Option(
            "--decode-json/--raw-only",
            help="Also decode aggregated multi-board events to JSON after capture.",
        ),
    ] = None,
    watch_waveforms: Annotated[
        bool | None,
        typer.Option(
            "--watch-waveforms/--no-watch-waveforms",
            help="Show a sampled waveform monitor during multi-board capture when boards are in waveform send modes.",
        ),
    ] = None,
    watch_every: Annotated[
        int | None,
        typer.Option(
            "--watch-every",
            min=1,
            help="Sample one waveform frame every N frames per board for the multi-board watcher.",
        ),
    ] = None,
    stop_on_watch_close: Annotated[
        bool | None,
        typer.Option(
            "--stop-on-watch-close/--keep-running-after-watch-close",
            help="When waveform watching is enabled, closing the watch window also stops acquisition by default.",
        ),
    ] = None,
    profile: RequiredProfileOption = ...,
) -> None:
    """Run multi-board acquisition for one logical group."""
    profile_data = ProfileService().load_profile(profile)
    try:
        resolved = resolve_multi_acquire_options(
            defaults=profile_data.defaults,
            output_dir=output_dir,
            aggregation_key=aggregation_key,
            timestamp_match_window_ticks=timestamp_match_window_ticks,
            event_timeout_ms=event_timeout_ms,
            tcp_timeout_s=tcp_timeout_s,
            allow_start_without_ack=allow_start_without_ack,
            decode_json=decode_json,
            watch_waveforms=watch_waveforms,
            watch_every=watch_every,
            stop_on_watch_close=stop_on_watch_close,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    service = AcquireService()
    try:
        result = service.capture_multi(
            group_name=group,
            profile_path=profile,
            output_base_dir=resolved["output_dir"],
            aggregation_key=resolved["aggregation_key"],
            timestamp_match_window_ticks=resolved["timestamp_match_window_ticks"],
            event_timeout_ms=resolved["event_timeout_ms"],
            tcp_timeout_s=resolved["tcp_timeout_s"],
            allow_start_without_ack=resolved["allow_start_without_ack"],
            outputs=resolved["outputs"],
            watch_waveforms=resolved["watch_waveforms"],
            watch_every=resolved["watch_every"],
            stop_capture_on_watch_close=resolved["stop_on_watch_close"],
        )
    except Exception as exc:
        typer.echo(f"Multi-board acquisition failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    print_multi_acquire_result(result)
