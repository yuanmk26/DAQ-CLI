import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from daq_cli.application.profile_service import ProfileService
from daq_cli.domain.device import DeviceConfig
from daq_cli.domain.group import GroupConfig
from daq_cli.infrastructure.adapters.legacy_capture_runner import (
    LegacySingleCaptureProgress,
    LegacySingleCaptureRunner,
)
from daq_cli.infrastructure.adapters.legacy_board_adapter import LegacyBoardAdapter
from daq_cli.infrastructure.adapters.legacy_multi_capture_runner import (
    LegacyMultiCaptureConfig,
    LegacyMultiCaptureRunner,
)


@dataclass(slots=True)
class SingleAcquireResult:
    device: DeviceConfig
    source_profile: Path
    output_base_dir: Path
    run_output_dir: Path | None
    requested_events: int
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


@dataclass(slots=True)
class SingleAcquireProgress:
    captured_events: int
    requested_events: int
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


class AcquireService:
    """Acquisition-oriented business workflows."""

    def __init__(self, profile_service: ProfileService | None = None) -> None:
        self._profile_service = profile_service or ProfileService()

    def capture_single(
        self,
        device_name: str,
        profile_path: Path | str,
        events: int,
        timeout_s: float,
        output_base_dir: Path | None = None,
        decode_json: bool = False,
        decoded_output_dir: Path | None = None,
        watch_every: int | None = None,
        progress_callback: Callable[[SingleAcquireProgress], None] | None = None,
    ) -> SingleAcquireResult:
        profile = self._profile_service.load_profile(profile_path)
        try:
            device = profile.devices[device_name]
        except KeyError as exc:
            available = ", ".join(sorted(profile.devices)) or "<none>"
            raise ValueError(
                f"Unknown device '{device_name}'. Available devices: {available}"
            ) from exc

        if profile.legacy.project_root is None:
            raise ValueError("The selected profile does not define legacy.project_root")

        base_dir = output_base_dir or (
            self._default_output_base_dir(profile.path, profile) / "single"
        )
        board_adapter = LegacyBoardAdapter(profile.legacy.project_root)
        tcp_config = board_adapter.read_tcp_mode2_config(device)
        runner = LegacySingleCaptureRunner(profile.legacy.project_root)
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
            output_base_dir=base_dir,
            events=events,
            timeout_s=timeout_s,
            send_mode=tcp_config.send_mode,
            decode_json=decode_json,
            decoded_output_dir=decoded_output_dir,
            watch_every=watch_every,
            progress_callback=on_progress,
        )
        return SingleAcquireResult(
            device=device,
            source_profile=profile.path,
            output_base_dir=base_dir,
            run_output_dir=raw_result.run_output_dir,
            requested_events=events,
            captured_events=raw_result.captured_events,
            send_mode=raw_result.send_mode,
            decode_enabled=raw_result.decode_enabled,
            decoded_output_dir=raw_result.decoded_output_dir,
            decoded_events=raw_result.decoded_events,
            decode_errors=raw_result.decode_errors,
            watch_enabled=raw_result.watch_enabled,
            watch_every=raw_result.watch_every,
            watched_frames=raw_result.watched_frames,
            tcp_timeout_s=timeout_s,
            log_output=raw_result.log_output,
        )

    def capture_multi(
        self,
        group_name: str,
        profile_path: Path | str,
        output_base_dir: Path | None = None,
        aggregation_key: str = "timestamp",
        timestamp_match_window_ticks: int = 10,
        event_timeout_ms: int = 50,
        tcp_timeout_s: float = 1.0,
        allow_start_without_ack: bool = False,
        decode_json: bool = False,
        watch_waveforms: bool = False,
        watch_every: int | None = None,
        stop_capture_on_watch_close: bool = True,
    ) -> MultiAcquireResult:
        profile = self._profile_service.load_profile(profile_path)
        try:
            group = profile.groups[group_name]
        except KeyError as exc:
            available = ", ".join(sorted(profile.groups)) or "<none>"
            raise ValueError(
                f"Unknown group '{group_name}'. Available groups: {available}"
            ) from exc

        if profile.legacy.project_root is None:
            raise ValueError("The selected profile does not define legacy.project_root")
        if group.tcm is None:
            raise ValueError(f"Group '{group_name}' does not define a TCM reference")

        tcm_config = profile.tcm.get(group.tcm)
        if not isinstance(tcm_config, dict):
            raise ValueError(
                f"Group '{group_name}' references unknown TCM '{group.tcm}'"
            )
        if tcm_config.get("ip") is None:
            raise ValueError(f"TCM '{group.tcm}' does not define an IP address")

        devices = self._resolve_group_devices(profile.devices, group)
        base_dir = output_base_dir or (
            self._default_output_base_dir(profile.path, profile) / "multi"
        )
        if watch_waveforms:
            board_adapter = LegacyBoardAdapter(profile.legacy.project_root)
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
        runner = LegacyMultiCaptureRunner(profile.legacy.project_root)
        raw_result = runner.capture_multi(
            LegacyMultiCaptureConfig(
                run_name_prefix=group.name,
                output_base_dir=base_dir,
                tcm_ip=str(tcm_config["ip"]),
                tcm_rbcp_port=int(tcm_config.get("rbcp_port", 4660)),
                adc_length=int(profile.defaults.get("adc_length", 64)),
                aggregation_key=aggregation_key,
                timestamp_match_window_ticks=timestamp_match_window_ticks,
                event_timeout_ms=event_timeout_ms,
                tcp_timeout_s=tcp_timeout_s,
                allow_start_without_ack=allow_start_without_ack,
                boards=devices,
                decode_json=decode_json,
                watch_waveforms=watch_waveforms,
                watch_every=watch_every,
                stop_capture_on_watch_close=stop_capture_on_watch_close,
            )
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
            decode_enabled=raw_result.decode_enabled,
            decoded_output_dir=raw_result.decoded_output_dir,
            decoded_complete_events=raw_result.decoded_complete_events,
            decoded_partial_events=raw_result.decoded_partial_events,
            decode_errors=raw_result.decode_errors,
            watch_waveforms=raw_result.watch_waveforms,
            watch_every=raw_result.watch_every,
            watched_frames=raw_result.watched_frames,
            stop_capture_on_watch_close=raw_result.stop_capture_on_watch_close,
            config_path=raw_result.config_path,
            meta_path=raw_result.meta_path,
            log_path=raw_result.log_path,
            status=raw_result.status,
        )

    def _default_output_base_dir(self, profile_path: Path, profile) -> Path:
        configured = profile.defaults.get("output_dir", "out")
        base = Path(str(configured))
        if not base.is_absolute():
            base = profile_path.parent.parent / base
        return base

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
