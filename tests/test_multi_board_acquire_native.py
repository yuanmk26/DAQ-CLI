"""Native multi-board pipeline units: receiver, monitor, run meta, TCM align.

Byte-level writer/aggregator/reader equivalence lives in
``test_multi_board_native_equivalence.py``; these tests pin the remaining
behavioural contracts.
"""

from __future__ import annotations

import json
import queue
import threading
from unittest.mock import patch

from daq_cli.infrastructure.multi_board_acquire.app import MultiBoardAcquisitionApp
from daq_cli.infrastructure.multi_board_acquire.clock import FakeClock
from daq_cli.infrastructure.multi_board_acquire.constants import FORMAT_VERSION
from daq_cli.infrastructure.multi_board_acquire.frames import MultiBoardFrame
from tests.test_multi_board_native_equivalence import (
    _NullWriter,
    _RecordingLogger,
    _native_config,
    _native_frame,
    _scenario_packets,
)


class _OneShotSocket:
    """Socket double: yields queued blobs, then reports EOF."""

    def __init__(self, blobs: list[bytes], on_eof=None) -> None:
        self._blobs = list(blobs)
        self._on_eof = on_eof
        self.timeout = None
        self.closed = False

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def connect(self, _address) -> None:
        return None

    def recv(self, _size: int) -> bytes:
        if not self._blobs:
            if self._on_eof is not None:
                self._on_eof()
            return b""
        return self._blobs.pop(0)

    def close(self) -> None:
        self.closed = True


class _ReceiverState:
    """Minimal state double recording the calls a receiver makes."""

    def __init__(self) -> None:
        self.connected = False
        self.reconnects = 0
        self.desyncs = 0
        self.recv_errors = 0
        self.frames: list[MultiBoardFrame] = []

    def mark_connected(self, _board_id):  # noqa: D102 - test double
        self.connected = True

    def mark_disconnected(self, _board_id):  # noqa: D102 - test double
        self.connected = False

    def mark_reconnect(self, _board_id):  # noqa: D102 - test double
        self.reconnects += 1
        return self.reconnects

    def mark_desync(self, _board_id):  # noqa: D102 - test double
        self.desyncs += 1

    def mark_recv_error(self, _board_id):  # noqa: D102 - test double
        self.recv_errors += 1

    def record_frame(self, frame):  # noqa: D102 - test double
        self.frames.append(frame)


class _FrameCollector:
    def __init__(self) -> None:
        self.frames: list[MultiBoardFrame] = []

    def on_frame(self, frame):  # noqa: D102 - test double
        self.frames.append(frame)


class TestReceiverReconnect:
    def _run(self, sessions: list[bytes], *, stop_on_extra_reconnect: bool = True):
        from daq_cli.infrastructure.multi_board_acquire.receiver import (
            MultiBoardBoardReceiver,
        )

        config = _native_config(board_count=1)
        config.reconnect_delay_s = 0.0
        clock = FakeClock()
        state = _ReceiverState()
        logger = _RecordingLogger()
        stop_event = threading.Event()
        collector = _FrameCollector()

        remaining = list(sessions)
        sockets: list[_OneShotSocket] = []

        def on_eof():
            # All scripted sessions delivered: the next reconnect is the end.
            if not remaining and stop_on_extra_reconnect:
                stop_event.set()

        def socket_factory():
            sock = _OneShotSocket([remaining.pop(0)], on_eof=on_eof)
            sockets.append(sock)
            return sock

        receiver = MultiBoardBoardReceiver(
            config.boards[0],
            config,
            queue.Queue(),
            state,
            logger,
            stop_event,
            clock=clock,
            frame_sink=collector,
            socket_factory=socket_factory,
        )
        receiver.run()
        return collector, state, logger, sockets

    def test_first_frame_after_reconnect_carries_the_flag(self):
        raw0, _ = _scenario_packets()
        collected, state, _logger, sockets = self._run([raw0, raw0])

        assert len(collected.frames) == 2
        assert collected.frames[0].reconnect_mark is False
        assert collected.frames[1].reconnect_mark is True
        assert state.reconnects == 1
        # Each session failure (including the final EOF) is counted.
        assert state.recv_errors == 2
        # The final disconnect happens because of the stop request, so no
        # mark_disconnected follows and the last known state stays connected.
        assert state.connected is True
        assert len(sockets) == 2
        assert all(sock.closed for sock in sockets)

    def test_single_session_never_marks_reconnect(self):
        raw0, _ = _scenario_packets()
        config = _native_config(board_count=1)
        config.reconnect_delay_s = 0.0
        state = _ReceiverState()
        collector = _FrameCollector()
        stop_event = threading.Event()
        sock = _OneShotSocket([raw0], on_eof=stop_event.set)

        from daq_cli.infrastructure.multi_board_acquire.receiver import (
            MultiBoardBoardReceiver,
        )

        receiver = MultiBoardBoardReceiver(
            config.boards[0],
            config,
            queue.Queue(),
            state,
            _RecordingLogger(),
            stop_event,
            clock=FakeClock(),
            frame_sink=collector,
            socket_factory=lambda: sock,
        )
        receiver.run()

        assert len(collector.frames) == 1
        assert collector.frames[0].reconnect_mark is False
        assert state.reconnects == 0


class TestMonitorEmit:
    def _state(self):
        from daq_cli.infrastructure.multi_board_acquire.state import (
            MultiBoardSharedState,
        )

        cfg = _native_config(board_count=2)
        return cfg, MultiBoardSharedState(cfg.boards, clock=FakeClock())

    def test_emit_renders_monitor_line_and_json_schema(self):
        from daq_cli.infrastructure.multi_board_acquire.monitor import (
            MultiBoardMonitorThread,
        )

        cfg, state = self._state()
        clock = FakeClock()
        logger = _RecordingLogger()
        writer = _NullWriter()
        monitor = MultiBoardMonitorThread(
            cfg, state, writer, logger, threading.Event(), clock=clock
        )

        with patch.object(writer, "write_monitor_snapshot") as write_snapshot:
            json_snapshot = monitor.emit(state.snapshot(), interval_s=1.0, now_s=1.0)

        level, head = logger.lines[0]
        assert level == "INFO"
        assert head.startswith("[MON] elapsed=1.0s complete=0 partial=0")
        assert "open_buckets=0 last_complete_key=0 last_complete_ts=0" in head

        board_lines = [line for _level, line in logger.lines[1:]]
        assert len(board_lines) == 2
        assert board_lines[0].startswith(
            "[MON] dev1 conn=down fps=0.0 total=0 last_ev=None desync=0 reconnect=0"
        )

        assert sorted(json_snapshot.keys()) == [
            "aggregation_key",
            "boards",
            "complete_events",
            "elapsed_s",
            "event_count_mismatches",
            "last_complete_aggregation_value",
            "last_complete_timestamp",
            "last_partial_missing",
            "open_bucket_count",
            "partial_events",
            "partial_ratio",
            "timestamp_match_window_ticks",
            "ts",
        ]
        assert json_snapshot["boards"]["dev1"]["warn_tokens"] == []
        assert "dev2" in json_snapshot["boards"]
        # now_s=1.0 is below the 5 s jsonl interval.
        assert not write_snapshot.called

    def test_emit_writes_jsonl_once_the_interval_elapses(self):
        from daq_cli.infrastructure.multi_board_acquire.monitor import (
            MultiBoardMonitorThread,
        )

        cfg, state = self._state()
        writer = _NullWriter()
        monitor = MultiBoardMonitorThread(
            cfg, state, writer, _RecordingLogger(), threading.Event(), clock=FakeClock()
        )
        with patch.object(writer, "write_monitor_snapshot") as write_snapshot:
            monitor.emit(state.snapshot(), interval_s=1.0, now_s=5.0)
        assert write_snapshot.called

    def test_no_data_warning_after_silence(self):
        from daq_cli.infrastructure.multi_board_acquire.monitor import (
            MultiBoardMonitorThread,
        )

        cfg, state = self._state()
        clock = FakeClock(start_unix_ns=10_000_000_000)
        state.record_frame(_native_frame(_scenario_packets()[0], cfg.boards[0], recv_unix_ns=0))
        monitor = MultiBoardMonitorThread(
            cfg, state, _NullWriter(), _RecordingLogger(), threading.Event(), clock=clock
        )
        snapshot = monitor.emit(state.snapshot(), interval_s=10.0, now_s=10.0)
        # dev1 last reported at t=0 -> 10 s silent -> NO_DATA.
        assert "NO_DATA" in snapshot["boards"]["dev1"]["warn_tokens"]
        # dev2 never reported -> silence is unknown, no token.
        assert "NO_DATA" not in snapshot["boards"]["dev2"]["warn_tokens"]


class TestRunMetaStateMachine:
    def test_status_transitions_and_align_snapshot(self, tmp_path):
        from daq_cli.infrastructure.multi_board_acquire.alignment import AlignSnapshot

        cfg = _native_config(board_count=2)
        cfg.output_base_dir = str(tmp_path)
        cfg.run_name = "run_case"
        cfg.tcm_allow_start_without_ack = True

        app = MultiBoardAcquisitionApp(cfg, config_path="cfg.json")
        snapshot = AlignSnapshot(
            status=5, online_mask=0x0F, ack_mask=0x04, missing_mask=0x0B
        )

        app.write_run_meta("created", None)
        first = json.loads((tmp_path / "run_case" / "run_meta.json").read_text("utf-8"))
        assert first["status"] == "created"
        assert first["stop_time"] is None
        assert "align_snapshot" not in first

        app.write_run_meta("aligned_ack_bypassed", snapshot)
        second = json.loads((tmp_path / "run_case" / "run_meta.json").read_text("utf-8"))
        assert second["status"] == "aligned_ack_bypassed"
        assert second["stop_time"] is None
        assert second["align_snapshot"] == {
            "status": 5,
            "online_mask": 15,
            "ack_mask": 4,
            "missing_mask": 11,
        }

        app.aligned = True
        app.write_run_meta("stopped", snapshot)
        raw = (tmp_path / "run_case" / "run_meta.json").read_text("utf-8")
        third = json.loads(raw)
        assert third["status"] == "stopped"
        assert third["stop_time"] is not None
        assert third["format_name"] == "FDU_ADC_AGGR"
        assert third["format_version"] == FORMAT_VERSION
        assert sorted(third.keys()) == [
            "adc_length",
            "aggregation_key",
            "align_snapshot",
            "boards_expected",
            "config_path",
            "event_timeout_ms",
            "format_name",
            "format_version",
            "run_dir",
            "start_time",
            "status",
            "stop_time",
            "tcm_allow_start_without_ack",
            "tcm_ip",
            "tcm_rbcp_port",
            "timestamp_match_window_ticks",
        ]
        assert raw.endswith("}\n")
        assert raw.index('"adc_length"') < raw.index('"aggregation_key"')


class _FakeAlignBus:
    """Records RBCP traffic, advancing to the next status every 4 reads."""

    def __init__(self, statuses: list[tuple[int, int, int, int]]) -> None:
        self.writes: list[tuple[int, int]] = []
        self.reads: list[int] = []
        self.closed = False
        self._statuses = list(statuses)

    def read(self, address: int, length: int) -> bytes:
        self.reads.append(address)
        if self._statuses:
            status, online, ack, missing = self._statuses[0]
        else:
            status, online, ack, missing = 0, 0, 0, 0
        mapping = {0x19: status, 0x1A: online, 0x1B: ack, 0x1C: missing}
        value = mapping[address]
        # 0x1C completes one snapshot -> advance to the next scripted one.
        if address == 0x1C and len(self._statuses) > 1:
            self._statuses.pop(0)
        return bytes([value])

    def write(self, address: int, data: bytes) -> bytes:
        self.writes.append((address, data[0]))
        return b""

    def close(self) -> None:
        self.closed = True


class TestTcmAlign:
    def _controller(self, statuses, clock=None):
        from daq_cli.infrastructure.multi_board_acquire.alignment import (
            TcmAlignController,
        )

        clock = clock or FakeClock()
        bus = _FakeAlignBus(statuses)
        logger = _RecordingLogger()
        controller = TcmAlignController(
            _native_config(board_count=2),
            logger,
            clock=clock,
            rbcp_factory=lambda **_kwargs: bus,
        )
        return controller, bus, logger, clock

    def test_done_with_all_acks_succeeds(self):
        controller, bus, logger, clock = self._controller([(0x02, 0x03, 0x03, 0x00)])
        success, snapshot = controller.align()

        assert success is True
        assert snapshot.status == 0x02
        assert bus.writes == [(0x18, 0x02), (0x18, 0x01)]
        # DONE on the first poll -> only the command delay is slept.
        assert clock.sleeps == [0.02]
        assert bus.reads[:4] == [0x19, 0x1A, 0x1B, 0x1C]
        assert bus.closed
        assert "success=true" in logger.lines[-1][1]

    def test_done_with_missing_ack_fails(self):
        controller, _bus, logger, _clock = self._controller([(0x02, 0x03, 0x01, 0x02)])
        success, snapshot = controller.align()
        assert success is False
        assert snapshot.missing_mask == 0x02
        assert "success=false" in logger.lines[-1][1]

    def test_timeout_sticky_bit_stops_polling(self):
        controller, bus, _logger, _clock = self._controller(
            [(0x00, 0x03, 0x00, 0x03), (0x04, 0x03, 0x00, 0x03)]
        )
        success, snapshot = controller.align()
        assert success is False
        assert snapshot.status == 0x04
        assert len(bus.reads) == 8  # two snapshots, then stop

    def test_poll_deadline_falls_back_to_a_final_snapshot(self):
        statuses = [(0x00, 0x01, 0x00, 0x01)] * 100
        controller, bus, _logger, _clock = self._controller(statuses)
        success, _snapshot = controller.align()
        assert success is False
        # 2.0 s deadline / 0.05 s poll interval = 40 polls, plus one final read.
        assert len(bus.reads) == (40 + 1) * 4
