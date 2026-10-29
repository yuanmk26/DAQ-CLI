"""The native frame representation shared by the multi-board pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from daq_cli.infrastructure.adapters.legacy_capture_runner import TcpSentHeaderFields
from daq_cli.infrastructure.multi_board_acquire.config import MultiBoardConfig
from daq_cli.infrastructure.multi_board_acquire.constants import bit_count


@dataclass(slots=True)
class MultiBoardFrame:
    """One TCP_SENT frame from one board.

    ``raw_packet`` holds the exact wire bytes (header + feature + waveform) so
    the writer can slice the payload and the watch path can hand the untouched
    packet to :func:`decode_tcp_sent_packet` — no re-encoding anywhere.
    """

    board_id: int
    board_name: str
    board_ip: str
    mode: int
    event_count: int
    timestamp: int
    hit_mask: int
    feature_record_length: int
    format_version: int
    recv_unix_ns: int
    raw_packet: bytes
    header_bytes: int
    feature_len: int
    waveform_len: int
    crossing_fine: int = 0
    accept_fine: int = 0
    reconnect_mark: bool = False

    @property
    def hit_count(self) -> int:
        return bit_count(self.hit_mask)

    @property
    def feature_bytes(self) -> bytes:
        return self.raw_packet[self.header_bytes : self.header_bytes + self.feature_len]

    @property
    def waveform_bytes(self) -> bytes:
        start = self.header_bytes + self.feature_len
        return self.raw_packet[start : start + self.waveform_len]


def frame_from_fields(
    fields: TcpSentHeaderFields,
    board: MultiBoardConfig,
    *,
    recv_unix_ns: int,
    reconnect_mark: bool = False,
) -> MultiBoardFrame:
    """Wrap validated reader output plus board identity into a frame."""
    return MultiBoardFrame(
        board_id=board.board_id,
        board_name=board.name,
        board_ip=board.ip,
        mode=fields.mode,
        event_count=fields.event_count,
        timestamp=fields.timestamp,
        hit_mask=fields.hit_mask,
        feature_record_length=fields.feature_record_length,
        format_version=fields.format_version,
        recv_unix_ns=recv_unix_ns,
        raw_packet=fields.packet,
        header_bytes=fields.header_bytes,
        feature_len=fields.feature_len,
        waveform_len=fields.waveform_len,
        crossing_fine=fields.crossing_fine or 0,
        accept_fine=fields.accept_fine or 0,
        reconnect_mark=reconnect_mark,
    )


__all__ = ["MultiBoardFrame", "frame_from_fields"]
