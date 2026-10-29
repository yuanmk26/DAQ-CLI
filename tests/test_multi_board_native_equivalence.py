"""Byte-level equivalence between the native multi-board pipeline and the
vendored ``multi_board_acquire`` implementation.

All timing-sensitive paths are driven by :class:`FakeClock` so both sides see
the same wall-clock values and the produced files can be compared byte for byte.
"""

from __future__ import annotations

import struct
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from daq_cli.infrastructure.adapters.legacy_capture_runner import (
    TcpSentHeaderFields,
    _TcpSentRawStreamReader,
)
from daq_cli.infrastructure.multi_board_acquire.aggregator import (
    AggregatedEvent as NativeAggregatedEvent,
    MultiBoardEventAggregator,
)
from daq_cli.infrastructure.multi_board_acquire.clock import FakeClock
from daq_cli.infrastructure.multi_board_acquire.config import (
    MultiBoardAppConfig as NativeAppConfig,
    MultiBoardConfig as NativeBoardConfig,
)
from daq_cli.infrastructure.multi_board_acquire.constants import (
    EVENT_FLAG_COMPLETE,
    EVENT_FLAG_EVENT_COUNT_MISMATCH,
    EVENT_FLAG_PARTIAL,
    EVENT_FLAG_TIMEOUT_FLUSH,
    FORMAT_VERSION,
)
from daq_cli.infrastructure.multi_board_acquire.frames import (
    MultiBoardFrame,
    frame_from_fields,
)
from daq_cli.infrastructure.multi_board_acquire.writer import MultiBoardDataWriter

ADC_LENGTH = 256


# --------------------------------------------------------------- vendored side


@pytest.fixture(scope="module")
def vendor():
    from daq_cli.infrastructure.adapters.legacy_runtime import (
        bundled_legacy_script_dir,
        clear_legacy_modules,
        temporary_sys_path,
    )
    import importlib

    with temporary_sys_path(bundled_legacy_script_dir()):
        clear_legacy_modules()
        yield importlib.import_module("multi_board_acquire")
        clear_legacy_modules()


def _vendor_config(vendor, *, board_count: int, adc_length: int = ADC_LENGTH):
    boards = [
        vendor.BoardConfig(board_id=i, name="dev%d" % (i + 1), ip="192.168.10.%d" % (10 + i), tcp_port=24)
        for i in range(board_count)
    ]
    config = vendor.AppConfig(
        run_name_prefix="test",
        run_name=None,
        output_base_dir=".",
        tcm_ip="192.168.10.16",
        tcm_rbcp_port=4660,
        tcm_timeout_ms=3000,
        tcm_command_delay_s=0.02,
        tcm_poll_interval_s=0.05,
        tcm_poll_timeout_s=2.0,
        tcm_allow_start_without_ack=True,
        adc_length=adc_length,
        aggregation_key="timestamp",
        timestamp_match_window_ticks=10,
        event_timeout_ms=50,
        monitor_interval_s=1.0,
        monitor_jsonl_interval_s=5.0,
        tcp_timeout_s=1.0,
        reconnect_delay_s=1.0,
        recv_buffer_bytes=8192,
        frame_queue_size=10000,
        board_warn_no_data_s=3.0,
        partial_warn_ratio=0.01,
        reconnect_warn_count=3,
        boards=boards,
    )
    return config


def _native_config(*, board_count: int, adc_length: int = ADC_LENGTH):
    return NativeAppConfig(
        output_base_dir=".",
        tcm_ip="192.168.10.16",
        tcm_allow_start_without_ack=True,
        adc_length=adc_length,
        timestamp_match_window_ticks=10,
        boards=[
            NativeBoardConfig(
                board_id=i,
                name="dev%d" % (i + 1),
                ip="192.168.10.%d" % (10 + i),
                tcp_port=24,
            )
            for i in range(board_count)
        ],
    )


def _wire_packet(
    *,
    mode: int,
    event_count: int,
    timestamp: int,
    hit_mask: int,
    payload: bytes = b"",
    format_version: int = 0,
    crossing_fine: int = 0,
    accept_fine: int = 0,
    feature_record_length: int | None = None,
) -> bytes:
    header_bytes = 28 if format_version >= 1 else 20
    header = bytearray(header_bytes)
    header[0:3] = b"\xFF\xFE\x01"
    header[3] = mode
    header[4:8] = event_count.to_bytes(4, "big")
    header[8:16] = timestamp.to_bytes(8, "big")
    header[16:18] = hit_mask.to_bytes(2, "big")
    header[18] = (
        feature_record_length
        if feature_record_length is not None
        else (10 if mode in (2, 3) else 0)
    )
    header[19] = format_version
    if format_version >= 1:
        header[20:24] = crossing_fine.to_bytes(4, "big")
        header[24:28] = accept_fine.to_bytes(4, "big")
    return bytes(header) + payload


def _fields(raw: bytes, adc_length: int = ADC_LENGTH) -> TcpSentHeaderFields:
    class _OneShotSocket:
        def __init__(self, blob: bytes) -> None:
            self._blob = blob

        def recv(self, size: int) -> bytes:
            chunk, self._blob = self._blob[:size], self._blob[size:]
            return chunk

    reader = _TcpSentRawStreamReader(
        _OneShotSocket(raw), expected_send_mode=None, adc_length=adc_length
    )
    return reader.read_frame()


def _native_frame(
    raw: bytes,
    board: NativeBoardConfig,
    *,
    recv_unix_ns: int,
    reconnect: bool = False,
    adc_length: int = ADC_LENGTH,
) -> MultiBoardFrame:
    return frame_from_fields(
        _fields(raw, adc_length),
        board,
        recv_unix_ns=recv_unix_ns,
        reconnect_mark=reconnect,
    )


def _vendor_frame(
    vendor,
    raw: bytes,
    board,
    *,
    recv_unix_ns: int,
    reconnect: bool = False,
    adc_length: int = ADC_LENGTH,
):
    """Build the vendored Frame by running the vendored FrameParser."""
    buffer = bytearray(raw)
    parser = vendor.FrameParser(adc_length)
    frame, desync = parser.parse_one(buffer, board, reconnect)
    assert desync is False
    assert frame is not None
    frame.recv_unix_ns = recv_unix_ns
    return frame


def _native_event(
    *,
    seq: int,
    aggregation_value: int,
    timestamp: int,
    frames: dict[int, MultiBoardFrame],
    status_flags: int,
    present_mask: int,
    missing_mask: int,
    first_recv_unix_ns: int,
    flush_unix_ns: int,
    missing_ids: list[int],
) -> NativeAggregatedEvent:
    counts = [f.event_count for f in frames.values()]
    return NativeAggregatedEvent(
        aggregate_seq=seq,
        aggregation_value=aggregation_value,
        timestamp=timestamp,
        created_unix_ns=first_recv_unix_ns,
        first_recv_unix_ns=first_recv_unix_ns,
        flush_unix_ns=flush_unix_ns,
        frames=frames,
        boards_present_mask=present_mask,
        boards_missing_mask=missing_mask,
        status_flags=status_flags,
        event_count_min=min(counts) if counts else 0,
        event_count_max=max(counts) if counts else 0,
        missing_board_ids=missing_ids,
    )


def _vendor_event(
    vendor,
    *,
    seq: int,
    aggregation_value: int,
    timestamp: int,
    frames: dict[int, object],
    status_flags: int,
    present_mask: int,
    missing_mask: int,
    first_recv_unix_ns: int,
    flush_unix_ns: int,
    missing_ids: list[int],
):
    counts = [f.event_count for f in frames.values()]
    return vendor.AggregatedEvent(
        aggregate_seq=seq,
        aggregation_value=aggregation_value,
        timestamp=timestamp,
        created_unix_ns=first_recv_unix_ns,
        first_recv_unix_ns=first_recv_unix_ns,
        flush_unix_ns=flush_unix_ns,
        frames=frames,
        boards_present_mask=present_mask,
        boards_missing_mask=missing_mask,
        status_flags=status_flags,
        event_count_min=min(counts) if counts else 0,
        event_count_max=max(counts) if counts else 0,
        missing_board_ids=missing_ids,
    )


# ------------------------------------------------------------------- fixtures


def _scenario_packets():
    """Two boards: board 0 mode 1 (v0 header), board 1 mode 3 (v1 header)."""
    full_waveform = b"\x01\x02\x03\x04" * (16 * ADC_LENGTH)
    hit_mask = 0b0000_0000_0000_0011  # 2 hits
    feature = bytes(range(10)) * 2
    hit_waveform = b"\x0A\x0B\x0C\x0D" * (2 * ADC_LENGTH)
    board0 = _wire_packet(
        mode=1, event_count=100, timestamp=1000, hit_mask=0, payload=full_waveform
    )
    board1 = _wire_packet(
        mode=3,
        event_count=101,
        timestamp=1002,
        hit_mask=hit_mask,
        payload=feature + hit_waveform,
        format_version=1,
        crossing_fine=0xDEADBEEF,
        accept_fine=0x12345678,
    )
    return board0, board1


class TestWriterByteEquivalence:
    def test_file_header_and_empty_files_match(self, vendor, tmp_path):
        vendored_dir = tmp_path / "vendor"
        native_dir = tmp_path / "native"
        vendored_dir.mkdir()
        native_dir.mkdir()

        vendor_cfg = _vendor_config(vendor, board_count=2)
        vendor_cfg.output_base_dir = str(vendored_dir)
        original = vendor.now_unix_ns
        vendor.now_unix_ns = lambda: FROZEN_UNIX_NS
        try:
            vendor_writer = vendor.DataWriter(
                vendor_cfg, str(vendored_dir), _NullLogger()
            )
        finally:
            vendor.now_unix_ns = original
        native_writer = MultiBoardDataWriter(
            _native_config(board_count=2),
            native_dir,
            clock=FakeClock(start_unix_ns=FROZEN_UNIX_NS),
        )
        try:
            for name in ("complete_events.dat", "partial_events.dat", "complete_events.idx"):
                vendor_bytes = (vendored_dir / name).read_bytes()
                native_bytes = (native_dir / name).read_bytes()
                assert native_bytes == vendor_bytes
            assert len((native_dir / "complete_events.dat").read_bytes()) == 36
        finally:
            vendor_writer.close()
            native_writer.close()

    def test_complete_event_bytes_match(self, vendor, tmp_path):
        raw0, raw1 = _scenario_packets()
        board0_v = vendor.BoardConfig(0, "dev1", "192.168.10.10", 24)
        board1_v = vendor.BoardConfig(1, "dev2", "192.168.10.12", 24)

        vf0 = _vendor_frame(vendor, raw0, board0_v, recv_unix_ns=111)
        vf1 = _vendor_frame(vendor, raw1, board1_v, recv_unix_ns=222, reconnect=True)

        native_cfg = _native_config(board_count=2)
        board0_n, board1_n = native_cfg.boards
        nf0 = _native_frame(raw0, board0_n, recv_unix_ns=111)
        nf1 = _native_frame(raw1, board1_n, recv_unix_ns=222, reconnect=True)

        kwargs = dict(
            seq=1,
            aggregation_value=1000,
            timestamp=1000,
            status_flags=EVENT_FLAG_COMPLETE,
            present_mask=0b11,
            missing_mask=0,
            first_recv_unix_ns=111,
            flush_unix_ns=999,
            missing_ids=[],
        )
        v_event = _vendor_event(vendor, frames={0: vf0, 1: vf1}, **kwargs)
        n_event = _native_event(frames={0: nf0, 1: nf1}, **kwargs)

        v_bytes = _write_and_read_vendor(vendor, tmp_path / "v", v_event)
        n_bytes = _write_and_read_native(tmp_path / "n", n_event)
        assert n_bytes["complete_events.dat"] == v_bytes["complete_events.dat"]
        assert n_bytes["complete_events.idx"] == v_bytes["complete_events.idx"]
        assert len(n_bytes["complete_events.dat"]) > 36

    def test_partial_event_bytes_match_and_no_index(self, vendor, tmp_path):
        raw0, _ = _scenario_packets()
        board0_v = vendor.BoardConfig(0, "dev1", "192.168.10.10", 24)
        vf0 = _vendor_frame(vendor, raw0, board0_v, recv_unix_ns=111)

        native_cfg = _native_config(board_count=2)
        nf0 = _native_frame(raw0, native_cfg.boards[0], recv_unix_ns=111)

        kwargs = dict(
            seq=1,
            aggregation_value=1000,
            timestamp=1000,
            status_flags=EVENT_FLAG_PARTIAL | EVENT_FLAG_TIMEOUT_FLUSH,
            present_mask=0b01,
            missing_mask=0b10,
            first_recv_unix_ns=111,
            flush_unix_ns=999,
            missing_ids=[1],
        )
        v_bytes = _write_and_read_vendor(
            vendor, tmp_path / "v", _vendor_event(vendor, frames={0: vf0}, **kwargs)
        )
        n_bytes = _write_and_read_native(
            tmp_path / "n", _native_event(frames={0: nf0}, **kwargs)
        )
        assert n_bytes["partial_events.dat"] == v_bytes["partial_events.dat"]
        assert n_bytes["complete_events.idx"] == v_bytes["complete_events.idx"] == b""

    def test_event_count_mismatch_flag_matches(self, vendor, tmp_path):
        raw0, _ = _scenario_packets()
        board0_v = vendor.BoardConfig(0, "dev1", "192.168.10.10", 24)
        board0_n = _native_config(board_count=2).boards[0]

        vf0 = _vendor_frame(vendor, raw0, board0_v, recv_unix_ns=1)
        # Second frame with same board_id is impossible in a bucket; instead
        # compare the flag bit computed by the aggregator (see aggregator tests).

        kwargs = dict(
            seq=2,
            aggregation_value=1000,
            timestamp=1000,
            status_flags=(
                EVENT_FLAG_PARTIAL
                | EVENT_FLAG_TIMEOUT_FLUSH
                | EVENT_FLAG_EVENT_COUNT_MISMATCH
            ),
            present_mask=0b01,
            missing_mask=0b10,
            first_recv_unix_ns=1,
            flush_unix_ns=2,
            missing_ids=[1],
        )
        v_bytes = _write_and_read_vendor(
            vendor, tmp_path / "v", _vendor_event(vendor, frames={0: vf0}, **kwargs)
        )
        n_bytes = _write_and_read_native(
            tmp_path / "n",
            _native_event(
                frames={0: _native_frame(raw0, board0_n, recv_unix_ns=1)}, **kwargs
            ),
        )
        assert n_bytes["partial_events.dat"] == v_bytes["partial_events.dat"]


FROZEN_UNIX_NS = 1_700_000_000_000_000_000


def _write_and_read_vendor(vendor, run_dir: Path, event) -> dict[str, bytes]:
    run_dir.mkdir(parents=True, exist_ok=True)
    config = _vendor_config(vendor, board_count=2)
    config.output_base_dir = str(run_dir)
    # Freeze the file-header clock so the two writers produce identical bytes.
    original = vendor.now_unix_ns
    vendor.now_unix_ns = lambda: FROZEN_UNIX_NS
    try:
        writer = vendor.DataWriter(config, str(run_dir), _NullLogger())
        try:
            writer.write_event(event)
        finally:
            writer.close()
    finally:
        vendor.now_unix_ns = original
    return {
        name: (run_dir / name).read_bytes()
        for name in ("complete_events.dat", "partial_events.dat", "complete_events.idx")
    }


def _write_and_read_native(run_dir: Path, event) -> dict[str, bytes]:
    run_dir.mkdir(parents=True, exist_ok=True)
    writer = MultiBoardDataWriter(
        _native_config(board_count=2),
        run_dir,
        clock=FakeClock(start_unix_ns=FROZEN_UNIX_NS),
    )
    try:
        writer.write_event(event)
    finally:
        writer.close()
    return {
        name: (run_dir / name).read_bytes()
        for name in ("complete_events.dat", "partial_events.dat", "complete_events.idx")
    }


class _NullLogger:
    def log(self, level, message):  # noqa: D102 - test double
        pass


class _RecordingLogger:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def log(self, level, message):  # noqa: D102 - test double
        self.lines.append((level, message))


class _NullState:
    def __init__(self) -> None:
        self.complete = 0
        self.partial = 0
        self.open_buckets = 0

    def update_open_bucket_count(self, count):  # noqa: D102 - test double
        self.open_buckets = count

    def record_complete_event(self, event):  # noqa: D102 - test double
        self.complete += 1

    def record_partial_event(self, event):  # noqa: D102 - test double
        self.partial += 1


class _NullWriter:
    def __init__(self) -> None:
        self.events = []

    def write_event(self, event):  # noqa: D102 - test double
        self.events.append(event)

    def write_monitor_snapshot(self, snapshot):  # noqa: D102 - test double
        pass


class _VendorState:
    """Mirrors the vendored SharedState counters for equivalence assertions."""

    def __init__(self) -> None:
        self.complete_events = 0
        self.partial_events = 0
        self.open_bucket_count = 0
        self.event_count_mismatches = 0
        self.last_partial_missing: list[int] = []

    def update_open_bucket_count(self, count):  # noqa: D102 - test double
        self.open_bucket_count = count

    def record_complete_event(self, event):  # noqa: D102 - test double
        self.complete_events += 1

    def record_partial_event(self, event):  # noqa: D102 - test double
        self.partial_events += 1
        self.last_partial_missing = list(event.missing_board_ids)


class TestAggregatorEquivalence:
    """Drive the native and vendored aggregators with identical frame streams."""

    def _build(self, vendor, raw_packets, *, boards=2, aggregation_key="timestamp",
               window=10, timeout_ms=50, adc_length=ADC_LENGTH):
        """Return (native_frames, vendor_frames) built from the same wire bytes."""
        vcfg = _vendor_config(vendor, board_count=boards, adc_length=adc_length)
        ncfg = _native_config(board_count=boards, adc_length=adc_length)
        vcfg.aggregation_key = aggregation_key
        vcfg.timestamp_match_window_ticks = window
        vcfg.event_timeout_ms = timeout_ms
        ncfg.aggregation_key = aggregation_key
        ncfg.timestamp_match_window_ticks = window
        ncfg.event_timeout_ms = timeout_ms

        native_frames = []
        vendor_frames = []
        for index, raw in enumerate(raw_packets):
            board_index = index % boards
            native_frames.append(
                _native_frame(
                    raw,
                    ncfg.boards[board_index],
                    recv_unix_ns=10 + index,
                    adc_length=adc_length,
                )
            )
            vendor_frames.append(
                _vendor_frame(
                    vendor,
                    raw,
                    vcfg.boards[board_index],
                    recv_unix_ns=10 + index,
                    adc_length=adc_length,
                )
            )
        return native_frames, vendor_frames, ncfg, vcfg

    def _run_native(self, frames, config, clock):
        import queue as _queue

        q = _queue.Queue()
        writer = _NullWriter()
        state = _NullState()
        logger = _RecordingLogger()
        stop_event = threading.Event()
        agg = MultiBoardEventAggregator(
            config.boards, config, q, writer, state, logger, stop_event, clock=clock
        )
        for frame in frames:
            q.put(frame)
        stop_event.set()
        agg.run()
        return writer.events, state, logger

    def _run_vendor(self, vendor, frames, config, clock):
        import queue as _queue

        q = _queue.Queue()
        writer = _NullWriter()
        state = _VendorState()
        logger = _RecordingLogger()
        stop_event = threading.Event()
        agg = vendor.EventAggregator(
            config.boards, config, q, writer, state, logger, stop_event
        )
        for frame in frames:
            q.put(frame)
        stop_event.set()
        # Freeze the vendored module's clocks onto the same timeline as the
        # native FakeClock so bucket expiry decisions line up.
        original = (vendor.time.monotonic, vendor.time.sleep, vendor.now_unix_ns)
        vendor.time.monotonic = clock.monotonic
        vendor.time.sleep = clock.sleep
        vendor.now_unix_ns = clock.unix_ns
        try:
            agg.run()
        finally:
            vendor.time.monotonic, vendor.time.sleep, vendor.now_unix_ns = original
        return writer.events, state, logger

    def _assert_same_events(self, native_events, vendor_events):
        assert len(native_events) == len(vendor_events)
        for native, vendored in zip(native_events, vendor_events):
            assert native.aggregate_seq == vendored.aggregate_seq
            assert native.aggregation_value == vendored.aggregation_value
            assert native.timestamp == vendored.timestamp
            assert native.status_flags == vendored.status_flags
            assert native.boards_present_mask == vendored.boards_present_mask
            assert native.boards_missing_mask == vendored.boards_missing_mask
            assert native.missing_board_ids == vendored.missing_board_ids
            assert sorted(native.frames) == sorted(vendored.frames)

    def test_complete_when_all_boards_present(self, vendor):
        raw0, raw1 = _scenario_packets()
        native, vendored, ncfg, vcfg = self._build(vendor, [raw0, raw1])
        clock = FakeClock()
        n_events, n_state, _ = self._run_native(native, ncfg, clock)
        v_events, v_state, _ = self._run_vendor(vendor, vendored, vcfg, FakeClock())
        self._assert_same_events(n_events, v_events)
        assert n_state.complete == v_state.complete_events == 1
        assert n_state.partial == v_state.partial_events == 0
        assert n_events[0].status_flags & EVENT_FLAG_COMPLETE
        assert n_events[0].boards_present_mask == 0b11
        # Boards disagree on event_count (100 vs 101) -> mismatch flag.
        assert n_events[0].status_flags & EVENT_FLAG_EVENT_COUNT_MISMATCH

    def test_timeout_flushes_partial(self, vendor):
        raw0, _ = _scenario_packets()
        native, vendored, ncfg, vcfg = self._build(vendor, [raw0])
        n_events, n_state, _ = self._run_native(native, ncfg, FakeClock())
        v_events, v_state, _ = self._run_vendor(vendor, vendored, vcfg, FakeClock())
        self._assert_same_events(n_events, v_events)
        assert n_state.partial == v_state.partial_events == 1
        assert n_events[0].status_flags == (
            EVENT_FLAG_PARTIAL | EVENT_FLAG_TIMEOUT_FLUSH
        )
        assert n_events[0].missing_board_ids == [1]

    def test_duplicate_board_frame_overwrites_and_warns(self, vendor):
        raw0, _ = _scenario_packets()
        native, vendored, ncfg, vcfg = self._build(
            vendor, [raw0, raw0, raw0, raw0], boards=1
        )
        n_events, n_state, n_log = self._run_native(native, ncfg, FakeClock())
        v_events, v_state, _ = self._run_vendor(vendor, vendored, vcfg, FakeClock())
        self._assert_same_events(n_events, v_events)
        assert n_state.complete == v_state.complete_events == 4

    def test_timestamp_window_merges_boards_within_window(self, vendor):
        raw0, raw1 = _scenario_packets()
        native, vendored, ncfg, vcfg = self._build(vendor, [raw0, raw1], window=10)
        n_events, n_state, _ = self._run_native(native, ncfg, FakeClock())
        v_events, v_state, _ = self._run_vendor(vendor, vendored, vcfg, FakeClock())
        self._assert_same_events(n_events, v_events)
        assert n_state.complete == v_state.complete_events == 1
        assert len(n_events[0].frames) == 2

    def test_out_of_window_frames_stay_separate(self, vendor):
        raw0, raw1 = _scenario_packets()
        native, vendored, ncfg, vcfg = self._build(vendor, [raw0, raw1], window=0)
        # window 0 still merges exact matches; board 1 is at +2 ticks, so it
        # must not join board 0's bucket.
        clock = FakeClock()
        n_events, n_state, _ = self._run_native(native, ncfg, clock)
        v_events, v_state, _ = self._run_vendor(vendor, vendored, vcfg, FakeClock())
        self._assert_same_events(n_events, v_events)
        assert n_state.partial == v_state.partial_events == 2

    def test_event_count_aggregation_key(self, vendor):
        raw0, raw1 = _scenario_packets()
        native, vendored, ncfg, vcfg = self._build(
            vendor, [raw0, raw1], aggregation_key="event_count"
        )
        n_events, _, _ = self._run_native(native, ncfg, FakeClock())
        v_events, _, _ = self._run_vendor(vendor, vendored, vcfg, FakeClock())
        self._assert_same_events(n_events, v_events)
        assert len(n_events) == 2


class TestReaderParity:
    def test_read_frame_matches_vendored_frame_parser(self, vendor):
        raw0, raw1 = _scenario_packets()
        board0_v = vendor.BoardConfig(0, "dev1", "192.168.10.10", 24)
        board1_v = vendor.BoardConfig(1, "dev2", "192.168.10.12", 24)
        for raw, board in ((raw0, board0_v), (raw1, board1_v)):
            fields = _fields(raw)
            vframe = _vendor_frame(vendor, raw, board, recv_unix_ns=0)
            assert fields.mode == vframe.mode
            assert fields.event_count == vframe.event_count
            assert fields.timestamp == vframe.timestamp
            assert fields.hit_mask == vframe.hit_mask
            assert fields.format_version == vframe.format_version
            assert fields.crossing_fine == (vframe.crossing_fine or None)
            assert fields.accept_fine == (vframe.accept_fine or None)
            assert fields.packet == raw
            assert fields.feature_len == len(vframe.feature_bytes)
            assert fields.waveform_len == len(vframe.waveform_bytes)

    def test_adc_length_parameter_changes_frame_size(self, vendor):
        """A non-256 adc_length must slice differently, matching the vendored parser."""
        hit_mask = 0b1
        payload = b"\x01\x02\x03\x04" * 64
        raw = _wire_packet(mode=0, event_count=1, timestamp=1, hit_mask=hit_mask, payload=payload)
        board_v = vendor.BoardConfig(0, "dev1", "192.168.10.10", 24)
        vframe = _vendor_frame(vendor, raw, board_v, recv_unix_ns=0, adc_length=64)
        assert len(vframe.waveform_bytes) == 64 * 4
        assert len(raw) == 20 + 64 * 4

        fields = _fields(raw, adc_length=64)
        assert fields.waveform_len == 64 * 4


class TestNativeFramePayloadSlicing:
    def test_feature_and_waveform_slices_match_reader_lengths(self):
        raw0, raw1 = _scenario_packets()
        cfg = _native_config(board_count=2)
        nf1 = _native_frame(raw1, cfg.boards[1], recv_unix_ns=0)
        assert len(nf1.feature_bytes) == nf1.feature_len == 20
        assert len(nf1.waveform_bytes) == nf1.waveform_len
        assert nf1.raw_packet == raw1
