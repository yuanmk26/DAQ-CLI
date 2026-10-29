"""TCM timestamp-alignment controller.

Register sequence (FDU-TCM v3):

1. write ``0x18 <- 0x02`` (CLEAR), sleep ``command_delay_s``
2. write ``0x18 <- 0x01`` (START)
3. poll ``0x19`` (status) / ``0x1A`` (online) / ``0x1B`` (ack) / ``0x1C``
   (missing) until the sticky DONE bit or the sticky TIMEOUT bit is set, or
   ``poll_timeout_s`` elapses
4. success = DONE sticky set AND every online board acknowledged
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from daq_cli.infrastructure.multi_board_acquire.clock import MultiBoardClock, SYSTEM_CLOCK
from daq_cli.infrastructure.multi_board_acquire.config import MultiBoardAppConfig
from daq_cli.infrastructure.multi_board_acquire.constants import (
    ALIGN_ACK_MASK_ADDR,
    ALIGN_CTRL_ADDR,
    ALIGN_CTRL_CLEAR,
    ALIGN_CTRL_START,
    ALIGN_MISSING_ACK_MASK_ADDR,
    ALIGN_ONLINE_MASK_ADDR,
    ALIGN_STATUS_ADDR,
    STATUS_DONE_STICKY_BIT,
    STATUS_TIMEOUT_STICKY_BIT,
    status_bit,
)
from daq_cli.infrastructure.rbcp import RbcpClient

RbcpFactory = Callable[..., RbcpClient]


@dataclass(slots=True)
class AlignSnapshot:
    status: int
    online_mask: int
    ack_mask: int
    missing_mask: int


class TcmAlignController:
    def __init__(
        self,
        config: MultiBoardAppConfig,
        logger,
        *,
        clock: MultiBoardClock = SYSTEM_CLOCK,
        rbcp_factory: RbcpFactory = RbcpClient,
    ) -> None:
        self.config = config
        self.logger = logger
        self._clock = clock
        self._rbcp_factory = rbcp_factory

    # ------------------------------------------------------------ primitives

    def _read_u8(self, bus: RbcpClient, addr: int) -> int:
        data = bus.read(addr, 1)
        if len(data) != 1:
            raise RuntimeError("RBCP read returned %d bytes, expected 1" % len(data))
        return data[0]

    def _write_u8(self, bus: RbcpClient, addr: int, value: int) -> None:
        bus.write(addr, bytes([value & 0xFF]))

    def _read_snapshot(self, bus: RbcpClient) -> AlignSnapshot:
        return AlignSnapshot(
            status=self._read_u8(bus, ALIGN_STATUS_ADDR),
            online_mask=self._read_u8(bus, ALIGN_ONLINE_MASK_ADDR),
            ack_mask=self._read_u8(bus, ALIGN_ACK_MASK_ADDR),
            missing_mask=self._read_u8(bus, ALIGN_MISSING_ACK_MASK_ADDR),
        )

    # ----------------------------------------------------------------- align

    def align(self) -> tuple[bool, AlignSnapshot]:
        bus = self._rbcp_factory(
            device_ip=self.config.tcm_ip,
            udp_port=self.config.tcm_rbcp_port,
            timeout_ms=self.config.tcm_timeout_ms,
        )
        try:
            self.logger.log(
                "INFO",
                "TCM align start ip=%s port=%d"
                % (self.config.tcm_ip, self.config.tcm_rbcp_port),
            )

            self._write_u8(bus, ALIGN_CTRL_ADDR, ALIGN_CTRL_CLEAR)
            self._clock.sleep(self.config.tcm_command_delay_s)
            self._write_u8(bus, ALIGN_CTRL_ADDR, ALIGN_CTRL_START)

            deadline = self._clock.monotonic() + self.config.tcm_poll_timeout_s
            final_snapshot: AlignSnapshot | None = None
            while self._clock.monotonic() < deadline:
                snapshot = self._read_snapshot(bus)
                if status_bit(snapshot.status, STATUS_DONE_STICKY_BIT):
                    final_snapshot = snapshot
                    break
                if status_bit(snapshot.status, STATUS_TIMEOUT_STICKY_BIT):
                    final_snapshot = snapshot
                    break
                self._clock.sleep(self.config.tcm_poll_interval_s)

            if final_snapshot is None:
                final_snapshot = self._read_snapshot(bus)

            success = (
                status_bit(final_snapshot.status, STATUS_DONE_STICKY_BIT) == 1
                and (final_snapshot.ack_mask & final_snapshot.online_mask)
                == final_snapshot.online_mask
            )

            self.logger.log(
                "INFO" if success else "ERROR",
                (
                    "TCM align result success=%s status=0x%02X online=0x%02X "
                    "ack=0x%02X missing=0x%02X"
                    % (
                        str(success).lower(),
                        final_snapshot.status,
                        final_snapshot.online_mask,
                        final_snapshot.ack_mask,
                        final_snapshot.missing_mask,
                    )
                ),
            )
            return success, final_snapshot
        finally:
            bus.close()

    def clear_align(self) -> None:
        """Clear the alignment controller (ALIGN_CTRL_CLEAR write)."""
        bus = self._rbcp_factory(
            device_ip=self.config.tcm_ip,
            udp_port=self.config.tcm_rbcp_port,
            timeout_ms=self.config.tcm_timeout_ms,
        )
        try:
            self._write_u8(bus, ALIGN_CTRL_ADDR, ALIGN_CTRL_CLEAR)
        finally:
            bus.close()


__all__ = ["AlignSnapshot", "RbcpFactory", "TcmAlignController"]
