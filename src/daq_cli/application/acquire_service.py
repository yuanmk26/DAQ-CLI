from dataclasses import dataclass
from pathlib import Path

from daq_cli.application.profile_service import ProfileService
from daq_cli.domain.device import DeviceConfig
from daq_cli.infrastructure.adapters.legacy_capture_runner import (
    LegacySingleCaptureRunner,
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

        base_dir = output_base_dir or self._default_output_base_dir(profile.path, profile)
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

    def _default_output_base_dir(self, profile_path: Path, profile) -> Path:
        configured = profile.defaults.get("output_dir", "out")
        base = Path(str(configured))
        if not base.is_absolute():
            base = profile_path.parent.parent / base
        return base / "single"
