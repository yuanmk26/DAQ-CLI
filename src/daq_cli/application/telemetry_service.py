from dataclasses import dataclass
from pathlib import Path

from daq_cli.application.profile_service import ProfileService
from daq_cli.domain.device import DeviceConfig
from daq_cli.infrastructure.adapters.legacy_board_adapter import LegacyBoardAdapter


@dataclass(slots=True)
class SysmonSnapshot:
    temperature_c: float
    vccint_v: float
    vccaux_v: float
    vccbram_v: float


@dataclass(slots=True)
class BoardSysmonResult:
    device: DeviceConfig
    source_profile: Path
    snapshot: SysmonSnapshot


class TelemetryService:
    """Board telemetry workflows."""

    def __init__(self, profile_service: ProfileService | None = None) -> None:
        self._profile_service = profile_service or ProfileService()

    def get_board_sysmon(
        self, device_name: str, profile_path: Path | str
    ) -> BoardSysmonResult:
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

        adapter = LegacyBoardAdapter(profile.legacy.project_root)
        snapshot = adapter.read_sysmon(device)
        return BoardSysmonResult(
            device=device,
            source_profile=profile.path,
            snapshot=SysmonSnapshot(
                temperature_c=snapshot.temperature_c,
                vccint_v=snapshot.vccint_v,
                vccaux_v=snapshot.vccaux_v,
                vccbram_v=snapshot.vccbram_v,
            ),
        )
