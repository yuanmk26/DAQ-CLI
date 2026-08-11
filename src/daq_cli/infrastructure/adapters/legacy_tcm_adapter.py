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

# FDU-TCM v2/v3 trigger-link registers
# (docs/rbcp_timestamp_alignment_registers.md — note 0x25 = STATUS /
# 0x26 = CHAN, debounce split LSB at 0x23 / MSB at 0x24; coincidence
# (v3) at 0x27..0x2F):
#   0x20 TRG_CTRL        bit0 = trigger-link enable, bit1 = clear sticky (write 1)
#   0x21 TRG_IN_MASK     8-bit per-channel participation mask (OR mode)
#   0x22 TRG_PULSE_WIDTH wide pulse width in 20M cycles (default 32 = 1.6us)
#   0x23 TRG_DEBOUNCE[7:0]   debounce low byte (default 20 = 1us)
#   0x24 TRG_DEBOUNCE[15:8]  debounce high byte
#   0x25 TRG_STATUS      bit0=trig_sticky, bit1=pending, bit2=wide active,
#                        bit3=collecting, bit7:4=grp_ok
#   0x26 TRG_CHAN        channels of the most recent trigger event
#   0x27 TRG_COINC_CTRL  bit0=coincidence enable, bit3:1=group count (0=default 2)
#   0x28 TRG_COINC_WINDOW coincidence window in 20M cycles (0=default 4)
#   0x29 TRG_COINC_STATUS bit0=trig_sticky, bit1=timeout sticky, bit5:2=collected count
#   0x2A..0x2D TRG_GRP_MASK_0..3  group participation masks
#   0x2E TRG_GRP_N_0_1  bit3:0=grp0 N, bit7:4=grp1 N (0=default 1)
#   0x2F TRG_GRP_N_2_3  bit3:0=grp2 N, bit7:4=grp3 N (0=default 1)
_TRG_CTRL_ADDR = 0x20
_TRG_MASK_ADDR = 0x21
_TRG_PULSE_WIDTH_ADDR = 0x22
_TRG_DEBOUNCE_ADDR = 0x23
_TRG_STATUS_ADDR = 0x25
_TRG_CHAN_ADDR = 0x26
_TRG_COINC_CTRL_ADDR = 0x27
_TRG_COINC_WINDOW_ADDR = 0x28
_TRG_COINC_STATUS_ADDR = 0x29
_TRG_GRP_MASK_ADDRS = (0x2A, 0x2B, 0x2C, 0x2D)
_TRG_GRP_N_0_1_ADDR = 0x2E
_TRG_GRP_N_2_3_ADDR = 0x2F

_TRG_CTRL_ENABLE_BIT = 1 << 0
_TRG_CTRL_CLEAR_STICKY_BIT = 1 << 1
_TRG_STATUS_STICKY_BIT = 1 << 0
_TRG_STATUS_PENDING_BIT = 1 << 1
_TRG_STATUS_WIDE_PULSE_BIT = 1 << 2
_TRG_STATUS_COLLECTING_BIT = 1 << 3
_TRG_STATUS_GRP_OK_MASK = 0xF0
_TRG_COINC_ENABLE_BIT = 1 << 0
_TRG_COINC_GRP_COUNT_MASK = 0x0E
_TRG_COINC_STATUS_TIMEOUT_STICKY_BIT = 1 << 1
_TRG_COINC_STATUS_COLLECTED_MASK = 0x3C

DEFAULT_TRG_PULSE_WIDTH = 32
DEFAULT_TRG_DEBOUNCE = 20
DEFAULT_TRG_COINC_WINDOW = 4
DEFAULT_TRG_GRP_COUNT = 2


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
            coinc_ctrl = client.read(_TRG_COINC_CTRL_ADDR, 1)[0]
            coinc_window = client.read(_TRG_COINC_WINDOW_ADDR, 1)[0]
            coinc_status = client.read(_TRG_COINC_STATUS_ADDR, 1)[0]
            group_masks = tuple(
                client.read(addr, 1)[0] for addr in _TRG_GRP_MASK_ADDRS
            )
            n_0_1 = client.read(_TRG_GRP_N_0_1_ADDR, 1)[0]
            n_2_3 = client.read(_TRG_GRP_N_2_3_ADDR, 1)[0]
        # 0x23 = LSB, 0x24 = MSB (final firmware layout)
        debounce = (debounce_bytes[1] << 8) | debounce_bytes[0]
        group_n = (
            n_0_1 & 0x0F,
            (n_0_1 >> 4) & 0x0F,
            n_2_3 & 0x0F,
            (n_2_3 >> 4) & 0x0F,
        )
        return LegacyTcmTriggerReadResult(
            enable=bool(ctrl & _TRG_CTRL_ENABLE_BIT),
            mask=int(mask),
            pulse_width=int(pulse_width),
            debounce=int(debounce),
            trig_sticky=bool(status & _TRG_STATUS_STICKY_BIT),
            pending=bool(status & _TRG_STATUS_PENDING_BIT),
            wide_pulse_active=bool(status & _TRG_STATUS_WIDE_PULSE_BIT),
            last_trigger_channels=int(last_trigger_channels),
            coincidence_enabled=bool(coinc_ctrl & _TRG_COINC_ENABLE_BIT),
            grp_count=int((coinc_ctrl & _TRG_COINC_GRP_COUNT_MASK) >> 1),
            coinc_window=int(coinc_window),
            coinc_timeout_sticky=bool(
                coinc_status & _TRG_COINC_STATUS_TIMEOUT_STICKY_BIT
            ),
            collected_count=int((coinc_status & _TRG_COINC_STATUS_COLLECTED_MASK) >> 2),
            collecting=bool(status & _TRG_STATUS_COLLECTING_BIT),
            grp_ok=int((status & _TRG_STATUS_GRP_OK_MASK) >> 4),
            group_masks=group_masks,
            group_n=group_n,
        )

    def write_trigger_config(
        self,
        tcm: TcmConfig,
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
    ) -> None:
        """Write mask/width/debounce first, then the enable bit.

        Coincidence (v3): group masks and Ns are written before 0x27 so the
        mode switch is atomic; 0x27 = enable bit + group count, written last.
        """
        if mask < 0 or mask > 0xFF:
            raise ValueError("TCM trigger mask must stay in range 0..0xFF")
        if pulse_width < 0 or pulse_width > 0xFF:
            raise ValueError("TCM pulse width must stay in range 0..0xFF")
        if debounce < 0 or debounce > 0xFFFF:
            raise ValueError("TCM debounce must stay in range 0..0xFFFF")
        if grp_count < 0 or grp_count > 4:
            raise ValueError("TCM group count must stay in range 0..4")
        if coinc_window < 0 or coinc_window > 0xFF:
            raise ValueError("TCM coincidence window must stay in range 0..0xFF")
        if len(group_masks) != 4 or any(value < 0 or value > 0xFF for value in group_masks):
            raise ValueError("TCM group masks must be 4 values in range 0..0xFF")
        if len(group_n) != 4 or any(value < 0 or value > 8 for value in group_n):
            raise ValueError("TCM group N values must be 4 values in range 0..8")
        with self._rbcp_client(tcm) as client:
            client.write(_TRG_MASK_ADDR, bytes([mask]))
            client.write(_TRG_PULSE_WIDTH_ADDR, bytes([pulse_width]))
            # 0x23 = LSB, 0x24 = MSB (final firmware layout)
            client.write(
                _TRG_DEBOUNCE_ADDR,
                bytes([debounce & 0xFF, (debounce >> 8) & 0xFF]),
            )
            for addr, grp_mask in zip(_TRG_GRP_MASK_ADDRS, group_masks):
                client.write(addr, bytes([grp_mask]))
            client.write(
                _TRG_GRP_N_0_1_ADDR,
                bytes([group_n[0] & 0x0F | (group_n[1] & 0x0F) << 4]),
            )
            client.write(
                _TRG_GRP_N_2_3_ADDR,
                bytes([group_n[2] & 0x0F | (group_n[3] & 0x0F) << 4]),
            )
            client.write(_TRG_COINC_WINDOW_ADDR, bytes([coinc_window]))
            coinc_ctrl = (
                (_TRG_COINC_ENABLE_BIT if coincidence_enabled else 0)
                | (grp_count & 0x07) << 1
            )
            client.write(_TRG_COINC_CTRL_ADDR, bytes([coinc_ctrl]))
            ctrl = _TRG_CTRL_ENABLE_BIT if enable else 0
            client.write(_TRG_CTRL_ADDR, bytes([ctrl]))

    def clear_trigger_sticky(self, tcm: TcmConfig) -> None:
        """Clear the trigger sticky bit by writing bit1 of 0x20 (RMW)."""
        with self._rbcp_client(tcm) as client:
            ctrl = client.read(_TRG_CTRL_ADDR, 1)[0]
            updated = ctrl | _TRG_CTRL_CLEAR_STICKY_BIT
            client.write(_TRG_CTRL_ADDR, bytes([updated]))

    def clear_align(self, tcm: TcmConfig) -> None:
        """Release a stuck TCM alignment controller (write ALIGN_CTRL_CLEAR).

        A failed align (boards not ACKing) leaves ALIGN_BUSY set, which
        blocks trigger-link wide-pulse broadcasts; clearing unblocks them.
        """
        with self._rbcp_client(tcm) as client:
            client.write(0x18, bytes([0x02]))  # ALIGN_CTRL_CLEAR
