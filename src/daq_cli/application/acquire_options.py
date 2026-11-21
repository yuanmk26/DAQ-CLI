from pathlib import Path
from typing import TypedDict

from daq_cli.application.output_config import (
    AcquireOutputsConfig,
    OutputTargetConfig,
    TextOutputConfig,
)


class SingleAcquireOptions(TypedDict):
    events: int
    timeout_s: float
    output_dir: Path | None
    outputs: AcquireOutputsConfig
    watch_every: int | None
    progress_every: int
    storage_mode: str
    rate_interval_s: float


class MultiAcquireOptions(TypedDict):
    output_dir: Path | None
    outputs: AcquireOutputsConfig
    aggregation_key: str
    timestamp_match_window_ticks: int
    event_timeout_ms: int
    tcp_timeout_s: float
    allow_start_without_ack: bool
    watch_waveforms: bool
    watch_every: int
    stop_on_watch_close: bool


def resolve_single_acquire_options(
    *,
    defaults: dict[str, object],
    events: int | None = None,
    timeout_s: float | None = None,
    output_dir: Path | None = None,
    watch_every: int | None = None,
    progress_every: int | None = None,
    storage: str | None = None,
    rate_interval: float | None = None,
) -> SingleAcquireOptions:
    acquire_defaults = defaults.get("acquire_single")
    if not isinstance(acquire_defaults, dict):
        acquire_defaults = {}

    outputs = AcquireOutputsConfig(
        raw=OutputTargetConfig(enabled=True),
        json=OutputTargetConfig(enabled=False),
        text=TextOutputConfig(enabled=False),
        log=OutputTargetConfig(enabled=True),
    )
    storage_mode = str(storage if storage is not None else acquire_defaults.get("storage_mode", "aggregate")).lower()
    if storage is None and storage_mode == "legacy":
        storage_mode = "aggregate"
    if storage_mode not in {"aggregate", "rate"}:
        raise ValueError("storage must be one of: aggregate, rate")
    return {
        "events": events if events is not None else int(acquire_defaults.get("events", 1000)),
        "timeout_s": (
            timeout_s if timeout_s is not None else float(acquire_defaults.get("timeout_s", 10.0))
        ),
        "output_dir": output_dir if output_dir is not None else _path_from_value(acquire_defaults.get("output_dir")),
        "outputs": outputs,
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
        "storage_mode": storage_mode,
        "rate_interval_s": max(
            0.1,
            float(
                rate_interval
                if rate_interval is not None
                else acquire_defaults.get("rate_interval_s", 1.0)
            ),
        ),
    }


def resolve_multi_acquire_options(
    *,
    defaults: dict[str, object],
    output_dir: Path | None = None,
    aggregation_key: str | None = None,
    timestamp_match_window_ticks: int | None = None,
    event_timeout_ms: int | None = None,
    tcp_timeout_s: float | None = None,
    allow_start_without_ack: bool | None = None,
    watch_waveforms: bool | None = None,
    watch_every: int | None = None,
    stop_on_watch_close: bool | None = None,
) -> MultiAcquireOptions:
    acquire_defaults = defaults.get("acquire_multi")
    if not isinstance(acquire_defaults, dict):
        acquire_defaults = {}

    outputs = resolve_outputs_config(
        acquire_defaults=acquire_defaults,
        default_log_enabled=True,
    )
    key = str(aggregation_key or acquire_defaults.get("aggregation_key", "timestamp")).lower()
    if key not in {"timestamp", "event_count"}:
        raise ValueError("aggregation key must be 'timestamp' or 'event_count'")
    return {
        "output_dir": output_dir if output_dir is not None else _path_from_value(acquire_defaults.get("output_dir")),
        "aggregation_key": key,
        "timestamp_match_window_ticks": (
            timestamp_match_window_ticks
            if timestamp_match_window_ticks is not None
            else int(acquire_defaults.get("timestamp_match_window_ticks", 10))
        ),
        "event_timeout_ms": (
            event_timeout_ms
            if event_timeout_ms is not None
            else int(acquire_defaults.get("event_timeout_ms", 50))
        ),
        "tcp_timeout_s": (
            tcp_timeout_s
            if tcp_timeout_s is not None
            else float(acquire_defaults.get("tcp_timeout_s", 1.0))
        ),
        "allow_start_without_ack": (
            allow_start_without_ack
            if allow_start_without_ack is not None
            else bool(acquire_defaults.get("allow_start_without_ack", False))
        ),
        "outputs": outputs,
        "watch_waveforms": (
            watch_waveforms
            if watch_waveforms is not None
            else bool(acquire_defaults.get("watch_waveforms", False))
        ),
        "watch_every": (
            watch_every
            if watch_every is not None
            else (
                int(acquire_defaults["watch_every"])
                if acquire_defaults.get("watch_every") is not None
                else 100
            )
        ),
        "stop_on_watch_close": (
            stop_on_watch_close
            if stop_on_watch_close is not None
            else bool(acquire_defaults.get("stop_on_watch_close", True))
        ),
    }


def resolve_outputs_config(
    *,
    acquire_defaults: dict[str, object],
    default_log_enabled: bool,
) -> AcquireOutputsConfig:
    outputs_defaults = acquire_defaults.get("outputs")
    if not isinstance(outputs_defaults, dict):
        outputs_defaults = {}
    legacy_text_defaults = acquire_defaults.get("text_output")
    if not isinstance(legacy_text_defaults, dict):
        legacy_text_defaults = {}

    raw_defaults = outputs_defaults.get("raw")
    if not isinstance(raw_defaults, dict):
        raw_defaults = {}
    text_defaults = outputs_defaults.get("text")
    if not isinstance(text_defaults, dict):
        text_defaults = {}
    log_defaults = outputs_defaults.get("log")
    if not isinstance(log_defaults, dict):
        log_defaults = {}

    text_enabled = bool(
        text_defaults.get("enabled", legacy_text_defaults.get("enabled", False))
    )
    text_dir = _path_from_value(
        text_defaults.get("dir", legacy_text_defaults.get("output_dir"))
    )
    text_max_events_per_file = int(
        text_defaults.get(
            "max_events_per_file",
            legacy_text_defaults.get("max_events_per_file", 100),
        )
    )
    text_waveform_layout = str(
        text_defaults.get(
            "waveform_layout",
            legacy_text_defaults.get("waveform_layout", "channel_blocks"),
        )
    )

    return AcquireOutputsConfig(
        raw=OutputTargetConfig(
            enabled=True,
            dir=_path_from_value(raw_defaults.get("dir")),
        ),
        json=OutputTargetConfig(enabled=False),
        text=TextOutputConfig(
            enabled=text_enabled,
            dir=text_dir,
            max_events_per_file=text_max_events_per_file,
            waveform_layout=text_waveform_layout,
        ),
        log=OutputTargetConfig(
            enabled=bool(log_defaults.get("enabled", default_log_enabled)),
            dir=_path_from_value(log_defaults.get("dir")),
        ),
    )


def _path_from_value(value: object) -> Path | None:
    if value in (None, ""):
        return None
    return Path(str(value))


def default_output_base_dir(profile) -> Path:
    """Resolve the profile's base output directory (same rule as the service)."""
    configured = profile.defaults.get("output_dir", "out")
    base = Path(str(configured))
    if not base.is_absolute():
        profile_dir = profile.path.parent
        if profile_dir.name.lower() == "profiles":
            base = profile_dir.parent / base
        else:
            base = profile_dir / base
    return base
