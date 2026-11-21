import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from daq_cli.application.output_config import (
    AcquireOutputsConfig,
    OutputTargetConfig,
    TextOutputConfig,
)
from daq_cli.application.acquire_options import default_output_base_dir
from daq_cli.application.profile_service import ProfileService
from daq_cli.domain.device import DeviceConfig
from daq_cli.domain.group import GroupConfig
from daq_cli.infrastructure.adapters.legacy_capture_runner import (
    LegacySingleCaptureProgress,
    LegacySingleCaptureRunner,
)
from daq_cli.infrastructure.adapters.legacy_board_adapter import LegacyBoardAdapter
from daq_cli.infrastructure.adapters.multi_capture_runner import (
    MultiCaptureConfig,
    MultiCaptureRunner,
)

# Opt-in escape hatch during the native migration: set DAQ_MULTI_VENDOR=1 to run
# multi-board capture through the legacy wrapper + vendored script instead of the
# native runner (useful for A/B comparison on real hardware).
_VENDOR_ENV_FLAG = "DAQ_MULTI_VENDOR"


def _use_vendor_multi_runner() -> bool:
    return os.environ.get(_VENDOR_ENV_FLAG, "").strip().lower() in {"1", "true", "yes"}


def _multi_runner_classes():
    """Pick the multi-board runner/config pair (native by default).

    The legacy pair is imported lazily so the vendored script is only touched
    when explicitly requested via ``DAQ_MULTI_VENDOR=1``.
    """
    if _use_vendor_multi_runner():
        from daq_cli.infrastructure.adapters.legacy_multi_capture_runner import (
            LegacyMultiCaptureConfig,
            LegacyMultiCaptureRunner,
        )

        return LegacyMultiCaptureRunner, LegacyMultiCaptureConfig
    return MultiCaptureRunner, MultiCaptureConfig


@dataclass(slots=True)
class SingleAcquireResult:
    device: DeviceConfig
    source_profile: Path
    output_base_dir: Path
    run_output_dir: Path | None
    requested_events: int | None
    captured_events: int | None
    send_mode: int
    decode_enabled: bool
    decoded_output_dir: Path | None
    decoded_events: int | None
    decode_errors: int
    watch_enabled: bool
    watch_every: int | None
    watched_frames: int
    tcp_timeout_s: float
    log_output: str
    raw_output_dir: Path | None = None
    json_output_enabled: bool = False
    json_output_dir: Path | None = None
    log_output_path: Path | None = None
    text_output_enabled: bool = False
    text_output_dir: Path | None = None
    text_output_events: int = 0
    text_output_files: int = 0
    storage_mode: str = "legacy"
    rate_interval_s: float = 1.0
    rate_csv_path: Path | None = None
    run_meta_path: Path | None = None
    aggregate_output_path: Path | None = None
    aggregate_index_path: Path | None = None
    monitor_jsonl_path: Path | None = None
    duration_reached: bool = False


@dataclass(slots=True)
class SingleAcquireProgress:
    captured_events: int
    requested_events: int | None
    packet_bytes: int | None
    hit_mask: int | None
    output_dir: Path | None
    event_rate_hz: float


@dataclass(slots=True)
class MultiAcquireResult:
    group: GroupConfig
    devices: list[DeviceConfig]
    source_profile: Path
    output_base_dir: Path
    run_output_dir: Path | None
    aggregation_key: str
    timestamp_match_window_ticks: int
    tcp_timeout_s: float
    allow_start_without_ack: bool
    decode_enabled: bool
    decoded_output_dir: Path | None
    decoded_complete_events: int
    decoded_partial_events: int
    decode_errors: int
    watch_waveforms: bool
    watch_every: int | None
    watched_frames: int
    stop_capture_on_watch_close: bool
    config_path: Path
    meta_path: Path | None
    log_path: Path | None
    status: str | None
    raw_output_dir: Path | None = None
    json_output_enabled: bool = False
    json_output_dir: Path | None = None
    log_output_dir: Path | None = None
    text_output_enabled: bool = False
    text_output_dir: Path | None = None
    text_output_complete_events: int = 0
    text_output_partial_events: int = 0
    text_output_files: int = 0


class AcquireService:
    """Acquisition-oriented business workflows."""

    def __init__(self, profile_service: ProfileService | None = None) -> None:
        self._profile_service = profile_service or ProfileService()

    def capture_single(
        self,
        device_name: str,
        profile_path: Path | str,
        events: int | None,
        timeout_s: float,
        output_base_dir: Path | None = None,
        outputs: AcquireOutputsConfig | None = None,
        decode_json: bool = False,
        decoded_output_dir: Path | None = None,
        text_output_enabled: bool = False,
        text_output_dir: Path | None = None,
        text_max_events_per_file: int = 100,
        text_waveform_layout: str = "channel_blocks",
        watch_every: int | None = None,
        progress_callback: Callable[[SingleAcquireProgress], None] | None = None,
        watch_frame_callback: Callable[[bytes], None] | None = None,
        run_name_prefix: str | None = None,
        cancel_event: threading.Event | None = None,
        storage_mode: str = "legacy",
        rate_interval_s: float = 1.0,
        duration_s: float | None = None,
    ) -> SingleAcquireResult:
        profile = self._profile_service.load_profile(profile_path)
        try:
            device = profile.devices[device_name]
        except KeyError as exc:
            available = ", ".join(sorted(profile.devices)) or "<none>"
            raise ValueError(
                f"Unknown device '{device_name}'. Available devices: {available}"
            ) from exc

        base_dir = output_base_dir or (
            default_output_base_dir(profile) / "single"
        )
        resolved_outputs = outputs or AcquireOutputsConfig(
            raw=OutputTargetConfig(enabled=True),
            json=OutputTargetConfig(enabled=decode_json, dir=decoded_output_dir),
            text=TextOutputConfig(
                enabled=text_output_enabled,
                dir=text_output_dir,
                max_events_per_file=text_max_events_per_file,
                waveform_layout=text_waveform_layout,
            ),
            log=OutputTargetConfig(enabled=False),
        )
        # When a caller supplies an outputs config (e.g. the GUI), its
        # json/text switches are authoritative: the legacy runner keys the
        # decode/text outputs off these standalone params.
        if outputs is not None:
            decode_json = resolved_outputs.json.enabled
            decoded_output_dir = decoded_output_dir or resolved_outputs.json.dir
            text_output_enabled = resolved_outputs.text.enabled
            text_output_dir = text_output_dir or resolved_outputs.text.dir
            text_max_events_per_file = resolved_outputs.text.max_events_per_file
            text_waveform_layout = resolved_outputs.text.waveform_layout
        board_adapter = LegacyBoardAdapter()
        tcp_config = board_adapter.read_tcp_mode2_config(device)
        runner = LegacySingleCaptureRunner()
        capture_started_at: float | None = None
        latest_output_dir: Path | None = None
        latest_captured_events = 0
        latest_packet_bytes: int | None = None
        latest_hit_mask: int | None = None

        def on_progress(raw_progress: LegacySingleCaptureProgress) -> None:
            nonlocal capture_started_at, latest_output_dir
            nonlocal latest_captured_events, latest_packet_bytes, latest_hit_mask
            if raw_progress.output_dir is not None:
                latest_output_dir = raw_progress.output_dir
            if raw_progress.captured_events > 0:
                latest_captured_events = raw_progress.captured_events
            if raw_progress.packet_bytes is not None:
                latest_packet_bytes = raw_progress.packet_bytes
            if raw_progress.hit_mask is not None:
                latest_hit_mask = raw_progress.hit_mask
            if progress_callback is None:
                return
            if latest_captured_events > 0 and capture_started_at is None:
                capture_started_at = time.perf_counter()
            elapsed_s = (
                max(time.perf_counter() - capture_started_at, 1e-9)
                if capture_started_at is not None
                else 0.0
            )
            event_rate_hz = (
                latest_captured_events / elapsed_s
                if latest_captured_events > 0 and elapsed_s > 0
                else 0.0
            )
            progress_callback(
                SingleAcquireProgress(
                    captured_events=latest_captured_events,
                    requested_events=events,
                    packet_bytes=latest_packet_bytes,
                    hit_mask=latest_hit_mask,
                    output_dir=latest_output_dir,
                    event_rate_hz=event_rate_hz,
                )
            )

        raw_result = runner.capture_single(
            device=device,
            **({"duration_s": duration_s} if duration_s is not None else {}),
            output_base_dir=base_dir,
            events=events,
            timeout_s=timeout_s,
            send_mode=tcp_config.send_mode,
            outputs=resolved_outputs,
            decode_json=decode_json,
            decoded_output_dir=decoded_output_dir,
            text_output_enabled=text_output_enabled,
            text_output_dir=text_output_dir,
            text_max_events_per_file=text_max_events_per_file,
            text_waveform_layout=text_waveform_layout,
            watch_every=watch_every,
            progress_callback=on_progress,
            watch_frame_callback=watch_frame_callback,
            run_name_prefix=run_name_prefix,
            cancel_event=cancel_event,
            storage_mode=storage_mode,
            rate_interval_s=rate_interval_s,
        )
        return SingleAcquireResult(
            duration_reached=getattr(raw_result, "duration_reached", False),
            device=device,
            source_profile=profile.path,
            output_base_dir=base_dir,
            run_output_dir=raw_result.run_output_dir,
            requested_events=events,
            captured_events=raw_result.captured_events,
            send_mode=raw_result.send_mode,
            decode_enabled=getattr(
                raw_result, "json_output_enabled", raw_result.decode_enabled
            ),
            decoded_output_dir=getattr(
                raw_result, "json_output_dir", raw_result.decoded_output_dir
            ),
            decoded_events=raw_result.decoded_events,
            decode_errors=raw_result.decode_errors,
            raw_output_dir=getattr(raw_result, "raw_output_dir", None),
            json_output_enabled=getattr(
                raw_result, "json_output_enabled", raw_result.decode_enabled
            ),
            json_output_dir=getattr(raw_result, "json_output_dir", raw_result.decoded_output_dir),
            log_output_path=getattr(raw_result, "log_output_path", None),
            watch_enabled=raw_result.watch_enabled,
            watch_every=raw_result.watch_every,
            watched_frames=raw_result.watched_frames,
            tcp_timeout_s=timeout_s,
            log_output=raw_result.log_output,
            text_output_enabled=getattr(raw_result, "text_output_enabled", False),
            text_output_dir=getattr(raw_result, "text_output_dir", None),
            text_output_events=getattr(raw_result, "text_output_events", 0),
            text_output_files=getattr(raw_result, "text_output_files", 0),
            storage_mode=getattr(raw_result, "storage_mode", storage_mode),
            rate_interval_s=getattr(
                raw_result, "rate_interval_s", rate_interval_s
            ),
            rate_csv_path=getattr(raw_result, "rate_csv_path", None),
            run_meta_path=getattr(raw_result, "run_meta_path", None),
            aggregate_output_path=getattr(
                raw_result, "aggregate_output_path", None
            ),
            aggregate_index_path=getattr(
                raw_result, "aggregate_index_path", None
            ),
            monitor_jsonl_path=getattr(raw_result, "monitor_jsonl_path", None),
        )

    def capture_multi(
        self,
        group_name: str,
        profile_path: Path | str,
        output_base_dir: Path | None = None,
        outputs: AcquireOutputsConfig | None = None,
        aggregation_key: str = "timestamp",
        timestamp_match_window_ticks: int = 10,
        event_timeout_ms: int = 50,
        tcp_timeout_s: float = 1.0,
        allow_start_without_ack: bool = False,
        decode_json: bool = False,
        text_output_enabled: bool = False,
        text_output_dir: Path | None = None,
        text_max_events_per_file: int = 100,
        text_waveform_layout: str = "channel_blocks",
        watch_waveforms: bool = False,
        watch_every: int | None = None,
        stop_capture_on_watch_close: bool = True,
        watch_update_callback: Callable[[object], None] | None = None,
        run_name_prefix: str | None = None,
        cancel_event: threading.Event | None = None,
        progress_callback: "Callable[[Path, dict], None] | None" = None,
    ) -> MultiAcquireResult:
        profile = self._profile_service.load_profile(profile_path)
        try:
            group = profile.groups[group_name]
        except KeyError as exc:
            available = ", ".join(sorted(profile.groups)) or "<none>"
            raise ValueError(
                f"Unknown group '{group_name}'. Available groups: {available}"
            ) from exc

        if group.tcm is None:
            raise ValueError(f"Group '{group_name}' does not define a TCM reference")

        tcm_config = profile.tcm.get(group.tcm)
        if tcm_config is None:
            raise ValueError(
                f"Group '{group_name}' references unknown TCM '{group.tcm}'"
            )

        devices = self._resolve_group_devices(profile.devices, group)
        base_dir = output_base_dir or (
            default_output_base_dir(profile) / "multi"
        )
        resolved_outputs = outputs or AcquireOutputsConfig(
            raw=OutputTargetConfig(enabled=True),
            json=OutputTargetConfig(enabled=decode_json),
            text=TextOutputConfig(
                enabled=text_output_enabled,
                dir=text_output_dir,
                max_events_per_file=text_max_events_per_file,
                waveform_layout=text_waveform_layout,
            ),
            log=OutputTargetConfig(enabled=True),
        )
        if outputs is not None:
            # Same as capture_single: an explicit outputs config (GUI) owns
            # the json/text switches; the runner reads these standalone
            # params, so mirror the config into them.
            decode_json = resolved_outputs.json.enabled
            text_output_enabled = resolved_outputs.text.enabled
            text_output_dir = text_output_dir or resolved_outputs.text.dir
            text_max_events_per_file = resolved_outputs.text.max_events_per_file
            text_waveform_layout = resolved_outputs.text.waveform_layout
        if watch_waveforms:
            board_adapter = LegacyBoardAdapter()
            unsupported = []
            for device in devices:
                send_mode = board_adapter.read_tcp_mode2_config(device).send_mode
                if send_mode not in {1, 3}:
                    unsupported.append(f"{device.name}:{send_mode}")
            if unsupported:
                raise ValueError(
                    "multi waveform watch only supports send_mode 1 or 3; "
                    f"unsupported boards: {', '.join(unsupported)}"
                )
        runner_cls, config_cls = _multi_runner_classes()
        runner = runner_cls()
        raw_result = runner.capture_multi(
            config_cls(
                run_name_prefix=run_name_prefix or group.name,
                output_base_dir=base_dir,
                tcm_ip=tcm_config.ip,
                tcm_rbcp_port=tcm_config.rbcp_port,
                adc_length=int(profile.defaults.get("adc_length", 256)),
                aggregation_key=aggregation_key,
                timestamp_match_window_ticks=timestamp_match_window_ticks,
                event_timeout_ms=event_timeout_ms,
                tcp_timeout_s=tcp_timeout_s,
                allow_start_without_ack=allow_start_without_ack,
                boards=devices,
                outputs=resolved_outputs,
                decode_json=decode_json,
                text_output_enabled=text_output_enabled,
                text_output_dir=text_output_dir,
                text_max_events_per_file=text_max_events_per_file,
                text_waveform_layout=text_waveform_layout,
                watch_waveforms=watch_waveforms,
                watch_every=watch_every,
                stop_capture_on_watch_close=stop_capture_on_watch_close,
            ),
            **({"progress_callback": progress_callback} if progress_callback else {}),
            watch_update_callback=watch_update_callback,
            cancel_event=cancel_event,
        )
        return MultiAcquireResult(
            group=group,
            devices=devices,
            source_profile=profile.path,
            output_base_dir=base_dir,
            run_output_dir=raw_result.run_output_dir,
            aggregation_key=aggregation_key,
            timestamp_match_window_ticks=timestamp_match_window_ticks,
            tcp_timeout_s=tcp_timeout_s,
            allow_start_without_ack=allow_start_without_ack,
            decode_enabled=getattr(
                raw_result, "json_output_enabled", raw_result.decode_enabled
            ),
            decoded_output_dir=getattr(
                raw_result, "json_output_dir", raw_result.decoded_output_dir
            ),
            decoded_complete_events=raw_result.decoded_complete_events,
            decoded_partial_events=raw_result.decoded_partial_events,
            decode_errors=raw_result.decode_errors,
            raw_output_dir=getattr(raw_result, "raw_output_dir", None),
            json_output_enabled=getattr(
                raw_result, "json_output_enabled", raw_result.decode_enabled
            ),
            json_output_dir=getattr(raw_result, "json_output_dir", raw_result.decoded_output_dir),
            log_output_dir=getattr(raw_result, "log_output_dir", None),
            watch_waveforms=raw_result.watch_waveforms,
            watch_every=raw_result.watch_every,
            watched_frames=raw_result.watched_frames,
            stop_capture_on_watch_close=raw_result.stop_capture_on_watch_close,
            config_path=raw_result.config_path,
            meta_path=raw_result.meta_path,
            log_path=raw_result.log_path,
            status=raw_result.status,
            text_output_enabled=getattr(raw_result, "text_output_enabled", False),
            text_output_dir=getattr(raw_result, "text_output_dir", None),
            text_output_complete_events=getattr(
                raw_result, "text_output_complete_events", 0
            ),
            text_output_partial_events=getattr(
                raw_result, "text_output_partial_events", 0
            ),
            text_output_files=getattr(raw_result, "text_output_files", 0),
        )

    def _resolve_group_devices(
        self,
        devices_by_name: dict[str, DeviceConfig],
        group: GroupConfig,
    ) -> list[DeviceConfig]:
        resolved = []
        missing = []
        for device_name in group.devices:
            device = devices_by_name.get(device_name)
            if device is None:
                missing.append(device_name)
                continue
            resolved.append(device)
        if missing:
            raise ValueError(
                f"Group '{group.name}' references unknown devices: {', '.join(missing)}"
            )
        if not resolved:
            raise ValueError(f"Group '{group.name}' does not contain any devices")
        return resolved
