from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from daq_cli.infrastructure.tcp_sent_decode import DecodedTcpSentEvent


@dataclass(slots=True)
class SegmentedTextWriteStats:
    events_written: int = 0
    files_created: int = 0


class SegmentedTextEventWriter:
    def __init__(self, output_dir: Path, max_events_per_file: int) -> None:
        self.output_dir = Path(output_dir)
        self.max_events_per_file = max(int(max_events_per_file), 1)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.current_file_index = 0
        self.current_event_count_in_file = 0
        self.current_file_handle: TextIO | None = None
        self.stats = SegmentedTextWriteStats()

    def append_event(self, rendered_event: str) -> Path:
        handle = self._ensure_file_handle()
        handle.write(rendered_event)
        if not rendered_event.endswith("\n"):
            handle.write("\n")
        handle.flush()
        self.current_event_count_in_file += 1
        self.stats.events_written += 1
        return self.output_dir / f"events_{self.current_file_index:05d}.txt"

    def close(self) -> None:
        if self.current_file_handle is not None:
            self.current_file_handle.close()
            self.current_file_handle = None

    def _ensure_file_handle(self) -> TextIO:
        if (
            self.current_file_handle is None
            or self.current_event_count_in_file >= self.max_events_per_file
        ):
            self.close()
            self.current_file_index += 1
            self.current_event_count_in_file = 0
            path = self.output_dir / f"events_{self.current_file_index:05d}.txt"
            self.current_file_handle = path.open("a", encoding="utf-8")
            self.stats.files_created += 1
        return self.current_file_handle


def format_single_event_text(
    event: DecodedTcpSentEvent,
    *,
    device_name: str,
    board_ip: str = "",
) -> str:
    lines = [
        f"===== EVENT {event.event_count} =====",
        "event_kind=single",
        f"device_name={device_name}",
        f"board_ip={board_ip}",
        f"source_file={event.source_file}",
        f"send_mode={event.send_mode}",
        f"event_count={event.event_count}",
        f"timestamp={event.timestamp}",
        f"hit_mask=0x{event.hit_mask:04X}",
        f"raw_packet_bytes={event.raw_packet_bytes}",
        "",
        f"[board {device_name}]",
        f"send_mode={event.send_mode}",
        f"event_count={event.event_count}",
        f"timestamp={event.timestamp}",
        f"hit_mask=0x{event.hit_mask:04X}",
    ]
    lines.extend(_format_feature_records(event.feature_records))
    lines.extend(_format_point_rows(event.channels))
    lines.extend(
        [
            f"===== END EVENT {event.event_count} =====",
            "",
        ]
    )
    return "\n".join(lines)


def format_multi_event_text(payload: dict[str, object]) -> str:
    aggregate_seq = int(payload.get("aggregate_seq", 0))
    lines = [
        f"===== EVENT {aggregate_seq} =====",
        f"event_kind={payload.get('event_kind', 'unknown')}",
        f"aggregate_seq={aggregate_seq}",
        f"aggregation_key={payload.get('aggregation_key', 'unknown')}",
        f"aggregate_timestamp={payload.get('aggregate_timestamp', 0)}",
        f"boards_present_mask=0x{int(payload.get('boards_present_mask', 0)):08X}",
        f"boards_missing_mask=0x{int(payload.get('boards_missing_mask', 0)):08X}",
        "missing_board_ids="
        + ",".join(str(item) for item in payload.get("missing_board_ids", [])),
        f"status_flags={payload.get('status_flags', 0)}",
        f"event_count_min={payload.get('event_count_min', 0)}",
        f"event_count_max={payload.get('event_count_max', 0)}",
        "",
    ]
    for board in payload.get("boards", []):
        if not isinstance(board, dict):
            continue
        board_name = str(board.get("board_name", f"bd{board.get('board_id', 0)}"))
        lines.extend(
            [
                f"[board {board_name}]",
                f"board_id={board.get('board_id', 0)}",
                f"board_ip={board.get('board_ip', '')}",
                f"recv_unix_ns={board.get('recv_unix_ns', 0)}",
                f"reconnect_mark={board.get('reconnect_mark', False)}",
                f"send_mode={board.get('send_mode', 0)}",
                f"event_count={board.get('event_count', 0)}",
                f"timestamp={board.get('timestamp', 0)}",
                f"hit_mask={board.get('hit_mask_hex', '0x0000')}",
            ]
        )
        feature_records = board.get("feature_records", [])
        if isinstance(feature_records, list):
            lines.extend(_format_feature_record_dicts(feature_records))
        channels = board.get("channels", [])
        if isinstance(channels, list):
            lines.extend(_format_point_rows(channels))
        lines.append("")
    lines.extend(
        [
            f"===== END EVENT {aggregate_seq} =====",
            "",
        ]
    )
    return "\n".join(lines)


def _format_feature_records(feature_records: list[object]) -> list[str]:
    if not feature_records:
        return ["feature_records=none"]
    lines = ["feature_records:"]
    for record in feature_records:
        lines.append(
            "feature "
            f"channel={record.channel} baseline={record.baseline} "
            f"peak_amp={record.peak_amp} peak_pos={record.peak_pos} "
            f"integral={record.integral}"
        )
    return lines


def _format_feature_record_dicts(feature_records: list[object]) -> list[str]:
    if not feature_records:
        return ["feature_records=none"]
    lines = ["feature_records:"]
    for record in feature_records:
        if not isinstance(record, dict):
            continue
        lines.append(
            "feature "
            f"channel={record.get('channel', 0)} "
            f"baseline={record.get('baseline', 0)} "
            f"peak_amp={record.get('peak_amp', 0)} "
            f"peak_pos={record.get('peak_pos', 0)} "
            f"integral={record.get('integral', 0)}"
        )
    return lines


def _format_point_rows(channels: list[object]) -> list[str]:
    if not any(isinstance(channel, list) and channel for channel in channels):
        return ["waveform=none"]

    max_length = 0
    normalized_channels: list[list[object] | None] = []
    for channel_index in range(16):
        if channel_index < len(channels) and isinstance(channels[channel_index], list):
            channel = channels[channel_index]
            normalized_channels.append(channel)
            max_length = max(max_length, len(channel))
        else:
            normalized_channels.append(None)

    headers = [f"ch{channel_index:02d}" for channel_index in range(16)]
    column_values: list[list[str]] = []
    for channel in normalized_channels:
        values: list[str] = []
        for sample_index in range(max_length):
            if channel is None or sample_index >= len(channel):
                values.append("NA")
            else:
                values.append(str(channel[sample_index]))
        column_values.append(values)
    column_widths = [
        max(len(headers[channel_index]), *(len(value) for value in column_values[channel_index]))
        for channel_index in range(16)
    ]

    lines = [
        "waveforms:",
        " ".join(
            header.rjust(column_widths[channel_index])
            for channel_index, header in enumerate(headers)
        ),
    ]
    for sample_index in range(max_length):
        lines.append(
            " ".join(
                column_values[channel_index][sample_index].rjust(column_widths[channel_index])
                for channel_index in range(16)
            )
        )
    return lines
