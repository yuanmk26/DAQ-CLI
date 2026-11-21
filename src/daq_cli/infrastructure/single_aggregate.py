"""Single-board aggregate storage (multi-board-like format, no partial file).

A single-board run has one board chunk per event, so it reuses the
``FDU_ADC_AGGR`` v2 writer but disables the partial stream and the multi-board
monitor file.  Rate logging is handled separately by ``RateLogRecorder``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from daq_cli.infrastructure.multi_board_acquire.config import MultiBoardConfig
from daq_cli.infrastructure.multi_board_acquire.constants import (
    EVENT_FLAG_COMPLETE,
    FORMAT_NAME,
    FORMAT_VERSION,
)
from daq_cli.infrastructure.multi_board_acquire.frames import (
    MultiBoardFrame,
    frame_from_fields,
)
from daq_cli.infrastructure.multi_board_acquire.writer import MultiBoardDataWriter

if TYPE_CHECKING:  # pragma: no cover - typing only
    from daq_cli.infrastructure.adapters.legacy_capture_runner import (
        TcpSentHeaderFields,
    )


@dataclass(slots=True)
class SingleAggregateEvent:
    """Minimal event object accepted by ``MultiBoardDataWriter.write_event``."""

    frames: dict[int, MultiBoardFrame]
    aggregate_seq: int
    timestamp: int
    first_recv_unix_ns: int
    flush_unix_ns: int
    boards_present_mask: int
    boards_missing_mask: int
    status_flags: int
    event_count_min: int
    event_count_max: int


class SingleBoardAggregateWriter:
    """Write ``complete_events.dat`` + ``complete_events.idx`` for one board."""

    def __init__(self, run_dir: Path, device: Any, adc_length: int) -> None:
        self.run_dir = Path(run_dir)
        board_id = int(getattr(device, "board_id", 0) or 0)
        if board_id < 0 or board_id > 31:
            raise ValueError("single-board board_id must stay in range 0..31")
        self._board = MultiBoardConfig(
            board_id=board_id,
            name=str(getattr(device, "name", "acquire")),
            ip=str(getattr(device, "ip", "")),
            tcp_port=int(getattr(device, "tcp_port", 24) or 24),
        )
        config = SimpleNamespace(
            boards=[self._board],
            adc_length=int(adc_length),
        )
        self._writer = MultiBoardDataWriter(
            config,
            self.run_dir,
            partial_enabled=False,
            monitor_enabled=False,
        )
        self.complete_path = self._writer.complete_path
        self.index_path = self._writer.index_path
        self._sequence = 0

    def write(
        self,
        fields: "TcpSentHeaderFields",
        *,
        recv_unix_ns: int | None = None,
    ) -> None:
        received_ns = (
            int(recv_unix_ns) if recv_unix_ns is not None else time.time_ns()
        )
        frame = frame_from_fields(
            fields,
            self._board,
            recv_unix_ns=received_ns,
        )
        event = SingleAggregateEvent(
            frames={frame.board_id: frame},
            aggregate_seq=self._sequence,
            timestamp=frame.timestamp,
            first_recv_unix_ns=received_ns,
            flush_unix_ns=time.time_ns(),
            boards_present_mask=1 << frame.board_id,
            boards_missing_mask=0,
            status_flags=EVENT_FLAG_COMPLETE,
            event_count_min=frame.event_count,
            event_count_max=frame.event_count,
        )
        self._writer.write_event(event)
        self._sequence += 1

    def close(self) -> None:
        self._writer.close()

    @property
    def events_written(self) -> int:
        return self._sequence


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _device_payload(device: Any) -> dict[str, object]:
    return {
        "name": str(getattr(device, "name", "acquire")),
        "ip": str(getattr(device, "ip", "")),
        "tcp_port": int(getattr(device, "tcp_port", 24) or 24),
        "rbcp_port": int(getattr(device, "rbcp_port", 4660) or 4660),
        "board_id": int(getattr(device, "board_id", 0) or 0),
    }


def write_single_run_meta(
    path: Path,
    *,
    run_dir: Path,
    device: Any,
    storage_mode: str,
    send_mode: int,
    adc_length: int,
    requested_events: int | None,
    duration_s: float | None = None,
    captured_events: int,
    status: str,
    start_time: str,
    stop_time: str | None,
    rate_interval_s: float,
    complete_events_path: Path | None = None,
    complete_events_index_path: Path | None = None,
    rate_csv_path: Path | None = None,
    monitor_jsonl_path: Path | None = None,
    rate_summary: dict[str, object] | None = None,
) -> None:
    """Write the single-board run metadata in a multi-board-like shape."""
    device_payload = _device_payload(device)
    payload: dict[str, object] = {
        "format_name": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "storage_mode": storage_mode,
        "aggregation_key": "none",
        "device": device_payload,
        "boards_expected": [device_payload],
        "send_mode": int(send_mode),
        "adc_length": int(adc_length),
        "requested_events": requested_events,
        **({"requested_duration_s": duration_s} if duration_s is not None else {}),
        "captured_events": int(captured_events),
        "status": status,
        "start_time": start_time,
        "stop_time": stop_time,
        "rate_interval_s": float(rate_interval_s),
        "run_dir": str(run_dir),
        "complete_events_path": (
            str(complete_events_path) if complete_events_path is not None else None
        ),
        "complete_events_index_path": (
            str(complete_events_index_path)
            if complete_events_index_path is not None
            else None
        ),
        "rate_csv_path": str(rate_csv_path) if rate_csv_path is not None else None,
        "monitor_jsonl_path": (
            str(monitor_jsonl_path) if monitor_jsonl_path is not None else None
        ),
    }
    if rate_summary is not None:
        payload["rate_summary"] = rate_summary
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "SingleAggregateEvent",
    "SingleBoardAggregateWriter",
    "write_single_run_meta",
]
