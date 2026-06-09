from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from daq_cli.infrastructure.tcp_sent_decode import decode_tcp_sent_packet


FORMAT_NAME = "FDU_ADC_AGGR"
FILE_MAGIC = b"FDUAGGR1"

EVENT_FLAG_COMPLETE = 1 << 0
EVENT_FLAG_PARTIAL = 1 << 1
EVENT_FLAG_TIMEOUT_FLUSH = 1 << 2
EVENT_FLAG_EVENT_COUNT_MISMATCH = 1 << 3

BOARD_FLAG_HAS_FEATURE = 1 << 0
BOARD_FLAG_HAS_WAVEFORM = 1 << 1
BOARD_FLAG_TCP_RECONNECTED_BEFORE_FRAME = 1 << 2

FILE_HEADER_FMT = "<8sHHIQIII"
EVENT_HEADER_FMT = "<IHHQQQQIIIIQQ"
BOARD_HEADER_FMT = "<IHHIIQHHHHIIQ"

FILE_HEADER_SIZE = struct.calcsize(FILE_HEADER_FMT)
EVENT_HEADER_SIZE = struct.calcsize(EVENT_HEADER_FMT)
BOARD_HEADER_SIZE = struct.calcsize(BOARD_HEADER_FMT)


@dataclass(slots=True)
class MultiBoardFileHeader:
    version: int
    created_unix_ns: int
    board_count: int
    adc_length: int


@dataclass(slots=True)
class MultiBoardChunkRecord:
    board_id: int
    board_flags: int
    event_count: int
    timestamp: int
    mode: int
    hit_mask: int
    hit_count: int
    feature_size: int
    feature_len: int
    waveform_len: int
    recv_unix_ns: int
    feature_bytes: bytes
    waveform_bytes: bytes


@dataclass(slots=True)
class MultiBoardEventRecord:
    source_file: Path
    event_kind: str
    aggregate_seq: int
    timestamp: int
    first_recv_unix_ns: int
    flush_unix_ns: int
    boards_present_mask: int
    boards_missing_mask: int
    status_flags: int
    event_count_min: int
    event_count_max: int
    boards: list[MultiBoardChunkRecord]


@dataclass(slots=True)
class MultiBoardTailReadState:
    offset: int = 0
    header_read: bool = False


@dataclass(slots=True)
class MultiBoardTailReadResult:
    state: MultiBoardTailReadState
    events: list[MultiBoardEventRecord]
    header: MultiBoardFileHeader | None = None


class MultiBoardDecodeError(RuntimeError):
    """Raised when an aggregated multi-board file cannot be decoded."""


class MultiBoardAggregatedEventReader:
    def __init__(self, path: Path | str, *, event_kind: str) -> None:
        self.path = Path(path)
        self.event_kind = event_kind

    def read_header(self) -> MultiBoardFileHeader:
        with self.path.open("rb") as fh:
            header = fh.read(FILE_HEADER_SIZE)
        return _parse_file_header(header=header, source=self.path)

    def iter_events(self) -> Iterable[MultiBoardEventRecord]:
        with self.path.open("rb") as fh:
            file_header = fh.read(FILE_HEADER_SIZE)
            _parse_file_header(header=file_header, source=self.path)

            while True:
                event_header = fh.read(EVENT_HEADER_SIZE)
                if not event_header:
                    break
                if len(event_header) != EVENT_HEADER_SIZE:
                    raise MultiBoardDecodeError(
                        f"Truncated event header in '{self.path}'."
                    )
                (
                    record_bytes,
                    header_bytes,
                    board_chunk_count,
                    aggregate_seq,
                    timestamp,
                    first_recv_unix_ns,
                    flush_unix_ns,
                    boards_present_mask,
                    boards_missing_mask,
                    status_flags,
                    _reserved,
                    event_count_min,
                    event_count_max,
                ) = struct.unpack(EVENT_HEADER_FMT, event_header)
                body_bytes = int(record_bytes) - int(header_bytes)
                if body_bytes < 0:
                    raise MultiBoardDecodeError(
                        f"Negative event body size in '{self.path}'."
                    )
                event_body = fh.read(body_bytes)
                if len(event_body) != body_bytes:
                    raise MultiBoardDecodeError(
                        f"Truncated event body in '{self.path}'."
                    )
                yield _build_event_record(
                    source_file=self.path,
                    event_kind=self.event_kind,
                    aggregate_seq=int(aggregate_seq),
                    timestamp=int(timestamp),
                    first_recv_unix_ns=int(first_recv_unix_ns),
                    flush_unix_ns=int(flush_unix_ns),
                    boards_present_mask=int(boards_present_mask),
                    boards_missing_mask=int(boards_missing_mask),
                    status_flags=int(status_flags),
                    event_count_min=int(event_count_min),
                    event_count_max=int(event_count_max),
                    board_chunk_count=int(board_chunk_count),
                    event_body=event_body,
                )


def load_multi_run_metadata(run_dir: Path | str) -> dict[str, object]:
    run_path = Path(run_dir)
    meta_path = run_path / "run_meta.json"
    if not meta_path.is_file():
        raise MultiBoardDecodeError(f"Run metadata not found: '{meta_path}'.")
    raw = json.loads(meta_path.read_text(encoding="utf-8"))
    if str(raw.get("format_name", "")) != FORMAT_NAME:
        raise MultiBoardDecodeError(
            f"Unsupported format_name in '{meta_path}': {raw.get('format_name')!r}."
        )
    return raw


def build_board_context(run_meta: dict[str, object]) -> dict[int, dict[str, object]]:
    context: dict[int, dict[str, object]] = {}
    for item in run_meta.get("boards_expected", []):
        if not isinstance(item, dict):
            continue
        board_id = int(item["board_id"])
        context[board_id] = {
            "board_name": str(item.get("name", f"bd{board_id}")),
            "board_ip": str(item.get("ip", "")),
        }
    return context


def event_to_json_dict(
    *,
    event: MultiBoardEventRecord,
    aggregation_key: str,
    board_context: dict[int, dict[str, object]],
) -> dict[str, object]:
    return {
        "source_file": str(event.source_file),
        "event_kind": event.event_kind,
        "aggregate_seq": event.aggregate_seq,
        "aggregation_key": aggregation_key,
        "aggregate_timestamp": event.timestamp,
        "first_recv_unix_ns": event.first_recv_unix_ns,
        "flush_unix_ns": event.flush_unix_ns,
        "boards_present_mask": event.boards_present_mask,
        "boards_missing_mask": event.boards_missing_mask,
        "missing_board_ids": board_ids_from_mask(event.boards_missing_mask),
        "status_flags": event.status_flags,
        "event_count_min": event.event_count_min,
        "event_count_max": event.event_count_max,
        "boards": [
            board_to_json_dict(
                board=board,
                source_file=event.source_file,
                board_context=board_context,
            )
            for board in event.boards
        ],
    }


def build_board_packet(record: MultiBoardChunkRecord) -> bytes:
    if record.feature_len > 0 and record.hit_count > 0:
        feature_record_length = record.feature_len // record.hit_count
    else:
        feature_record_length = 0
    header = bytearray(20)
    header[0:3] = b"\xFF\xFE\x01"
    header[3] = record.mode & 0xFF
    header[4:8] = int(record.event_count).to_bytes(4, "big", signed=False)
    header[8:16] = int(record.timestamp).to_bytes(8, "big", signed=False)
    header[16:18] = int(record.hit_mask).to_bytes(2, "big", signed=False)
    header[18] = int(feature_record_length) & 0xFF
    header[19] = 0
    return bytes(header) + record.feature_bytes + record.waveform_bytes


def board_ids_from_mask(mask: int) -> list[int]:
    return [board_id for board_id in range(32) if (mask >> board_id) & 0x1]


def board_to_json_dict(
    *,
    board: MultiBoardChunkRecord,
    source_file: Path,
    board_context: dict[int, dict[str, object]],
) -> dict[str, object]:
    packet = build_board_packet(board)
    decoded = decode_tcp_sent_packet(
        packet,
        source_file=source_file.with_name(
            f"{source_file.stem}_board_{board.board_id:02d}.bin"
        ),
    )
    context = board_context.get(board.board_id, {})
    return {
        "board_id": board.board_id,
        "board_name": str(context.get("board_name", f"bd{board.board_id}")),
        "board_ip": str(context.get("board_ip", "")),
        "recv_unix_ns": board.recv_unix_ns,
        "reconnect_mark": bool(
            board.board_flags & BOARD_FLAG_TCP_RECONNECTED_BEFORE_FRAME
        ),
        "send_mode": decoded.send_mode,
        "event_count": decoded.event_count,
        "timestamp": decoded.timestamp,
        "hit_mask": decoded.hit_mask,
        "hit_mask_hex": f"0x{decoded.hit_mask:04X}",
        "feature_record_length": decoded.feature_record_length,
        "channels": decoded.channels,
        "feature_records": [
            {
                "channel": record.channel,
                "baseline": record.baseline,
                "peak_amp": record.peak_amp,
                "peak_pos": record.peak_pos,
                "integral": record.integral,
            }
            for record in decoded.feature_records
        ],
        "raw_packet_bytes": decoded.raw_packet_bytes,
    }


def read_available_tail_events(
    *,
    path: Path | str,
    event_kind: str,
    state: MultiBoardTailReadState,
) -> MultiBoardTailReadResult:
    source = Path(path)
    if not source.is_file():
        return MultiBoardTailReadResult(state=state, events=[])

    file_size = source.stat().st_size
    current_state = MultiBoardTailReadState(
        offset=state.offset,
        header_read=state.header_read,
    )
    header: MultiBoardFileHeader | None = None
    if not current_state.header_read:
        if file_size < FILE_HEADER_SIZE:
            return MultiBoardTailReadResult(state=current_state, events=[])
        with source.open("rb") as fh:
            header_bytes = fh.read(FILE_HEADER_SIZE)
        header = _parse_file_header(header=header_bytes, source=source)
        current_state.header_read = True
        current_state.offset = FILE_HEADER_SIZE

    if file_size <= current_state.offset:
        return MultiBoardTailReadResult(state=current_state, events=[], header=header)

    events: list[MultiBoardEventRecord] = []
    with source.open("rb") as fh:
        while True:
            file_size = source.stat().st_size
            remaining = file_size - current_state.offset
            if remaining < EVENT_HEADER_SIZE:
                break
            fh.seek(current_state.offset)
            event_header = fh.read(EVENT_HEADER_SIZE)
            if len(event_header) != EVENT_HEADER_SIZE:
                break
            (
                record_bytes,
                header_bytes,
                board_chunk_count,
                aggregate_seq,
                timestamp,
                first_recv_unix_ns,
                flush_unix_ns,
                boards_present_mask,
                boards_missing_mask,
                status_flags,
                _reserved,
                event_count_min,
                event_count_max,
            ) = struct.unpack(EVENT_HEADER_FMT, event_header)
            record_bytes = int(record_bytes)
            header_bytes = int(header_bytes)
            if record_bytes < header_bytes:
                raise MultiBoardDecodeError(
                    f"Invalid event record size in '{source}'."
                )
            if remaining < record_bytes:
                break
            body_size = record_bytes - header_bytes
            event_body = fh.read(body_size)
            if len(event_body) != body_size:
                break
            events.append(
                _build_event_record(
                    source_file=source,
                    event_kind=event_kind,
                    aggregate_seq=int(aggregate_seq),
                    timestamp=int(timestamp),
                    first_recv_unix_ns=int(first_recv_unix_ns),
                    flush_unix_ns=int(flush_unix_ns),
                    boards_present_mask=int(boards_present_mask),
                    boards_missing_mask=int(boards_missing_mask),
                    status_flags=int(status_flags),
                    event_count_min=int(event_count_min),
                    event_count_max=int(event_count_max),
                    board_chunk_count=int(board_chunk_count),
                    event_body=event_body,
                )
            )
            current_state.offset += record_bytes
    return MultiBoardTailReadResult(state=current_state, events=events, header=header)


def _parse_file_header(*, header: bytes, source: Path) -> MultiBoardFileHeader:
    if len(header) != FILE_HEADER_SIZE:
        raise MultiBoardDecodeError(f"File '{source}' is too short for a header.")
    (
        magic,
        header_bytes,
        version,
        _reserved,
        created_unix_ns,
        _reserved2,
        board_count,
        adc_length,
    ) = struct.unpack(FILE_HEADER_FMT, header)
    if magic != FILE_MAGIC:
        raise MultiBoardDecodeError(
            f"File '{source}' does not have the expected aggregated file magic."
        )
    if int(header_bytes) != FILE_HEADER_SIZE:
        raise MultiBoardDecodeError(
            f"File '{source}' has unsupported header size {header_bytes}."
        )
    return MultiBoardFileHeader(
        version=int(version),
        created_unix_ns=int(created_unix_ns),
        board_count=int(board_count),
        adc_length=int(adc_length),
    )


def _build_event_record(
    *,
    source_file: Path,
    event_kind: str,
    aggregate_seq: int,
    timestamp: int,
    first_recv_unix_ns: int,
    flush_unix_ns: int,
    boards_present_mask: int,
    boards_missing_mask: int,
    status_flags: int,
    event_count_min: int,
    event_count_max: int,
    board_chunk_count: int,
    event_body: bytes,
) -> MultiBoardEventRecord:
    boards = _parse_board_chunks(event_body=event_body, source_file=source_file, board_chunk_count=board_chunk_count)
    return MultiBoardEventRecord(
        source_file=source_file,
        event_kind=event_kind,
        aggregate_seq=aggregate_seq,
        timestamp=timestamp,
        first_recv_unix_ns=first_recv_unix_ns,
        flush_unix_ns=flush_unix_ns,
        boards_present_mask=boards_present_mask,
        boards_missing_mask=boards_missing_mask,
        status_flags=status_flags,
        event_count_min=event_count_min,
        event_count_max=event_count_max,
        boards=boards,
    )


def _parse_board_chunks(
    *,
    event_body: bytes,
    source_file: Path,
    board_chunk_count: int,
) -> list[MultiBoardChunkRecord]:
    boards: list[MultiBoardChunkRecord] = []
    offset = 0
    for _board_index in range(board_chunk_count):
        chunk_header = event_body[offset : offset + BOARD_HEADER_SIZE]
        if len(chunk_header) != BOARD_HEADER_SIZE:
            raise MultiBoardDecodeError(
                f"Truncated board header in '{source_file}'."
            )
        (
            board_record_bytes,
            board_header_bytes,
            board_id,
            board_flags,
            board_event_count,
            board_timestamp,
            mode,
            hit_mask,
            hit_count,
            feature_size,
            feature_len,
            waveform_len,
            recv_unix_ns,
        ) = struct.unpack(BOARD_HEADER_FMT, chunk_header)
        board_record_bytes = int(board_record_bytes)
        board_header_bytes = int(board_header_bytes)
        if board_record_bytes < board_header_bytes:
            raise MultiBoardDecodeError(
                f"Invalid board record size in '{source_file}'."
            )
        board_body = event_body[
            offset + board_header_bytes : offset + board_record_bytes
        ]
        if len(board_body) != board_record_bytes - board_header_bytes:
            raise MultiBoardDecodeError(
                f"Truncated board payload in '{source_file}'."
            )
        feature_len = int(feature_len)
        waveform_len = int(waveform_len)
        if len(board_body) != feature_len + waveform_len:
            raise MultiBoardDecodeError(
                f"Board payload length mismatch in '{source_file}'."
            )
        boards.append(
            MultiBoardChunkRecord(
                board_id=int(board_id),
                board_flags=int(board_flags),
                event_count=int(board_event_count),
                timestamp=int(board_timestamp),
                mode=int(mode),
                hit_mask=int(hit_mask),
                hit_count=int(hit_count),
                feature_size=int(feature_size),
                feature_len=feature_len,
                waveform_len=waveform_len,
                recv_unix_ns=int(recv_unix_ns),
                feature_bytes=board_body[:feature_len],
                waveform_bytes=board_body[feature_len:],
            )
        )
        offset += board_record_bytes
    if offset != len(event_body):
        raise MultiBoardDecodeError(
            f"Unexpected trailing bytes in event record from '{source_file}'."
        )
    return boards
