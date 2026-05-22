from __future__ import annotations

import importlib
import io
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from daq_cli.application.config_models import BoardConfigOptions
from daq_cli.domain.device import DeviceConfig
from daq_cli.infrastructure.adapters.legacy_runtime import (
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


class LegacyBoardAdapter:
    """Thin wrapper around the existing board-control scripts."""

    def __init__(self, legacy_project_root: Path | str) -> None:
        self._project_root = Path(legacy_project_root)
        self._script_dir = self._project_root / "script"

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
            with self._patched_trigger_behavior(options), redirect_stdout(captured):
                success = bool(module.configure_device())
            return LegacyBoardConfigResult(
                success=success,
                log_output=captured.getvalue(),
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
