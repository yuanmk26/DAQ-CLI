from dataclasses import dataclass
from pathlib import Path

from daq_cli.application.config_models import BoardConfigOptions
from daq_cli.application.profile_service import ProfileService
from daq_cli.domain.device import DeviceConfig
from daq_cli.infrastructure.adapters.legacy_board_adapter import LegacyBoardAdapter


@dataclass(slots=True)
class BoardInfoResult:
    device: DeviceConfig
    source_profile: Path
    legacy_project_root: Path | None


@dataclass(slots=True)
class BoardConfigResult:
    device: DeviceConfig
    source_profile: Path
    success: bool
    send_start_delay_us: float
    adc_enabled: bool
    clock_enabled: bool
    trigger_enabled: bool
    tcp_mode2_enabled: bool
    trigger_thresholds: tuple[int, int, int, int]
    trigger_mode: int
    trigger_position: int
    timestamp_clean_enabled: bool
    ext_trigger_enabled: bool
    log_output: str


class BoardService:
    """Board-oriented business workflows."""

    def __init__(self, profile_service: ProfileService | None = None) -> None:
        self._profile_service = profile_service or ProfileService()

    def get_board_info(
        self, device_name: str, profile_path: Path | str
    ) -> BoardInfoResult:
        resolved_profile_path = Path(profile_path)
        profile = self._profile_service.load_profile(resolved_profile_path)
        try:
            device = profile.devices[device_name]
        except KeyError as exc:
            available = ", ".join(sorted(profile.devices)) or "<none>"
            raise ValueError(
                f"Unknown device '{device_name}'. Available devices: {available}"
            ) from exc

        return BoardInfoResult(
            device=device,
            source_profile=profile.path,
            legacy_project_root=profile.legacy.project_root,
        )

    def configure_board(
        self,
        device_name: str,
        profile_path: Path | str,
        send_start_delay_us: float = 0.0,
        options: BoardConfigOptions | None = None,
    ) -> BoardConfigResult:
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

        options = options or BoardConfigOptions()
        adapter = LegacyBoardAdapter(profile.legacy.project_root)
        raw_result = adapter.configure_board(
            device=device,
            send_start_delay_us=send_start_delay_us,
            options=options,
        )
        return BoardConfigResult(
            device=device,
            source_profile=profile.path,
            success=raw_result.success,
            send_start_delay_us=send_start_delay_us,
            adc_enabled=options.adc_enabled,
            clock_enabled=options.clock_enabled,
            trigger_enabled=options.trigger_enabled,
            tcp_mode2_enabled=options.tcp_mode2_enabled,
            trigger_thresholds=options.trigger_thresholds,
            trigger_mode=options.trigger_mode,
            trigger_position=options.trigger_position,
            timestamp_clean_enabled=options.timestamp_clean_enabled,
            ext_trigger_enabled=options.ext_trigger_enabled,
            log_output=raw_result.log_output,
        )
