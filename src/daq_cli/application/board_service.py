from dataclasses import dataclass
from pathlib import Path

from daq_cli.application.profile_service import ProfileService
from daq_cli.domain.device import DeviceConfig


@dataclass(slots=True)
class BoardInfoResult:
    device: DeviceConfig
    source_profile: Path
    legacy_project_root: Path | None


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
