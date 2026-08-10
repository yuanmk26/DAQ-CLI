from __future__ import annotations

import importlib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from daq_cli.domain.tcm import TcmConfig
from daq_cli.infrastructure.adapters.legacy_runtime import (
    bundled_legacy_script_dir,
    clear_legacy_modules,
    temporary_sys_path,
)

# FDU-TCM v2 trigger-link registers (docs/changes/2026-08-08):
#   0x20 TRG_CTRL        bit0 = trigger-link enable, bit1 = clear sticky (write 1)
#   0x21 TRG_IN_MASK     8-bit per-channel participation mask
#   0x22 TRG_PULSE_WIDTH wide pulse width in 20M cycles (default 32 = 1.6us)
#   0x23 TRG_DEBOUNCE    debounce in 20M cycles (default 20 = 1us)
#   0x24 TRG_STATUS      bit0 = trig_sticky, bit1 = pending, bit2 = wide pulse active
#   0x25 TRG_CHAN        channels of the most recent trigger event
_TRG_CTRL_ADDR = 0x20
_TRG_MASK_ADDR = 0x21
_TRG_PULSE_WIDTH_ADDR = 0x22
_TRG_DEBOUNCE_ADDR = 0x23
_TRG_STATUS_ADDR = 0x24
_TRG_CHAN_ADDR = 0x25

_TRG_CTRL_ENABLE_BIT = 1 << 0
_TRG_CTRL_CLEAR_STICKY_BIT = 1 << 1
_TRG_STATUS_STICKY_BIT = 1 << 0
_TRG_STATUS_PENDING_BIT = 1 << 1
_TRG_STATUS_WIDE_PULSE_BIT = 1 << 2

DEFAULT_TRG_PULSE_WIDTH = 32
DEFAULT_TRG_DEBOUNCE = 20


@dataclass(slots=True)
class LegacyTcmTriggerReadResult:
    enable: bool
    mask: int
    pulse_width: int
    debounce: int
    trig_sticky: bool
    pending: bool
    wide_pulse_active: bool
    last_trigger_channels: int


class LegacyTcmAdapter:
    """RBCP access to the TCM board trigger-link registers (0x20..0x25)."""

    def __init__(self, script_dir: Path | str | None = None) -> None:
        self._script_dir = (
            Path(script_dir) if script_dir is not None else bundled_legacy_script_dir()
        )

    @contextmanager
    def _rbcp_client(self, tcm: TcmConfig) -> Iterator[object]:
        with temporary_sys_path(self._script_dir):
            clear_legacy_modules()
            rbcp_module = importlib.import_module("lib.rbcp")
            yield rbcp_module.Rbcp(device_ip=tcm.ip, udp_port=tcm.rbcp_port)

    def read_trigger_config(self, tcm: TcmConfig) -> LegacyTcmTriggerReadResult:
        with self._rbcp_client(tcm) as client:
            ctrl = client.read(_TRG_CTRL_ADDR, 1)[0]
            mask = client.read(_TRG_MASK_ADDR, 1)[0]
            pulse_width = client.read(_TRG_PULSE_WIDTH_ADDR, 1)[0]
            debounce_bytes = client.read(_TRG_DEBOUNCE_ADDR, 2)
            status = client.read(_TRG_STATUS_ADDR, 1)[0]
            last_trigger_channels = client.read(_TRG_CHAN_ADDR, 1)[0]
        debounce = (debounce_bytes[0] << 8) | debounce_bytes[1]
        return LegacyTcmTriggerReadResult(
            enable=bool(ctrl & _TRG_CTRL_ENABLE_BIT),
            mask=int(mask),
            pulse_width=int(pulse_width),
            debounce=int(debounce),
            trig_sticky=bool(status & _TRG_STATUS_STICKY_BIT),
            pending=bool(status & _TRG_STATUS_PENDING_BIT),
            wide_pulse_active=bool(status & _TRG_STATUS_WIDE_PULSE_BIT),
            last_trigger_channels=int(last_trigger_channels),
        )

    def write_trigger_config(
        self,
        tcm: TcmConfig,
        *,
        enable: bool,
        mask: int,
        pulse_width: int,
        debounce: int,
    ) -> None:
        """Write mask/width/debounce first, then the enable bit."""
        if mask < 0 or mask > 0xFF:
            raise ValueError("TCM trigger mask must stay in range 0..0xFF")
        if pulse_width < 0 or pulse_width > 0xFF:
            raise ValueError("TCM pulse width must stay in range 0..0xFF")
        if debounce < 0 or debounce > 0xFFFF:
            raise ValueError("TCM debounce must stay in range 0..0xFFFF")
        with self._rbcp_client(tcm) as client:
            client.write(_TRG_MASK_ADDR, bytes([mask]))
            client.write(_TRG_PULSE_WIDTH_ADDR, bytes([pulse_width]))
            client.write(
                _TRG_DEBOUNCE_ADDR,
                bytes([(debounce >> 8) & 0xFF, debounce & 0xFF]),
            )
            ctrl = _TRG_CTRL_ENABLE_BIT if enable else 0
            client.write(_TRG_CTRL_ADDR, bytes([ctrl]))

    def clear_trigger_sticky(self, tcm: TcmConfig) -> None:
        """Clear the trigger sticky bit by writing bit1 of 0x20 (RMW)."""
        with self._rbcp_client(tcm) as client:
            ctrl = client.read(_TRG_CTRL_ADDR, 1)[0]
            updated = ctrl | _TRG_CTRL_CLEAR_STICKY_BIT
            client.write(_TRG_CTRL_ADDR, bytes([updated]))
