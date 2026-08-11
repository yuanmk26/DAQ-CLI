from __future__ import annotations

import importlib
import io
import time
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from daq_cli.application.config_models import BoardConfigOptions
from daq_cli.domain.device import DeviceConfig
from daq_cli.infrastructure.adapters.legacy_runtime import (
    bundled_legacy_script_dir,
    clear_legacy_modules,
    device_environment,
    temporary_sys_path,
)


@dataclass(slots=True)
class LegacySysmonSnapshot:
    temperature_c: float
    vccint_v: float
    vccaux_v: float
    vccbram_v: float


@dataclass(slots=True)
class LegacyBoardConfigResult:
    success: bool
    log_output: str


@dataclass(slots=True)
class LegacyRegisterReadResult:
    address: int
    data: bytes


@dataclass(slots=True)
class LegacyTriggerReadResult:
    trigger_mode: int
    trigger_position: int
    thresholds: tuple[int, int, int, int]
    send_start_delay: int
    timestamp_clean_enabled: bool
    ext_trigger_enabled: bool


@dataclass(slots=True)
class LegacyTcpMode2ReadResult:
    send_mode: int
    integration_pre_samples: int
    integration_post_samples: int
    hit_thresholds: list[int]
    hit_polarities: list[int]


@dataclass(slots=True)
class LegacyTcmLinkReadResult:
    thresholds: list[int]
    mask: int
    polarity: int
    debounce: int
    enable: bool
    pulse_width: int


class LegacyBoardAdapter:
    """Thin wrapper around the existing board-control scripts."""

    def __init__(self, script_dir: Path | str | None = None) -> None:
        self._script_dir = (
            Path(script_dir) if script_dir is not None else bundled_legacy_script_dir()
        )

    def read_sysmon(self, device: DeviceConfig) -> LegacySysmonSnapshot:
        with temporary_sys_path(self._script_dir), device_environment(device):
            clear_legacy_modules()
            sysmon_module = importlib.import_module("lib.sysmon")
            sysmon_reader = sysmon_module.sysmon()
            return LegacySysmonSnapshot(
                temperature_c=float(sysmon_reader.temperature()),
                vccint_v=float(sysmon_reader.vccint()),
                vccaux_v=float(sysmon_reader.vccaux()),
                vccbram_v=float(sysmon_reader.vccbram()),
            )

    def configure_board(
        self,
        device: DeviceConfig,
        send_start_delay_us: float = 0.0,
        options: BoardConfigOptions | None = None,
    ) -> LegacyBoardConfigResult:
        options = options or BoardConfigOptions()
        # The legacy configure_device() issues many RBCP requests (I2C
        # register writes for the ADC/clock chips); occasional UDP drops
        # surface as RbcpTimeout. Retry the whole run a few times — the
        # configuration is idempotent, so a re-run is safe.
        last_error: BaseException | None = None
        for attempt in range(3):
            try:
                with temporary_sys_path(self._script_dir), device_environment(
                    device, send_start_delay_us=send_start_delay_us
                ):
                    clear_legacy_modules()
                    module = importlib.import_module("start_16CH_two_board")
                    module.CONFIG_ADC = options.adc_enabled
                    module.CONFIG_CLOCK = options.clock_enabled
                    module.CONFIG_TRIGGER = options.trigger_enabled
                    module.CONFIG_TCP_MODE2 = options.tcp_mode2_enabled
                    captured = io.StringIO()
                    with self._patched_trigger_behavior(options), redirect_stdout(
                        captured
                    ):
                        success = bool(module.configure_device())
                    return LegacyBoardConfigResult(
                        success=success,
                        log_output=captured.getvalue(),
                    )
            except Exception as exc:  # noqa: BLE001 - retry any RBCP/I2C failure
                last_error = exc
                time.sleep(1.0 * (attempt + 1))
        raise RuntimeError(
            f"board configuration failed after 3 attempts: {last_error}"
        ) from last_error

    def read_registers(
        self, device: DeviceConfig, address: int, length: int
    ) -> LegacyRegisterReadResult:
        with temporary_sys_path(self._script_dir), device_environment(device):
            clear_legacy_modules()
            rbcp_module = importlib.import_module("lib.rbcp")
            rbcp_client = rbcp_module.Rbcp(device_ip=device.ip, udp_port=device.rbcp_port)
            data = bytes(rbcp_client.read(address, length))
            return LegacyRegisterReadResult(address=address, data=data)

    def write_registers(self, device: DeviceConfig, address: int, data: bytes) -> None:
        with temporary_sys_path(self._script_dir), device_environment(device):
            clear_legacy_modules()
            rbcp_module = importlib.import_module("lib.rbcp")
            rbcp_client = rbcp_module.Rbcp(device_ip=device.ip, udp_port=device.rbcp_port)
            rbcp_client.write(address, bytes(data))

    def read_trigger_config(self, device: DeviceConfig) -> LegacyTriggerReadResult:
        with temporary_sys_path(self._script_dir), device_environment(device):
            clear_legacy_modules()
            fpga_ctrl_module = importlib.import_module("FPGA_CTRL")
            controller = fpga_ctrl_module.FPGAControl()
            trigger_mode, trigger_position, thresholds = controller.read_trigger_info()
            ctrl_reg = controller.rbcp.read(0x06, 1)[0]
            delay_bytes = controller.rbcp.read(0x1B, 3)
            send_start_delay = (
                (delay_bytes[0] << 16) | (delay_bytes[1] << 8) | delay_bytes[2]
            )
            return LegacyTriggerReadResult(
                trigger_mode=int(trigger_mode),
                trigger_position=int(trigger_position),
                thresholds=tuple(int(value) for value in thresholds),
                send_start_delay=send_start_delay,
                timestamp_clean_enabled=bool((ctrl_reg >> 1) & 0x1),
                ext_trigger_enabled=bool((ctrl_reg >> 2) & 0x1),
            )

    def read_tcp_mode2_config(self, device: DeviceConfig) -> LegacyTcpMode2ReadResult:
        with temporary_sys_path(self._script_dir), device_environment(device):
            clear_legacy_modules()
            fpga_ctrl_module = importlib.import_module("FPGA_CTRL")
            controller = fpga_ctrl_module.FPGAControl()
            hit_thresholds, hit_polarities = controller.read_hit_config()
            send_mode = controller.rbcp.read(0x42, 1)[0] & 0x03
            integration_pre_samples = controller.rbcp.read(0x43, 1)[0] & 0x7F
            integration_post_samples = controller.rbcp.read(0x44, 1)[0] & 0x7F
            return LegacyTcpMode2ReadResult(
                send_mode=send_mode,
                integration_pre_samples=integration_pre_samples,
                integration_post_samples=integration_post_samples,
                hit_thresholds=[int(value) for value in hit_thresholds],
                hit_polarities=[int(value) for value in hit_polarities],
            )

    def write_send_mode(self, device: DeviceConfig, send_mode: int) -> None:
        if send_mode < 0 or send_mode > 3:
            raise ValueError("send_mode must stay in range 0..3")
        current = self.read_registers(device, 0x42, 1).data[0]
        updated = (current & 0xFC) | (send_mode & 0x03)
        self.write_registers(device, 0x42, bytes([updated]))

    def read_tcm_link_config(self, device: DeviceConfig) -> LegacyTcmLinkReadResult:
        """Read the TCM trigger-link registers (0x45..0x6C) without writing.

        Thresholds are read from the *effective* comparator registers
        (0x63-2N for channel N): the firmware TCM_THR concatenation
        ``{x45..x64}`` places channel 0 at the MSB while the comparator
        indexes ``thr[ch*16 +: 16]`` from the LSB, so the documented
        0x45+2N positions are not what the crossing detector reads.
        """
        with temporary_sys_path(self._script_dir), device_environment(device):
            clear_legacy_modules()
            rbcp_module = importlib.import_module("lib.rbcp")
            client = rbcp_module.Rbcp(device_ip=device.ip, udp_port=device.rbcp_port)
            data = bytes(client.read(0x45, 0x28))  # 0x45..0x6C
            thresholds = [
                (data[0x1E - i * 2] << 8) | data[0x1F - i * 2]
                for i in range(16)
            ]
            mask = (data[0x20] << 8) | data[0x21]
            polarity = (data[0x22] << 8) | data[0x23]
            debounce = (data[0x24] << 8) | data[0x25]
            enable = data[0x26] & 0x01
            pulse_width = data[0x27]
            return LegacyTcmLinkReadResult(
                thresholds=thresholds,
                mask=int(mask),
                polarity=int(polarity),
                debounce=int(debounce),
                enable=bool(enable),
                pulse_width=int(pulse_width),
            )

    def write_tcm_link_config(
        self,
        device: DeviceConfig,
        *,
        thresholds: list[int],
        mask: int,
        polarity: int,
        debounce: int,
        pulse_width: int,
        enable: bool,
    ) -> None:
        """Write the TCM trigger-link configuration (0x45..0x6C).

        Thresholds are written to the effective comparator registers
        (0x63-2N for channel N, see read_tcm_link_config) before the
        enable bit so the pulse output is only activated once everything
        is in place.
        """
        if len(thresholds) != 16:
            raise ValueError("TCM link needs exactly 16 channel thresholds")
        if any(value < 0 or value > 0xFFFF for value in thresholds):
            raise ValueError("TCM link thresholds must stay in range 0..0xFFFF")
        if mask < 0 or mask > 0xFFFF:
            raise ValueError("TCM link mask must stay in range 0..0xFFFF")
        if polarity < 0 or polarity > 0xFFFF:
            raise ValueError("TCM link polarity must stay in range 0..0xFFFF")
        if debounce < 0 or debounce > 0xFFFF:
            raise ValueError("TCM link debounce must stay in range 0..0xFFFF")
        if pulse_width < 0 or pulse_width > 0xFF:
            raise ValueError("TCM link pulse width must stay in range 0..0xFF")
        with temporary_sys_path(self._script_dir), device_environment(device):
            clear_legacy_modules()
            rbcp_module = importlib.import_module("lib.rbcp")
            client = rbcp_module.Rbcp(device_ip=device.ip, udp_port=device.rbcp_port)
            for i, threshold in enumerate(thresholds):
                addr = 0x63 - i * 2
                client.write(addr, bytes([(threshold >> 8) & 0xFF]))
                client.write(addr + 1, bytes([threshold & 0xFF]))
            fpga_ctrl_module = importlib.import_module("FPGA_CTRL")
            controller = fpga_ctrl_module.FPGAControl()
            controller.set_tcm_config(
                mask=mask,
                polarity=polarity,
                pulse_width=pulse_width,
                debounce=debounce,
                enable=enable,
            )

    @contextmanager
    def _patched_trigger_behavior(
        self, options: BoardConfigOptions
    ) -> Iterator[None]:
        fpga_ctrl_module = importlib.import_module("FPGA_CTRL")
        controller_cls = fpga_ctrl_module.FPGAControl

        original_set_threshold = controller_cls.set_threshold
        original_timestamp_clean_en = controller_cls.timestamp_clean_en
        original_ext_trigger_en = controller_cls.ext_trigger_en
        original_trigger_model = controller_cls.trigger_model
        original_trigger_postion = controller_cls.trigger_postion

        def patched_set_threshold(self, *thresholds):
            return original_set_threshold(self, *options.trigger_thresholds)

        def patched_timestamp_clean_en(self, mode):
            effective_mode = "enable" if options.timestamp_clean_enabled else "disable"
            return original_timestamp_clean_en(self, effective_mode)

        def patched_ext_trigger_en(self, mode):
            effective_mode = "enable" if options.ext_trigger_enabled else "disable"
            return original_ext_trigger_en(self, effective_mode)

        def patched_trigger_model(self, mode):
            return original_trigger_model(self, options.trigger_mode)

        def patched_trigger_postion(self, trigger_postion):
            return original_trigger_postion(self, options.trigger_position)

        controller_cls.set_threshold = patched_set_threshold
        controller_cls.timestamp_clean_en = patched_timestamp_clean_en
        controller_cls.ext_trigger_en = patched_ext_trigger_en
        controller_cls.trigger_model = patched_trigger_model
        controller_cls.trigger_postion = patched_trigger_postion
        try:
            yield
        finally:
            controller_cls.set_threshold = original_set_threshold
            controller_cls.timestamp_clean_en = original_timestamp_clean_en
            controller_cls.ext_trigger_en = original_ext_trigger_en
            controller_cls.trigger_model = original_trigger_model
            controller_cls.trigger_postion = original_trigger_postion
