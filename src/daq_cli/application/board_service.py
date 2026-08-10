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
    requested_send_mode: int | None
    effective_send_mode: int | None
    log_output: str


@dataclass(slots=True)
class RegisterReadResult:
    device: DeviceConfig
    source_profile: Path
    address: int
    data: bytes


@dataclass(slots=True)
class TriggerConfigReadResult:
    device: DeviceConfig
    source_profile: Path
    trigger_mode: int
    trigger_position: int
    thresholds: tuple[int, int, int, int]
    send_start_delay: int
    timestamp_clean_enabled: bool
    ext_trigger_enabled: bool


@dataclass(slots=True)
class TcpMode2ConfigReadResult:
    device: DeviceConfig
    source_profile: Path
    send_mode: int
    integration_pre_samples: int
    integration_post_samples: int
    hit_thresholds: list[int]
    hit_polarities: list[int]


@dataclass(slots=True)
class SendModeSetResult:
    device: DeviceConfig
    source_profile: Path
    requested_send_mode: int
    effective_send_mode: int


@dataclass(slots=True)
class TcmLinkConfigReadResult:
    device: DeviceConfig
    source_profile: Path
    thresholds: list[int]
    mask: int
    polarity: int
    debounce: int
    enable: bool
    pulse_width: int


@dataclass(slots=True)
class TcmLinkConfigWriteResult:
    device: DeviceConfig
    source_profile: Path
    thresholds: list[int]
    mask: int
    polarity: int
    debounce: int
    enable: bool
    pulse_width: int


@dataclass(slots=True)
class BoardConfigSummaryResult:
    device: DeviceConfig
    source_profile: Path
    trigger: TriggerConfigReadResult
    tcp_mode2: TcpMode2ConfigReadResult


class BoardService:
    """Board-oriented business workflows."""

    def __init__(self, profile_service: ProfileService | None = None) -> None:
        self._profile_service = profile_service or ProfileService()

    def _resolve_device(
        self, device_name: str, profile_path: Path | str
    ) -> tuple[object, DeviceConfig]:
        profile = self._profile_service.load_profile(profile_path)
        try:
            device = profile.devices[device_name]
        except KeyError as exc:
            available = ", ".join(sorted(profile.devices)) or "<none>"
            raise ValueError(
                f"Unknown device '{device_name}'. Available devices: {available}"
            ) from exc
        return profile, device

    def get_board_info(
        self, device_name: str, profile_path: Path | str
    ) -> BoardInfoResult:
        resolved_profile_path = Path(profile_path)
        profile, device = self._resolve_device(device_name, resolved_profile_path)

        return BoardInfoResult(
            device=device,
            source_profile=profile.path,
        )

    def configure_board(
        self,
        device_name: str,
        profile_path: Path | str,
        send_start_delay_us: float = 0.0,
        options: BoardConfigOptions | None = None,
    ) -> BoardConfigResult:
        profile, device = self._resolve_device(device_name, profile_path)

        options = options or BoardConfigOptions()
        adapter = LegacyBoardAdapter()
        raw_result = adapter.configure_board(
            device=device,
            send_start_delay_us=send_start_delay_us,
            options=options,
        )
        effective_send_mode: int | None = None
        log_output = raw_result.log_output
        if options.send_mode is not None:
            send_mode_result = self._set_send_mode_with_adapter(
                adapter=adapter,
                device=device,
                source_profile=profile.path,
                send_mode=options.send_mode,
            )
            effective_send_mode = send_mode_result.effective_send_mode
            log_output = self._annotate_send_mode_log(
                raw_result.log_output,
                effective_send_mode=effective_send_mode,
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
            requested_send_mode=options.send_mode,
            effective_send_mode=effective_send_mode,
            log_output=log_output,
        )

    def read_registers(
        self, device_name: str, profile_path: Path | str, address: int, length: int
    ) -> RegisterReadResult:
        profile, device = self._resolve_device(device_name, profile_path)
        adapter = self._make_adapter(profile)
        raw_result = adapter.read_registers(device, address, length)
        return RegisterReadResult(
            device=device,
            source_profile=profile.path,
            address=raw_result.address,
            data=raw_result.data,
        )

    def write_registers(
        self, device_name: str, profile_path: Path | str, address: int, data: bytes
    ) -> None:
        profile, device = self._resolve_device(device_name, profile_path)
        adapter = self._make_adapter(profile)
        adapter.write_registers(device, address, data)

    def read_trigger_config(
        self, device_name: str, profile_path: Path | str
    ) -> TriggerConfigReadResult:
        profile, device = self._resolve_device(device_name, profile_path)
        adapter = self._make_adapter(profile)
        raw_result = adapter.read_trigger_config(device)
        return TriggerConfigReadResult(
            device=device,
            source_profile=profile.path,
            trigger_mode=raw_result.trigger_mode,
            trigger_position=raw_result.trigger_position,
            thresholds=raw_result.thresholds,
            send_start_delay=raw_result.send_start_delay,
            timestamp_clean_enabled=raw_result.timestamp_clean_enabled,
            ext_trigger_enabled=raw_result.ext_trigger_enabled,
        )

    def read_tcp_mode2_config(
        self, device_name: str, profile_path: Path | str
    ) -> TcpMode2ConfigReadResult:
        profile, device = self._resolve_device(device_name, profile_path)
        adapter = self._make_adapter(profile)
        raw_result = adapter.read_tcp_mode2_config(device)
        return TcpMode2ConfigReadResult(
            device=device,
            source_profile=profile.path,
            send_mode=raw_result.send_mode,
            integration_pre_samples=raw_result.integration_pre_samples,
            integration_post_samples=raw_result.integration_post_samples,
            hit_thresholds=raw_result.hit_thresholds,
            hit_polarities=raw_result.hit_polarities,
        )

    def read_board_config_summary(
        self, device_name: str, profile_path: Path | str
    ) -> BoardConfigSummaryResult:
        trigger = self.read_trigger_config(
            device_name=device_name, profile_path=profile_path
        )
        tcp_mode2 = self.read_tcp_mode2_config(
            device_name=device_name, profile_path=profile_path
        )
        return BoardConfigSummaryResult(
            device=trigger.device,
            source_profile=trigger.source_profile,
            trigger=trigger,
            tcp_mode2=tcp_mode2,
        )

    def set_send_mode(
        self,
        device_name: str,
        profile_path: Path | str,
        send_mode: int,
    ) -> SendModeSetResult:
        profile, device = self._resolve_device(device_name, profile_path)
        adapter = self._make_adapter(profile)
        return self._set_send_mode_with_adapter(
            adapter=adapter,
            device=device,
            source_profile=profile.path,
            send_mode=send_mode,
        )

    def read_tcm_link_config(
        self, device_name: str, profile_path: Path | str
    ) -> TcmLinkConfigReadResult:
        profile, device = self._resolve_device(device_name, profile_path)
        adapter = self._make_adapter(profile)
        raw_result = adapter.read_tcm_link_config(device)
        return TcmLinkConfigReadResult(
            device=device,
            source_profile=profile.path,
            thresholds=raw_result.thresholds,
            mask=raw_result.mask,
            polarity=raw_result.polarity,
            debounce=raw_result.debounce,
            enable=raw_result.enable,
            pulse_width=raw_result.pulse_width,
        )

    def configure_tcm_link(
        self,
        device_name: str,
        profile_path: Path | str,
        *,
        thresholds: list[int],
        mask: int,
        polarity: int,
        debounce: int,
        pulse_width: int,
        enable: bool,
    ) -> TcmLinkConfigWriteResult:
        """Write the TCM trigger-link configuration and verify by readback."""
        profile, device = self._resolve_device(device_name, profile_path)
        adapter = self._make_adapter(profile)
        adapter.write_tcm_link_config(
            device,
            thresholds=thresholds,
            mask=mask,
            polarity=polarity,
            debounce=debounce,
            pulse_width=pulse_width,
            enable=enable,
        )
        readback = adapter.read_tcm_link_config(device)
        if (
            readback.thresholds != thresholds
            or readback.mask != mask
            or readback.polarity != polarity
            or readback.debounce != debounce
            or readback.pulse_width != pulse_width
            or readback.enable != enable
        ):
            raise RuntimeError(
                "TCM link write verification failed: requested "
                f"mask=0x{mask:04X} polarity=0x{polarity:04X} "
                f"debounce={debounce} width={pulse_width} enable={enable}, "
                f"read back mask=0x{readback.mask:04X} "
                f"polarity=0x{readback.polarity:04X} "
                f"debounce={readback.debounce} width={readback.pulse_width} "
                f"enable={readback.enable}."
            )
        return TcmLinkConfigWriteResult(
            device=device,
            source_profile=profile.path,
            thresholds=readback.thresholds,
            mask=readback.mask,
            polarity=readback.polarity,
            debounce=readback.debounce,
            enable=readback.enable,
            pulse_width=readback.pulse_width,
        )

    def _make_adapter(self, profile) -> LegacyBoardAdapter:
        return LegacyBoardAdapter()

    def _set_send_mode_with_adapter(
        self,
        adapter: LegacyBoardAdapter,
        device: DeviceConfig,
        source_profile: Path,
        send_mode: int,
    ) -> SendModeSetResult:
        adapter.write_send_mode(device, send_mode)
        readback = adapter.read_tcp_mode2_config(device)
        if readback.send_mode != send_mode:
            raise RuntimeError(
                f"send_mode write verification failed: requested {send_mode}, "
                f"read back {readback.send_mode}."
            )
        return SendModeSetResult(
            device=device,
            source_profile=source_profile,
            requested_send_mode=send_mode,
            effective_send_mode=readback.send_mode,
        )

    def _annotate_send_mode_log(
        self,
        log_output: str,
        effective_send_mode: int,
    ) -> str:
        normalized = log_output.replace(
            "Read Send Mode:", "Pre-write Read Send Mode:"
        )
        suffix = f"\nFinal verified send_mode: {effective_send_mode}\n"
        if normalized.endswith("\n"):
            return normalized + suffix.lstrip("\n")
        return normalized + suffix
