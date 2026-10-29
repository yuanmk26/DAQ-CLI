"""Aggregated event file writer (native).

On-disk layout is unchanged from the legacy writer:

``complete_events.dat`` / ``partial_events.dat``
    FILE_HEADER_FMT then a sequence of EVENT_HEADER_FMT headers each followed by
    one BOARD_HEADER_FMT_V2 chunk per present board, in ascending board id.
``complete_events.idx``
    INDEX_ENTRY_FMT per complete event, no file header.
``monitor.jsonl``
    one JSON object per monitor snapshot, appended.

The file headers are written at construction time (so an interrupted run still
leaves a parseable 36-byte header), and both data files plus the index are
flushed every :data:`WRITER_FLUSH_EVERY` records.
"""

from __future__ import annotations

import json
import struct
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from daq_cli.infrastructure.multi_board_acquire.clock import MultiBoardClock, SYSTEM_CLOCK
from daq_cli.infrastructure.multi_board_acquire.constants import (
    BOARD_CHUNK_CHANNEL_COUNT,
    BOARD_FLAG_HAS_FEATURE,
    BOARD_FLAG_HAS_FINE,
    BOARD_FLAG_HAS_WAVEFORM,
    BOARD_FLAG_TCP_RECONNECTED_BEFORE_FRAME,
    BOARD_HEADER_FMT_V2,
    EVENT_FLAG_COMPLETE,
    EVENT_HEADER_FMT,
    FILE_HEADER_FMT,
    FILE_MAGIC,
    FORMAT_NAME,
    FORMAT_VERSION,
    INDEX_ENTRY_FMT,
    WRITER_FLUSH_EVERY,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from daq_cli.infrastructure.multi_board_acquire.config import MultiBoardAppConfig
    from daq_cli.infrastructure.multi_board_acquire.frames import MultiBoardFrame

COMPLETE_EVENTS_NAME = "complete_events.dat"
PARTIAL_EVENTS_NAME = "partial_events.dat"
INDEX_NAME = "complete_events.idx"
MONITOR_JSONL_NAME = "monitor.jsonl"


class MultiBoardDataWriter:
    """Thread-safe writer for aggregated multi-board events."""

    def __init__(
        self,
        config: "MultiBoardAppConfig",
        run_dir: str | Path,
        logger=None,
        *,
        clock: MultiBoardClock = SYSTEM_CLOCK,
    ) -> None:
        self.config = config
        self.run_dir = Path(run_dir)
        self.logger = logger
        self._clock = clock

        self.complete_path = self.run_dir / COMPLETE_EVENTS_NAME
        self.partial_path = self.run_dir / PARTIAL_EVENTS_NAME
        self.index_path = self.run_dir / INDEX_NAME
        self.monitor_jsonl_path = self.run_dir / MONITOR_JSONL_NAME

        self._lock = threading.Lock()
        self._complete_fh = open(self.complete_path, "wb")
        self._partial_fh = open(self.partial_path, "wb")
        self._index_fh = open(self.index_path, "wb")
        self._monitor_fh = open(self.monitor_jsonl_path, "a", encoding="utf-8")
        self._complete_event_counter = 0
        self._partial_event_counter = 0
        self._closed = False

        self._write_file_header(self._complete_fh)
        self._write_file_header(self._partial_fh)

    # ------------------------------------------------------------- file header

    def _write_file_header(self, fh) -> None:
        payload = struct.pack(
            FILE_HEADER_FMT,
            FILE_MAGIC,
            struct.calcsize(FILE_HEADER_FMT),
            FORMAT_VERSION,
            0,
            self._clock.unix_ns(),
            0,
            len(self.config.boards),
            self.config.adc_length,
        )
        fh.write(payload)
        fh.flush()

    # ------------------------------------------------------------ board chunks

    def _build_board_record(self, frame: "MultiBoardFrame") -> bytes:
        board_flags = 0
        if frame.feature_len:
            board_flags |= BOARD_FLAG_HAS_FEATURE
        if frame.waveform_len:
            board_flags |= BOARD_FLAG_HAS_WAVEFORM
        if frame.reconnect_mark:
            board_flags |= BOARD_FLAG_TCP_RECONNECTED_BEFORE_FRAME
        if frame.format_version >= 1:
            board_flags |= BOARD_FLAG_HAS_FINE

        header_bytes = struct.calcsize(BOARD_HEADER_FMT_V2)
        total_bytes = header_bytes + frame.feature_len + frame.waveform_len
        payload = struct.pack(
            BOARD_HEADER_FMT_V2,
            total_bytes,
            header_bytes,
            frame.board_id,
            board_flags,
            frame.event_count,
            frame.timestamp,
            frame.mode,
            frame.hit_mask,
            frame.hit_count,
            # The legacy writer hard-codes 16 here regardless of the real
            # feature record length; the reader recovers the real value as
            # feature_len // hit_count. Reproduced verbatim for byte parity.
            BOARD_CHUNK_CHANNEL_COUNT,
            frame.feature_len,
            frame.waveform_len,
            frame.recv_unix_ns,
            frame.crossing_fine,
            frame.accept_fine,
        )
        return payload + frame.feature_bytes + frame.waveform_bytes

    def _build_event_record(self, event) -> bytes:
        board_chunks = []
        counts = []
        for board_id in sorted(event.frames.keys()):
            frame = event.frames[board_id]
            board_chunks.append(self._build_board_record(frame))
            counts.append(frame.event_count)

        header_bytes = struct.calcsize(EVENT_HEADER_FMT)
        record_bytes = header_bytes + sum(len(chunk) for chunk in board_chunks)
        event_count_min = min(counts) if counts else 0
        event_count_max = max(counts) if counts else 0
        header = struct.pack(
            EVENT_HEADER_FMT,
            record_bytes,
            header_bytes,
            len(board_chunks),
            event.aggregate_seq,
            event.timestamp,
            event.first_recv_unix_ns,
            event.flush_unix_ns,
            event.boards_present_mask,
            event.boards_missing_mask,
            event.status_flags,
            0,
            event_count_min,
            event_count_max,
        )
        return header + b"".join(board_chunks)

    # ------------------------------------------------------------------ writes

    def write_event(self, event) -> None:
        payload = self._build_event_record(event)
        with self._lock:
            if event.status_flags & EVENT_FLAG_COMPLETE:
                file_offset = self._complete_fh.tell()
                self._complete_fh.write(payload)
                self._complete_event_counter += 1
                self._index_fh.write(
                    struct.pack(
                        INDEX_ENTRY_FMT,
                        event.aggregate_seq,
                        event.timestamp,
                        file_offset,
                        len(payload),
                        event.boards_present_mask,
                        event.status_flags,
                        0,
                    )
                )
                if self._complete_event_counter % WRITER_FLUSH_EVERY == 0:
                    self._complete_fh.flush()
                    self._index_fh.flush()
            else:
                self._partial_fh.write(payload)
                self._partial_event_counter += 1
                if self._partial_event_counter % WRITER_FLUSH_EVERY == 0:
                    self._partial_fh.flush()

    def write_monitor_snapshot(self, snapshot: dict) -> None:
        with self._lock:
            self._monitor_fh.write(
                json.dumps(snapshot, ensure_ascii=True, sort_keys=True) + "\n"
            )
            self._monitor_fh.flush()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            for fh in (
                self._complete_fh,
                self._partial_fh,
                self._index_fh,
                self._monitor_fh,
            ):
                fh.flush()
                fh.close()
            self._closed = True


__all__ = [
    "COMPLETE_EVENTS_NAME",
    "FORMAT_NAME",
    "INDEX_NAME",
    "MONITOR_JSONL_NAME",
    "MultiBoardDataWriter",
    "PARTIAL_EVENTS_NAME",
]
