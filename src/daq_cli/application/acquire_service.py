from dataclasses import dataclass
from pathlib import Path

from daq_cli.application.profile_service import ProfileService
from daq_cli.domain.device import DeviceConfig
from daq_cli.domain.group import GroupConfig
from daq_cli.infrastructure.adapters.legacy_capture_runner import (
    LegacySingleCaptureRunner,
)
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
    tcp_timeout_s: float
    log_output: str


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
        runner = LegacySingleCaptureRunner(profile.legacy.project_root)
        raw_result = runner.capture_single(
            device=device,
            output_base_dir=base_dir,
            events=events,
            timeout_s=timeout_s,
        )
        return SingleAcquireResult(
            device=device,
            source_profile=profile.path,
            output_base_dir=base_dir,
            run_output_dir=raw_result.run_output_dir,
            requested_events=events,
            captured_events=raw_result.captured_events,
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
