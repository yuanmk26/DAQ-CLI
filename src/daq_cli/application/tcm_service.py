from dataclasses import dataclass
from pathlib import Path

from daq_cli.application.profile_service import ProfileService
from daq_cli.domain.tcm import TcmConfig
from daq_cli.infrastructure.adapters.legacy_tcm_adapter import LegacyTcmAdapter


@dataclass(slots=True)
class TcmTriggerConfigReadResult:
    tcm: TcmConfig
    source_profile: Path
    enable: bool
    mask: int
    pulse_width: int
    debounce: int
    trig_sticky: bool
    pending: bool
    wide_pulse_active: bool
    last_trigger_channels: int


@dataclass(slots=True)
class TcmTriggerConfigWriteResult:
    tcm: TcmConfig
    source_profile: Path
    enable: bool
    mask: int
    pulse_width: int
    debounce: int


class TcmService:
    """TCM board trigger-link workflows."""

    def __init__(self, profile_service: ProfileService | None = None) -> None:
        self._profile_service = profile_service or ProfileService()

    def _resolve_tcm(
        self, tcm_name: str, profile_path: Path | str
    ) -> tuple[object, TcmConfig]:
        profile = self._profile_service.load_profile(profile_path)
        try:
            tcm = profile.tcm[tcm_name]
        except KeyError as exc:
            available = ", ".join(sorted(profile.tcm)) or "<none>"
            raise ValueError(
                f"Unknown TCM '{tcm_name}'. Available TCM entries: {available}"
            ) from exc
        return profile, tcm

    def _make_adapter(self, profile) -> LegacyTcmAdapter:
        return LegacyTcmAdapter()

    def read_trigger_config(
        self, tcm_name: str, profile_path: Path | str
    ) -> TcmTriggerConfigReadResult:
        profile, tcm = self._resolve_tcm(tcm_name, profile_path)
        adapter = self._make_adapter(profile)
        raw_result = adapter.read_trigger_config(tcm)
        return TcmTriggerConfigReadResult(
            tcm=tcm,
            source_profile=profile.path,
            enable=raw_result.enable,
            mask=raw_result.mask,
            pulse_width=raw_result.pulse_width,
            debounce=raw_result.debounce,
            trig_sticky=raw_result.trig_sticky,
            pending=raw_result.pending,
            wide_pulse_active=raw_result.wide_pulse_active,
            last_trigger_channels=raw_result.last_trigger_channels,
        )

    def configure_trigger(
        self,
        tcm_name: str,
        profile_path: Path | str,
        *,
        enable: bool,
        mask: int,
        pulse_width: int,
        debounce: int,
    ) -> TcmTriggerConfigWriteResult:
        """Write the TCM trigger-link configuration and verify by readback."""
        profile, tcm = self._resolve_tcm(tcm_name, profile_path)
        adapter = self._make_adapter(profile)
        adapter.write_trigger_config(
            tcm,
            enable=enable,
            mask=mask,
            pulse_width=pulse_width,
            debounce=debounce,
        )
        readback = adapter.read_trigger_config(tcm)
        if (
            readback.enable != enable
            or readback.mask != mask
            or readback.pulse_width != pulse_width
            or readback.debounce != debounce
        ):
            raise RuntimeError(
                "TCM trigger write verification failed: requested "
                f"enable={enable} mask=0x{mask:02X} width={pulse_width} "
                f"debounce={debounce}, read back enable={readback.enable} "
                f"mask=0x{readback.mask:02X} width={readback.pulse_width} "
                f"debounce={readback.debounce}."
            )
        return TcmTriggerConfigWriteResult(
            tcm=tcm,
            source_profile=profile.path,
            enable=readback.enable,
            mask=readback.mask,
            pulse_width=readback.pulse_width,
            debounce=readback.debounce,
        )

    def clear_trigger_sticky(
        self, tcm_name: str, profile_path: Path | str
    ) -> None:
        profile, tcm = self._resolve_tcm(tcm_name, profile_path)
        adapter = self._make_adapter(profile)
        adapter.clear_trigger_sticky(tcm)
