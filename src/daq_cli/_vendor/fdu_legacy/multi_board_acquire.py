#!/usr/bin/env python3
"""Multi-board TCP acquisition with TCM timestamp alignment and event aggregation.

This tool aligns all ADC boards through the TCM RBCP interface, opens one TCP
stream per board, parses TCP_SENT packets, aggregates events by timestamp, and
stores complete/partial events in separate binary files with monitor output.

Example:
    python script/multi_board_acquire.py --config script/multi_board_acquire_config.example.json
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(SCRIPT_DIR, "lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

from rbcp import Rbcp, RbcpError  # type: ignore


FORMAT_NAME = "FDU_ADC_AGGR"
FORMAT_VERSION = 1
FILE_MAGIC = b"FDUAGGR1"

DEFAULT_ADC_LENGTH = 64
DEFAULT_TCP_TIMEOUT_S = 1.0
DEFAULT_RECONNECT_DELAY_S = 1.0
DEFAULT_EVENT_TIMEOUT_MS = 50
DEFAULT_MONITOR_INTERVAL_S = 1.0
DEFAULT_MONITOR_JSONL_INTERVAL_S = 5.0
DEFAULT_QUEUE_SIZE = 10000

ALIGN_CTRL_ADDR = 0x18
ALIGN_STATUS_ADDR = 0x19
ALIGN_ONLINE_MASK_ADDR = 0x1A
ALIGN_ACK_MASK_ADDR = 0x1B
ALIGN_MISSING_ACK_MASK_ADDR = 0x1C

ALIGN_CTRL_START = 0x01
ALIGN_CTRL_CLEAR = 0x02

STATUS_BUSY_BIT = 0
STATUS_DONE_STICKY_BIT = 1
STATUS_TIMEOUT_STICKY_BIT = 2
STATUS_DONE_SAMPLE_BIT = 3
STATUS_TIMEOUT_SAMPLE_BIT = 4

EVENT_FLAG_COMPLETE = 1 << 0
EVENT_FLAG_PARTIAL = 1 << 1
EVENT_FLAG_TIMEOUT_FLUSH = 1 << 2
EVENT_FLAG_EVENT_COUNT_MISMATCH = 1 << 3

BOARD_FLAG_HAS_FEATURE = 1 << 0
BOARD_FLAG_HAS_WAVEFORM = 1 << 1
BOARD_FLAG_TCP_RECONNECTED_BEFORE_FRAME = 1 << 2

MODE_HIT_WAVEFORM = 0
MODE_FULL_WAVEFORM = 1
MODE_HIT_FEATURE = 2
MODE_HIT_FEATURE_WAVEFORM = 3

FILE_HEADER_FMT = "<8sHHIQIII"
EVENT_HEADER_FMT = "<IHHQQQQIIIIQQ"
BOARD_HEADER_FMT = "<IHHIIQHHHHIIQ"
INDEX_ENTRY_FMT = "<QQQIIII"


def now_unix_ns() -> int:
    return time.time_ns()


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def ensure_dir(path: str) -> None:
    if not os.path.isdir(path):
        os.makedirs(path)


def bit_count(value: int) -> int:
    count = 0
    while value:
        count += value & 1
        value >>= 1
    return count


def status_bit(value: int, bit_index: int) -> int:
    return (value >> bit_index) & 0x1


def mask_from_board_ids(board_ids: List[int]) -> int:
    mask = 0
    for board_id in board_ids:
        mask |= 1 << board_id
    return mask


def pretty_secs(value: float) -> str:
    if value < 0:
        value = 0.0
    if value < 60.0:
        return "%.1fs" % value
    mins = int(value // 60.0)
    secs = int(value % 60.0)
    return "%dm%02ds" % (mins, secs)


@dataclass
class BoardConfig:
    board_id: int
    name: str
    ip: str
    tcp_port: int


@dataclass
class AppConfig:
    run_name_prefix: str
    run_name: Optional[str]
    output_base_dir: str
    tcm_ip: str
    tcm_rbcp_port: int
    tcm_timeout_ms: int
    tcm_command_delay_s: float
    tcm_poll_interval_s: float
    tcm_poll_timeout_s: float
    tcm_allow_start_without_ack: bool
    adc_length: int
    aggregation_key: str
    timestamp_match_window_ticks: int
    event_timeout_ms: int
    monitor_interval_s: float
    monitor_jsonl_interval_s: float
    tcp_timeout_s: float
    reconnect_delay_s: float
    recv_buffer_bytes: int
    frame_queue_size: int
    board_warn_no_data_s: float
    partial_warn_ratio: float
    reconnect_warn_count: int
    boards: List[BoardConfig]

    @classmethod
    def from_json_file(cls, path: str) -> "AppConfig":
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)

        boards = []
        for item in raw["boards"]:
            boards.append(
                BoardConfig(
                    board_id=int(item["board_id"]),
                    name=str(item["name"]),
                    ip=str(item["ip"]),
                    tcp_port=int(item.get("tcp_port", 24)),
                )
            )

        board_ids = [board.board_id for board in boards]
        if len(board_ids) != len(set(board_ids)):
            raise ValueError("board_id values must be unique")
        if any(board_id < 0 or board_id > 31 for board_id in board_ids):
            raise ValueError("board_id must stay in range 0..31 for 32-bit masks")

        return cls(
            run_name_prefix=str(raw.get("run_name_prefix", "run")),
            run_name=(
                str(raw["run_name"])
                if raw.get("run_name") not in (None, "")
                else None
            ),
            output_base_dir=str(raw.get("output_base_dir", os.path.join("out", "multi_board_acquire"))),
            tcm_ip=str(raw["tcm"]["ip"]),
            tcm_rbcp_port=int(raw["tcm"].get("rbcp_port", 4660)),
            tcm_timeout_ms=int(raw["tcm"].get("timeout_ms", 3000)),
            tcm_command_delay_s=float(raw["tcm"].get("command_delay_s", 0.02)),
            tcm_poll_interval_s=float(raw["tcm"].get("poll_interval_s", 0.05)),
            tcm_poll_timeout_s=float(raw["tcm"].get("poll_timeout_s", 2.0)),
            tcm_allow_start_without_ack=bool(raw["tcm"].get("allow_start_without_ack", False)),
            adc_length=int(raw.get("adc_length", DEFAULT_ADC_LENGTH)),
            aggregation_key=str(raw.get("aggregation_key", "timestamp")),
            timestamp_match_window_ticks=int(raw.get("timestamp_match_window_ticks", 0)),
            event_timeout_ms=int(raw.get("event_timeout_ms", DEFAULT_EVENT_TIMEOUT_MS)),
            monitor_interval_s=float(raw.get("monitor_interval_s", DEFAULT_MONITOR_INTERVAL_S)),
            monitor_jsonl_interval_s=float(raw.get("monitor_jsonl_interval_s", DEFAULT_MONITOR_JSONL_INTERVAL_S)),
            tcp_timeout_s=float(raw.get("tcp_timeout_s", DEFAULT_TCP_TIMEOUT_S)),
            reconnect_delay_s=float(raw.get("reconnect_delay_s", DEFAULT_RECONNECT_DELAY_S)),
            recv_buffer_bytes=int(raw.get("recv_buffer_bytes", 8192)),
            frame_queue_size=int(raw.get("frame_queue_size", DEFAULT_QUEUE_SIZE)),
            board_warn_no_data_s=float(raw.get("board_warn_no_data_s", 3.0)),
            partial_warn_ratio=float(raw.get("partial_warn_ratio", 0.01)),
            reconnect_warn_count=int(raw.get("reconnect_warn_count", 3)),
            boards=boards,
        )


class EventLogger:
    def __init__(self, log_path: str):
        self._lock = threading.Lock()
        self._fh = open(log_path, "a", encoding="utf-8")
        self._closed = False

    def log(self, level: str, message: str) -> None:
        line = "%s [%s] %s" % (iso_now(), level, message)
        with self._lock:
            print(line)
            if not self._closed:
                self._fh.write(line + "\n")
                self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._fh.flush()
            self._fh.close()
            self._closed = True


@dataclass
class Frame:
    board_id: int
    board_name: str
    board_ip: str
    mode: int
    event_count: int
    timestamp: int
    hit_mask: int
    feature_size: int
    feature_bytes: bytes
    waveform_bytes: bytes
    recv_unix_ns: int
    reconnect_mark: bool = False

    @property
    def hit_count(self) -> int:
        return bit_count(self.hit_mask)


@dataclass
class AggregatedEvent:
    aggregate_seq: int
    aggregation_value: int
    timestamp: int
    created_unix_ns: int
    first_recv_unix_ns: int
    flush_unix_ns: int
    frames: Dict[int, Frame]
    boards_present_mask: int
    boards_missing_mask: int
    status_flags: int
    event_count_min: int
    event_count_max: int
    missing_board_ids: List[int] = field(default_factory=list)


@dataclass
class TCMAlignSnapshot:
    status: int
    online_mask: int
    ack_mask: int
    missing_mask: int


class SharedState:
    def __init__(self, boards: List[BoardConfig]):
        self.lock = threading.Lock()
        self.start_monotonic_s = time.monotonic()
        self.run_started_unix_ns = now_unix_ns()
        self.stopping = False

        self.complete_events = 0
        self.partial_events = 0
        self.timeout_flushes = 0
        self.event_count_mismatches = 0
        self.last_complete_timestamp = 0
        self.last_complete_aggregation_value = 0
        self.last_partial_missing: List[int] = []
        self.open_bucket_count = 0

        self.board_stats: Dict[int, Dict[str, object]] = {}
        for board in boards:
            self.board_stats[board.board_id] = {
                "board_id": board.board_id,
                "name": board.name,
                "ip": board.ip,
                "connected": False,
                "reconnects": 0,
                "desyncs": 0,
                "frames_total": 0,
                "frames_since_last": 0,
                "fps": 0.0,
                "last_event_count": None,
                "last_recv_unix_ns": None,
                "last_connect_unix_ns": None,
                "last_disconnect_unix_ns": None,
                "recv_errors": 0,
                "warn_no_data_latched": False,
            }

    def mark_connected(self, board_id: int) -> None:
        with self.lock:
            stat = self.board_stats[board_id]
            stat["connected"] = True
            stat["last_connect_unix_ns"] = now_unix_ns()

    def mark_disconnected(self, board_id: int) -> None:
        with self.lock:
            stat = self.board_stats[board_id]
            stat["connected"] = False
            stat["last_disconnect_unix_ns"] = now_unix_ns()

    def mark_reconnect(self, board_id: int) -> int:
        with self.lock:
            stat = self.board_stats[board_id]
            stat["reconnects"] = int(stat["reconnects"]) + 1
            return int(stat["reconnects"])

    def mark_desync(self, board_id: int) -> None:
        with self.lock:
            stat = self.board_stats[board_id]
            stat["desyncs"] = int(stat["desyncs"]) + 1

    def mark_recv_error(self, board_id: int) -> None:
        with self.lock:
            stat = self.board_stats[board_id]
            stat["recv_errors"] = int(stat["recv_errors"]) + 1

    def record_frame(self, frame: Frame) -> None:
        with self.lock:
            stat = self.board_stats[frame.board_id]
            stat["frames_total"] = int(stat["frames_total"]) + 1
            stat["frames_since_last"] = int(stat["frames_since_last"]) + 1
            stat["last_event_count"] = frame.event_count
            stat["last_recv_unix_ns"] = frame.recv_unix_ns
            stat["warn_no_data_latched"] = False

    def update_open_bucket_count(self, count: int) -> None:
        with self.lock:
            self.open_bucket_count = count

    def record_complete_event(self, event: AggregatedEvent) -> None:
        with self.lock:
            self.complete_events += 1
            self.last_complete_timestamp = event.timestamp
            self.last_complete_aggregation_value = event.aggregation_value
            if event.status_flags & EVENT_FLAG_EVENT_COUNT_MISMATCH:
                self.event_count_mismatches += 1

    def record_partial_event(self, event: AggregatedEvent) -> None:
        with self.lock:
            self.partial_events += 1
            self.timeout_flushes += 1
            self.last_partial_missing = list(event.missing_board_ids)
            if event.status_flags & EVENT_FLAG_EVENT_COUNT_MISMATCH:
                self.event_count_mismatches += 1

    def snapshot(self) -> Dict[str, object]:
        with self.lock:
            board_stats_copy = {}
            for board_id, stat in self.board_stats.items():
                board_stats_copy[board_id] = dict(stat)
            return {
                "start_monotonic_s": self.start_monotonic_s,
                "run_started_unix_ns": self.run_started_unix_ns,
                "complete_events": self.complete_events,
                "partial_events": self.partial_events,
                "timeout_flushes": self.timeout_flushes,
                "event_count_mismatches": self.event_count_mismatches,
                "last_complete_timestamp": self.last_complete_timestamp,
                "last_complete_aggregation_value": self.last_complete_aggregation_value,
                "last_partial_missing": list(self.last_partial_missing),
                "open_bucket_count": self.open_bucket_count,
                "board_stats": board_stats_copy,
            }

    def reset_interval_counters(self) -> None:
        with self.lock:
            for stat in self.board_stats.values():
                stat["frames_since_last"] = 0


class TCMController:
    def __init__(self, config: AppConfig, logger: EventLogger):
        self.config = config
        self.logger = logger

    def _read_u8(self, bus: Rbcp, addr: int) -> int:
        data = bus.read(addr, 1)
        if len(data) != 1:
            raise RuntimeError("RBCP read returned %d bytes, expected 1" % len(data))
        return data[0]

    def _write_u8(self, bus: Rbcp, addr: int, value: int) -> None:
        bus.write(addr, bytes([value & 0xFF]))

    def _read_snapshot(self, bus: Rbcp) -> TCMAlignSnapshot:
        return TCMAlignSnapshot(
            status=self._read_u8(bus, ALIGN_STATUS_ADDR),
            online_mask=self._read_u8(bus, ALIGN_ONLINE_MASK_ADDR),
            ack_mask=self._read_u8(bus, ALIGN_ACK_MASK_ADDR),
            missing_mask=self._read_u8(bus, ALIGN_MISSING_ACK_MASK_ADDR),
        )

    def align(self) -> Tuple[bool, TCMAlignSnapshot]:
        bus = Rbcp(
            device_ip=self.config.tcm_ip,
            udp_port=self.config.tcm_rbcp_port,
            timeout=self.config.tcm_timeout_ms,
        )

        self.logger.log(
            "INFO",
            "TCM align start ip=%s port=%d" % (self.config.tcm_ip, self.config.tcm_rbcp_port),
        )

        self._write_u8(bus, ALIGN_CTRL_ADDR, ALIGN_CTRL_CLEAR)
        time.sleep(self.config.tcm_command_delay_s)
        self._write_u8(bus, ALIGN_CTRL_ADDR, ALIGN_CTRL_START)

        deadline = time.time() + self.config.tcm_poll_timeout_s
        final_snapshot = None
        while time.time() < deadline:
            snapshot = self._read_snapshot(bus)
            if status_bit(snapshot.status, STATUS_DONE_STICKY_BIT):
                final_snapshot = snapshot
                break
            if status_bit(snapshot.status, STATUS_TIMEOUT_STICKY_BIT):
                final_snapshot = snapshot
                break
            time.sleep(self.config.tcm_poll_interval_s)

        if final_snapshot is None:
            final_snapshot = self._read_snapshot(bus)

        success = (
            status_bit(final_snapshot.status, STATUS_DONE_STICKY_BIT) == 1
            and (final_snapshot.ack_mask & final_snapshot.online_mask) == final_snapshot.online_mask
        )

        self.logger.log(
            "INFO" if success else "ERROR",
            (
                "TCM align result success=%s status=0x%02X online=0x%02X ack=0x%02X missing=0x%02X"
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


class FrameParser:
    def __init__(self, adc_length: int):
        self.adc_length = adc_length

    @staticmethod
    def _u16_be(data: bytes, offset: int) -> int:
        return (data[offset] << 8) | data[offset + 1]

    @staticmethod
    def _u32_be(data: bytes, offset: int) -> int:
        return (
            (data[offset] << 24)
            | (data[offset + 1] << 16)
            | (data[offset + 2] << 8)
            | data[offset + 3]
        )

    @staticmethod
    def _u64_be(data: bytes, offset: int) -> int:
        value = 0
        for idx in range(8):
            value = (value << 8) | data[offset + idx]
        return value

    @staticmethod
    def _mode_has_feature(mode: int) -> bool:
        return mode in (MODE_HIT_FEATURE, MODE_HIT_FEATURE_WAVEFORM)

    @staticmethod
    def _mode_has_waveform(mode: int) -> bool:
        return mode in (MODE_HIT_WAVEFORM, MODE_FULL_WAVEFORM, MODE_HIT_FEATURE_WAVEFORM)

    @staticmethod
    def _mode_full_waveform(mode: int) -> bool:
        return mode == MODE_FULL_WAVEFORM

    def parse_one(self, buffer: bytearray, board: BoardConfig, reconnect_mark: bool) -> Tuple[Optional[Frame], bool]:
        if len(buffer) < 2:
            return None, False

        if buffer[0] == 0xFF and buffer[1] == 0xFF:
            header_bytes = 16
            if len(buffer) < header_bytes:
                return None, False
            packet = bytes(buffer[:header_bytes])
            event_count = self._u32_be(packet, 2)
            timestamp = self._u64_be(packet, 6)
            hit_mask = self._u16_be(packet, 14)
            hit_count = bit_count(hit_mask)
            waveform_bytes = hit_count * self.adc_length * 4
            total_bytes = header_bytes + waveform_bytes
            if len(buffer) < total_bytes:
                return None, False
            raw = bytes(buffer[:total_bytes])
            del buffer[:total_bytes]
            return (
                Frame(
                    board_id=board.board_id,
                    board_name=board.name,
                    board_ip=board.ip,
                    mode=MODE_HIT_WAVEFORM,
                    event_count=event_count,
                    timestamp=timestamp,
                    hit_mask=hit_mask,
                    feature_size=0,
                    feature_bytes=b"",
                    waveform_bytes=raw[header_bytes:],
                    recv_unix_ns=now_unix_ns(),
                    reconnect_mark=reconnect_mark,
                ),
                False,
            )

        if len(buffer) >= 3 and buffer[0] == 0xFF and buffer[1] == 0xFE and buffer[2] == 0x01:
            header_bytes = 20
            if len(buffer) < header_bytes:
                return None, False
            header = bytes(buffer[:header_bytes])
            mode = header[3]
            if mode < MODE_HIT_WAVEFORM or mode > MODE_HIT_FEATURE_WAVEFORM:
                del buffer[0]
                return None, True
            event_count = self._u32_be(header, 4)
            timestamp = self._u64_be(header, 8)
            hit_mask = self._u16_be(header, 16)
            feature_size = header[18]
            hit_count = bit_count(hit_mask)
            if self._mode_has_feature(mode):
                feature_bytes = hit_count * feature_size
            else:
                feature_bytes = 0

            if self._mode_has_waveform(mode):
                if self._mode_full_waveform(mode):
                    waveform_bytes = 16 * self.adc_length * 4
                else:
                    waveform_bytes = hit_count * self.adc_length * 4
            else:
                waveform_bytes = 0

            total_bytes = header_bytes + feature_bytes + waveform_bytes
            if len(buffer) < total_bytes:
                return None, False
            raw = bytes(buffer[:total_bytes])
            del buffer[:total_bytes]
            return (
                Frame(
                    board_id=board.board_id,
                    board_name=board.name,
                    board_ip=board.ip,
                    mode=mode,
                    event_count=event_count,
                    timestamp=timestamp,
                    hit_mask=hit_mask,
                    feature_size=feature_size,
                    feature_bytes=raw[header_bytes : header_bytes + feature_bytes],
                    waveform_bytes=raw[header_bytes + feature_bytes :],
                    recv_unix_ns=now_unix_ns(),
                    reconnect_mark=reconnect_mark,
                ),
                False,
            )

        del buffer[0]
        return None, True


class DataWriter:
    def __init__(self, config: AppConfig, run_dir: str, logger: EventLogger):
        self.config = config
        self.run_dir = run_dir
        self.logger = logger
        self.complete_path = os.path.join(run_dir, "complete_events.dat")
        self.partial_path = os.path.join(run_dir, "partial_events.dat")
        self.index_path = os.path.join(run_dir, "complete_events.idx")
        self.monitor_jsonl_path = os.path.join(run_dir, "monitor.jsonl")

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

    def _write_file_header(self, fh) -> None:
        payload = struct.pack(
            FILE_HEADER_FMT,
            FILE_MAGIC,
            struct.calcsize(FILE_HEADER_FMT),
            FORMAT_VERSION,
            0,
            now_unix_ns(),
            0,
            len(self.config.boards),
            self.config.adc_length,
        )
        fh.write(payload)
        fh.flush()

    def _build_board_record(self, frame: Frame) -> bytes:
        board_flags = 0
        if frame.feature_bytes:
            board_flags |= BOARD_FLAG_HAS_FEATURE
        if frame.waveform_bytes:
            board_flags |= BOARD_FLAG_HAS_WAVEFORM
        if frame.reconnect_mark:
            board_flags |= BOARD_FLAG_TCP_RECONNECTED_BEFORE_FRAME

        feature_len = len(frame.feature_bytes)
        waveform_len = len(frame.waveform_bytes)
        header_bytes = struct.calcsize(BOARD_HEADER_FMT)
        total_bytes = header_bytes + feature_len + waveform_len
        payload = struct.pack(
            BOARD_HEADER_FMT,
            total_bytes,
            header_bytes,
            frame.board_id,
            board_flags,
            frame.event_count,
            frame.timestamp,
            frame.mode,
            frame.hit_mask,
            frame.hit_count,
            16,
            feature_len,
            waveform_len,
            frame.recv_unix_ns,
        )
        return payload + frame.feature_bytes + frame.waveform_bytes

    def _build_event_record(self, event: AggregatedEvent) -> bytes:
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

    def write_event(self, event: AggregatedEvent) -> None:
        payload = self._build_event_record(event)
        with self._lock:
            if event.status_flags & EVENT_FLAG_COMPLETE:
                file_offset = self._complete_fh.tell()
                self._complete_fh.write(payload)
                self._complete_event_counter += 1
                index_payload = struct.pack(
                    INDEX_ENTRY_FMT,
                    event.aggregate_seq,
                    event.timestamp,
                    file_offset,
                    len(payload),
                    event.boards_present_mask,
                    event.status_flags,
                    0,
                )
                self._index_fh.write(index_payload)
                if self._complete_event_counter % 16 == 0:
                    self._complete_fh.flush()
                    self._index_fh.flush()
            else:
                self._partial_fh.write(payload)
                self._partial_event_counter += 1
                if self._partial_event_counter % 16 == 0:
                    self._partial_fh.flush()

    def write_monitor_snapshot(self, snapshot: Dict[str, object]) -> None:
        with self._lock:
            self._monitor_fh.write(json.dumps(snapshot, ensure_ascii=True, sort_keys=True) + "\n")
            self._monitor_fh.flush()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._complete_fh.flush()
            self._partial_fh.flush()
            self._index_fh.flush()
            self._monitor_fh.flush()
            self._complete_fh.close()
            self._partial_fh.close()
            self._index_fh.close()
            self._monitor_fh.close()
            self._closed = True


class BoardReceiver(threading.Thread):
    def __init__(
        self,
        board: BoardConfig,
        config: AppConfig,
        parser: FrameParser,
        frame_queue: "queue.Queue[Frame]",
        state: SharedState,
        logger: EventLogger,
        stop_event: threading.Event,
    ):
        super().__init__(daemon=True, name="recv_%s" % board.name)
        self.board = board
        self.config = config
        self.parser = parser
        self.frame_queue = frame_queue
        self.state = state
        self.logger = logger
        self.stop_event = stop_event
        self._mark_next_frame_reconnect = False

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self._run_session()
            except Exception as exc:
                self.state.mark_recv_error(self.board.board_id)
                self.logger.log("WARN", "board=%s receiver exception=%s" % (self.board.name, str(exc)))
            if self.stop_event.is_set():
                break
            reconnects = self.state.mark_reconnect(self.board.board_id)
            self._mark_next_frame_reconnect = True
            self.state.mark_disconnected(self.board.board_id)
            if reconnects >= self.config.reconnect_warn_count:
                self.logger.log("WARN", "board=%s reconnect_count=%d" % (self.board.name, reconnects))
            time.sleep(self.config.reconnect_delay_s)

    def _run_session(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.config.tcp_timeout_s)
        self.logger.log("INFO", "board=%s connect %s:%d" % (self.board.name, self.board.ip, self.board.tcp_port))
        sock.connect((self.board.ip, self.board.tcp_port))
        self.state.mark_connected(self.board.board_id)
        buffer = bytearray()

        try:
            while not self.stop_event.is_set():
                try:
                    chunk = sock.recv(self.config.recv_buffer_bytes)
                except socket.timeout:
                    continue

                if not chunk:
                    raise ConnectionError("socket closed by peer")
                buffer.extend(chunk)

                while not self.stop_event.is_set():
                    frame, desync = self.parser.parse_one(buffer, self.board, self._mark_next_frame_reconnect)
                    if desync:
                        self.state.mark_desync(self.board.board_id)
                        continue
                    if frame is None:
                        break
                    self._mark_next_frame_reconnect = False
                    self.state.record_frame(frame)
                    self.frame_queue.put(frame)
        finally:
            sock.close()


class EventAggregator(threading.Thread):
    def __init__(
        self,
        boards: List[BoardConfig],
        config: AppConfig,
        frame_queue: "queue.Queue[Frame]",
        writer: DataWriter,
        state: SharedState,
        logger: EventLogger,
        stop_event: threading.Event,
    ):
        super().__init__(daemon=True, name="event_aggregator")
        self.boards = boards
        self.config = config
        self.frame_queue = frame_queue
        self.writer = writer
        self.state = state
        self.logger = logger
        self.stop_event = stop_event
        self.expected_board_ids = [board.board_id for board in boards]
        self.expected_board_mask = mask_from_board_ids(self.expected_board_ids)
        self.event_timeout_s = self.config.event_timeout_ms / 1000.0
        self.next_seq = 1
        self.buckets: Dict[int, Dict[str, object]] = {}

    def _frame_key(self, frame: Frame) -> int:
        if self.config.aggregation_key == "event_count":
            return frame.event_count
        return frame.timestamp

    def _find_timestamp_bucket_key(self, timestamp: int) -> Optional[int]:
        for bucket_key in self.buckets.keys():
            if abs(bucket_key - timestamp) <= self.config.timestamp_match_window_ticks:
                return bucket_key
        return None

    def run(self) -> None:
        while not self.stop_event.is_set() or not self.frame_queue.empty():
            self._flush_expired(force=False)
            try:
                frame = self.frame_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            self._handle_frame(frame)

        self._flush_expired(force=True)
        self.state.update_open_bucket_count(0)

    def _new_bucket(self, frame: Frame) -> Dict[str, object]:
        return {
            "aggregation_value": self._frame_key(frame),
            "timestamp": frame.timestamp,
            "created_monotonic_s": time.monotonic(),
            "first_recv_unix_ns": frame.recv_unix_ns,
            "frames": {frame.board_id: frame},
        }

    def _handle_frame(self, frame: Frame) -> None:
        bucket_key = self._frame_key(frame)
        if self.config.aggregation_key == "timestamp":
            matched_key = self._find_timestamp_bucket_key(frame.timestamp)
            if matched_key is not None:
                bucket_key = matched_key
        bucket = self.buckets.get(bucket_key)
        if bucket is None:
            bucket = self._new_bucket(frame)
            self.buckets[bucket_key] = bucket
        else:
            frames = bucket["frames"]  # type: ignore[assignment]
            if frame.board_id in frames:
                self.logger.log(
                    "WARN",
                    "duplicate frame aggregation=%d board=%s old_event=%s new_event=%s"
                    % (
                        bucket_key,
                        frame.board_name,
                        str(frames[frame.board_id].event_count),
                        str(frame.event_count),
                    ),
                )
            frames[frame.board_id] = frame

        self.state.update_open_bucket_count(len(self.buckets))
        if self._bucket_complete(bucket):
            event = self._finalize_bucket(bucket_key, complete=True)
            self.writer.write_event(event)
            self.state.record_complete_event(event)

    def _bucket_complete(self, bucket: Dict[str, object]) -> bool:
        frames = bucket["frames"]  # type: ignore[assignment]
        return len(frames) == len(self.expected_board_ids)

    def _flush_expired(self, force: bool) -> None:
        now_s = time.monotonic()
        expired_keys = []
        for bucket_key, bucket in self.buckets.items():
            age_s = now_s - float(bucket["created_monotonic_s"])
            if force or age_s >= self.event_timeout_s:
                expired_keys.append(bucket_key)

        for bucket_key in sorted(expired_keys):
            event = self._finalize_bucket(bucket_key, complete=False)
            self.writer.write_event(event)
            self.state.record_partial_event(event)
            self.logger.log(
                "WARN",
                "partial event aggregation=%d timestamp=%d missing=%s"
                % (event.aggregation_value, event.timestamp, ",".join(str(item) for item in event.missing_board_ids)),
            )

        if expired_keys:
            self.state.update_open_bucket_count(len(self.buckets))

    def _finalize_bucket(self, bucket_key: int, complete: bool) -> AggregatedEvent:
        bucket = self.buckets.pop(bucket_key)
        frames: Dict[int, Frame] = bucket["frames"]  # type: ignore[assignment]
        present_ids = sorted(frames.keys())
        missing_ids = [board_id for board_id in self.expected_board_ids if board_id not in frames]
        present_mask = mask_from_board_ids(present_ids)
        missing_mask = self.expected_board_mask & (~present_mask)
        status_flags = EVENT_FLAG_COMPLETE if complete else (EVENT_FLAG_PARTIAL | EVENT_FLAG_TIMEOUT_FLUSH)
        event_counts = {frame.event_count for frame in frames.values()}
        if len(event_counts) > 1:
            status_flags |= EVENT_FLAG_EVENT_COUNT_MISMATCH
        timestamps = [frame.timestamp for frame in frames.values()]

        event = AggregatedEvent(
            aggregate_seq=self.next_seq,
            aggregation_value=bucket_key,
            timestamp=min(timestamps) if timestamps else 0,
            created_unix_ns=int(bucket["first_recv_unix_ns"]),
            first_recv_unix_ns=int(bucket["first_recv_unix_ns"]),
            flush_unix_ns=now_unix_ns(),
            frames=dict(frames),
            boards_present_mask=present_mask,
            boards_missing_mask=missing_mask,
            status_flags=status_flags,
            event_count_min=min(event_counts) if event_counts else 0,
            event_count_max=max(event_counts) if event_counts else 0,
            missing_board_ids=missing_ids,
        )
        self.next_seq += 1
        return event


class MonitorThread(threading.Thread):
    def __init__(
        self,
        config: AppConfig,
        state: SharedState,
        writer: DataWriter,
        logger: EventLogger,
        stop_event: threading.Event,
    ):
        super().__init__(daemon=True, name="monitor")
        self.config = config
        self.state = state
        self.writer = writer
        self.logger = logger
        self.stop_event = stop_event
        self._last_jsonl_s = 0.0

    def run(self) -> None:
        last_tick = time.monotonic()
        while not self.stop_event.is_set():
            time.sleep(self.config.monitor_interval_s)
            now_s = time.monotonic()
            snapshot = self.state.snapshot()
            interval_s = max(now_s - last_tick, 1e-6)
            last_tick = now_s
            self._emit(snapshot, interval_s, now_s)
            self.state.reset_interval_counters()

    def _emit(self, snapshot: Dict[str, object], interval_s: float, now_s: float) -> None:
        elapsed_s = now_s - float(snapshot["start_monotonic_s"])
        complete = int(snapshot["complete_events"])
        partial = int(snapshot["partial_events"])
        total = complete + partial
        partial_ratio = (float(partial) / float(total)) if total else 0.0
        open_buckets = int(snapshot["open_bucket_count"])
        last_complete_timestamp = int(snapshot["last_complete_timestamp"])
        last_complete_aggregation_value = int(snapshot["last_complete_aggregation_value"])
        last_partial_missing = snapshot["last_partial_missing"]
        board_stats = snapshot["board_stats"]

        monitor_head = (
            "[MON] elapsed=%s complete=%d partial=%d partial_ratio=%.2f%% open_buckets=%d last_complete_key=%d last_complete_ts=%d"
            % (
                pretty_secs(elapsed_s),
                complete,
                partial,
                partial_ratio * 100.0,
                open_buckets,
                last_complete_aggregation_value,
                last_complete_timestamp,
            )
        )
        self.logger.log("INFO", monitor_head)
        if last_partial_missing:
            self.logger.log("INFO", "[MON] last_partial_missing=%s" % ",".join(str(item) for item in last_partial_missing))

        now_ns = now_unix_ns()
        json_snapshot = {
            "ts": iso_now(),
            "elapsed_s": elapsed_s,
            "complete_events": complete,
            "partial_events": partial,
            "partial_ratio": partial_ratio,
            "aggregation_key": self.config.aggregation_key,
            "timestamp_match_window_ticks": self.config.timestamp_match_window_ticks,
            "open_bucket_count": open_buckets,
            "last_complete_aggregation_value": last_complete_aggregation_value,
            "last_complete_timestamp": last_complete_timestamp,
            "last_partial_missing": last_partial_missing,
            "event_count_mismatches": int(snapshot["event_count_mismatches"]),
            "boards": {},
        }

        for board_id in sorted(board_stats.keys()):
            stat = board_stats[board_id]
            frames_since_last = int(stat["frames_since_last"])
            fps = float(frames_since_last) / interval_s
            name = str(stat["name"])
            connected = bool(stat["connected"])
            last_recv_ns = stat["last_recv_unix_ns"]
            silent_s = None
            if last_recv_ns is not None:
                silent_s = max(0.0, (now_ns - int(last_recv_ns)) / 1.0e9)
            warn_tokens = []
            if silent_s is not None and silent_s >= self.config.board_warn_no_data_s:
                warn_tokens.append("NO_DATA")
            if int(stat["reconnects"]) >= self.config.reconnect_warn_count:
                warn_tokens.append("RECONNECT")
            if partial_ratio >= self.config.partial_warn_ratio:
                warn_tokens.append("PARTIAL_RATIO")

            warn_suffix = ""
            if warn_tokens:
                warn_suffix = " warn=%s" % ",".join(warn_tokens)

            line = (
                "[MON] %s conn=%s fps=%.1f total=%d last_ev=%s desync=%d reconnect=%d silent=%s%s"
                % (
                    name,
                    "up" if connected else "down",
                    fps,
                    int(stat["frames_total"]),
                    str(stat["last_event_count"]),
                    int(stat["desyncs"]),
                    int(stat["reconnects"]),
                    "n/a" if silent_s is None else pretty_secs(silent_s),
                    warn_suffix,
                )
            )
            self.logger.log("INFO", line)

            json_snapshot["boards"][name] = {
                "board_id": board_id,
                "connected": connected,
                "fps": fps,
                "frames_total": int(stat["frames_total"]),
                "last_event_count": stat["last_event_count"],
                "desyncs": int(stat["desyncs"]),
                "reconnects": int(stat["reconnects"]),
                "recv_errors": int(stat["recv_errors"]),
                "silent_s": silent_s,
                "warn_tokens": warn_tokens,
            }

        if now_s - self._last_jsonl_s >= self.config.monitor_jsonl_interval_s:
            self.writer.write_monitor_snapshot(json_snapshot)
            self._last_jsonl_s = now_s


class AcquisitionApp:
    def __init__(self, config: AppConfig, config_path: str):
        self.config = config
        self.config_path = config_path
        self.stop_event = threading.Event()
        self.run_dir = self._make_run_dir()
        self.logger = EventLogger(os.path.join(self.run_dir, "log.txt"))
        self.writer = DataWriter(config, self.run_dir, self.logger)
        self.state = SharedState(config.boards)
        self.meta_start_time = iso_now()
        self.align_snapshot: Optional[TCMAlignSnapshot] = None
        self.aligned = False
        self._started = False
        self._stopped = False
        self.parser = FrameParser(config.adc_length)
        self.frame_queue: "queue.Queue[Frame]" = queue.Queue(maxsize=config.frame_queue_size)
        self.tcm = TCMController(config, self.logger)
        self.receivers = [
            BoardReceiver(board, config, self.parser, self.frame_queue, self.state, self.logger, self.stop_event)
            for board in config.boards
        ]
        self.aggregator = EventAggregator(
            config.boards, config, self.frame_queue, self.writer, self.state, self.logger, self.stop_event
        )
        self.monitor = MonitorThread(config, self.state, self.writer, self.logger, self.stop_event)

    def _make_run_dir(self) -> str:
        ensure_dir(self.config.output_base_dir)
        run_name = self.config.run_name
        if not run_name:
            run_name = "%s_%s" % (
                self.config.run_name_prefix,
                time.strftime("%Y%m%d_%H%M%S", time.localtime()),
            )
        run_dir = os.path.join(self.config.output_base_dir, run_name)
        ensure_dir(run_dir)
        return run_dir

    def _write_run_meta(self, status: str, align_snapshot: Optional[TCMAlignSnapshot]) -> None:
        meta = {
            "format_name": FORMAT_NAME,
            "format_version": FORMAT_VERSION,
            "status": status,
            "config_path": self.config_path,
            "run_dir": self.run_dir,
            "start_time": self.meta_start_time,
            "stop_time": iso_now() if status in ("stopped", "align_failed") else None,
            "tcm_ip": self.config.tcm_ip,
            "tcm_rbcp_port": self.config.tcm_rbcp_port,
            "tcm_allow_start_without_ack": self.config.tcm_allow_start_without_ack,
            "aggregation_key": self.config.aggregation_key,
            "event_timeout_ms": self.config.event_timeout_ms,
            "timestamp_match_window_ticks": self.config.timestamp_match_window_ticks,
            "adc_length": self.config.adc_length,
            "boards_expected": [
                {
                    "board_id": board.board_id,
                    "name": board.name,
                    "ip": board.ip,
                    "tcp_port": board.tcp_port,
                }
                for board in self.config.boards
            ],
        }
        if align_snapshot is not None:
            meta["align_snapshot"] = {
                "status": align_snapshot.status,
                "online_mask": align_snapshot.online_mask,
                "ack_mask": align_snapshot.ack_mask,
                "missing_mask": align_snapshot.missing_mask,
            }
        meta_path = os.path.join(self.run_dir, "run_meta.json")
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")

    def start(self) -> None:
        self._write_run_meta("created", None)
        success, snapshot = self.tcm.align()
        self.align_snapshot = snapshot
        effective_success = success or self.config.tcm_allow_start_without_ack
        if success:
            meta_status = "aligned"
        elif self.config.tcm_allow_start_without_ack:
            meta_status = "aligned_ack_bypassed"
        else:
            meta_status = "align_failed"
        self._write_run_meta(meta_status, snapshot)
        if not effective_success:
            raise RuntimeError("TCM align failed")
        if not success and self.config.tcm_allow_start_without_ack:
            self.logger.log("WARN", "TCM align failed but continuing because allow_start_without_ack=true")

        self.aligned = True
        self.logger.log("INFO", "run_dir=%s" % self.run_dir)
        self.aggregator.start()
        self.monitor.start()
        for receiver in self.receivers:
            receiver.start()
        self._started = True
        self.logger.log("INFO", "acquisition started boards=%d" % len(self.receivers))

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.stop_event.set()
        for receiver in self.receivers:
            if receiver.ident is not None:
                receiver.join(timeout=2.0)
        if self.aggregator.ident is not None:
            self.aggregator.join(timeout=2.0)
        if self.monitor.ident is not None:
            self.monitor.join(timeout=2.0)
        final_status = "stopped" if self.aligned else "align_failed"
        self._write_run_meta(final_status, self.align_snapshot)
        self.writer.close()
        self.logger.log("INFO", "acquisition stopped")
        self.logger.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Multi-board TCP acquisition with TCM timestamp alignment.")
    parser.add_argument(
        "--config",
        default=os.path.join("script", "multi_board_acquire_config.example.json"),
        help="JSON configuration file path",
    )
    return parser.parse_args()


def install_signal_handlers(app: AcquisitionApp) -> None:
    def _handle(_signum, _frame) -> None:
        app.logger.log("INFO", "stop signal received")
        app.stop_event.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


def main() -> int:
    args = parse_args()
    config = AppConfig.from_json_file(args.config)
    app = AcquisitionApp(config, os.path.abspath(args.config))
    install_signal_handlers(app)

    try:
        app.start()
        while not app.stop_event.is_set():
            time.sleep(0.5)
        return 0
    except KeyboardInterrupt:
        app.logger.log("INFO", "keyboard interrupt")
        return 0
    except (RbcpError, OSError, RuntimeError, ValueError) as exc:
        app.logger.log("ERROR", str(exc))
        return 1
    finally:
        app.stop()


if __name__ == "__main__":
    raise SystemExit(main())
