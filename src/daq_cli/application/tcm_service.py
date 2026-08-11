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
    # coincidence (v3)
    coincidence_enabled: bool = False
    grp_count: int = 0
    coinc_window: int = 0
    coinc_timeout_sticky: bool = False
    collected_count: int = 0
    collecting: bool = False
    grp_ok: int = 0
    group_masks: tuple[int, int, int, int] = (0, 0, 0, 0)
    group_n: tuple[int, int, int, int] = (0, 0, 0, 0)


@dataclass(slots=True)
class TcmTriggerConfigWriteResult:
    tcm: TcmConfig
    source_profile: Path
    enable: bool
    mask: int
    pulse_width: int
    debounce: int
    coincidence_enabled: bool = False
    grp_count: int = 0
    coinc_window: int = 0
    group_masks: tuple[int, int, int, int] = (0, 0, 0, 0)
    group_n: tuple[int, int, int, int] = (0, 0, 0, 0)


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
            coincidence_enabled=raw_result.coincidence_enabled,
            grp_count=raw_result.grp_count,
            coinc_window=raw_result.coinc_window,
            coinc_timeout_sticky=raw_result.coinc_timeout_sticky,
            collected_count=raw_result.collected_count,
            collecting=raw_result.collecting,
            grp_ok=raw_result.grp_ok,
            group_masks=raw_result.group_masks,
            group_n=raw_result.group_n,
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
        coincidence_enabled: bool = False,
        grp_count: int = 0,
        coinc_window: int = 0,
        group_masks: tuple[int, int, int, int] = (0, 0, 0, 0),
        group_n: tuple[int, int, int, int] = (0, 0, 0, 0),
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
            coincidence_enabled=coincidence_enabled,
            grp_count=grp_count,
            coinc_window=coinc_window,
            group_masks=group_masks,
            group_n=group_n,
        )
        readback = adapter.read_trigger_config(tcm)
        if (
            readback.enable != enable
            or readback.mask != mask
            or readback.pulse_width != pulse_width
            or readback.debounce != debounce
            or readback.coincidence_enabled != coincidence_enabled
            or readback.grp_count != grp_count
            or readback.coinc_window != coinc_window
            or tuple(readback.group_masks) != tuple(group_masks)
            or tuple(readback.group_n) != tuple(group_n)
        ):
            raise RuntimeError(
                "TCM trigger write verification failed: requested "
                f"enable={enable} mask=0x{mask:02X} width={pulse_width} "
                f"debounce={debounce} coinc={coincidence_enabled} "
                f"groups={grp_count} window={coinc_window} "
                f"masks={group_masks} n={group_n}, read back "
                f"enable={readback.enable} mask=0x{readback.mask:02X} "
                f"width={readback.pulse_width} debounce={readback.debounce} "
                f"coinc={readback.coincidence_enabled} groups={readback.grp_count} "
                f"window={readback.coinc_window} masks={tuple(readback.group_masks)} "
                f"n={tuple(readback.group_n)}."
            )
        return TcmTriggerConfigWriteResult(
            tcm=tcm,
            source_profile=profile.path,
            enable=readback.enable,
            mask=readback.mask,
            pulse_width=readback.pulse_width,
            debounce=readback.debounce,
            coincidence_enabled=readback.coincidence_enabled,
            grp_count=readback.grp_count,
            coinc_window=readback.coinc_window,
            group_masks=tuple(readback.group_masks),
            group_n=tuple(readback.group_n),
        )

    def clear_trigger_sticky(
        self, tcm_name: str, profile_path: Path | str
    ) -> None:
        profile, tcm = self._resolve_tcm(tcm_name, profile_path)
        adapter = self._make_adapter(profile)
        adapter.clear_trigger_sticky(tcm)

    def clear_align(self, tcm_name: str, profile_path: Path | str) -> None:
        """Release a stuck alignment controller so trigger broadcasts resume."""
        profile, tcm = self._resolve_tcm(tcm_name, profile_path)
        adapter = self._make_adapter(profile)
        adapter.clear_align(tcm)
