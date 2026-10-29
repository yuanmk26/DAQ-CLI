from pathlib import Path
import shutil
from types import SimpleNamespace
import queue
import threading
import unittest
import uuid
from unittest.mock import patch

import daq_cli.infrastructure.adapters.multi_capture_runner as multi_capture_runner_module
from daq_cli.application.output_config import (
    AcquireOutputsConfig,
    OutputTargetConfig,
    TextOutputConfig,
)
from daq_cli.infrastructure.adapters.multi_capture_runner import (
    MultiBoardDecodeRuntime,
    MultiCaptureConfig,
    MultiCaptureRunner,
)
from daq_cli.infrastructure.adapters.multi_board_decode_backend import (
    DecodeDrainResult,
)
from daq_cli.infrastructure.adapters.multi_board_watch import (
    DEFAULT_MULTI_WATCH_QUEUE_SIZE,
    MultiBoardWatchPublisher,
    MultiBoardWatchRuntime,
    WatchControlMessage,
    _publish_view_update,
    watch_backend_main,
)
from daq_cli.infrastructure.multi_board_acquire import (
    MultiBoardAppConfig,
    MultiBoardConfig,
    MultiBoardFrame,
    frame_from_fields,
)
from daq_cli.infrastructure.wave_monitor import MultiBoardWaveUpdate, WaveMonitorFrame
from daq_cli.presentation.wave_monitor_viewer import _drain_multi_board_updates
from daq_cli.infrastructure.tcp_sent_decode import decode_tcp_sent_packet
from daq_cli.infrastructure.adapters.legacy_capture_runner import _TcpSentRawStreamReader
from daq_cli.infrastructure.run_name_allocator import allocate_next_run_dir


ADC_LENGTH = 256


class MultiWaveWatchTests(unittest.TestCase):
    def test_native_frame_round_trips_mode1_waveform_packet(self) -> None:
        frame = _build_native_frame(mode=1, hit_mask=0x00FF, event_count=12, timestamp=3456)
        decoded = decode_tcp_sent_packet(frame.raw_packet, source_file=Path("sample.bin"))

        self.assertEqual(decoded.send_mode, 1)
        self.assertEqual(decoded.event_count, 12)
        self.assertEqual(decoded.timestamp, 3456)
        self.assertEqual(decoded.hit_mask, 0x00FF)
        self.assertEqual(len(decoded.channels), 16)
        self.assertTrue(all(channel is not None for channel in decoded.channels))

    def test_native_frame_round_trips_mode3_waveform_packet(self) -> None:
        frame = _build_native_frame(mode=3, hit_mask=0x0003, event_count=7, timestamp=99)
        decoded = decode_tcp_sent_packet(frame.raw_packet, source_file=Path("sample.bin"))

        self.assertEqual(decoded.send_mode, 3)
        self.assertEqual(decoded.hit_mask, 0x0003)
        self.assertIsNotNone(decoded.channels[0])
        self.assertIsNotNone(decoded.channels[1])
        self.assertIsNone(decoded.channels[2])

    def test_native_frame_round_trips_fine_frame_to_v1_packet(self) -> None:
        frame = _build_native_frame(
            mode=1,
            hit_mask=0x00FF,
            event_count=12,
            timestamp=3456,
            format_version=1,
            crossing_fine=0xCAFE0000,
            accept_fine=0xCAFE0064,
        )
        decoded = decode_tcp_sent_packet(frame.raw_packet, source_file=Path("sample.bin"))

        self.assertEqual(decoded.format_version, 1)
        self.assertEqual(decoded.crossing_fine, 0xCAFE0000)
        self.assertEqual(decoded.accept_fine, 0xCAFE0064)
        self.assertEqual(decoded.delta_fine, 100)

    def test_stream_reader_discriminates_frame_versions(self) -> None:
        from daq_cli.infrastructure.tcp_sent_protocol import FORMAT_VERSION_FINE

        fine_packet = _build_tcp_sent_packet_v2(
            1, 0x00FF, 21, format_version=1,
            crossing_fine=0x100, accept_fine=0x180,
        )
        legacy_packet = _build_tcp_sent_packet_v2(1, 0x00FF, 21)

        fine_fields = _read_fields(fine_packet)
        self.assertEqual(fine_fields.format_version, FORMAT_VERSION_FINE)
        self.assertEqual(fine_fields.header_bytes, 28)
        self.assertEqual(fine_fields.crossing_fine, 0x100)
        self.assertEqual(fine_fields.accept_fine, 0x180)

        legacy_fields = _read_fields(legacy_packet)
        self.assertEqual(legacy_fields.format_version, 0)
        self.assertEqual(legacy_fields.header_bytes, 20)
        self.assertIsNone(legacy_fields.crossing_fine)
        self.assertIsNone(legacy_fields.accept_fine)

    def test_watch_publisher_samples_every_nth_frame_per_board(self) -> None:
        task_queue: queue.Queue = queue.Queue(maxsize=4)
        publisher = MultiBoardWatchPublisher(
            board_order={0: ("dev1", 0)},
            watch_every=2,
            aggregation_key="event_count",
            timestamp_match_window_ticks=0,
            event_timeout_ms=50,
            task_queue=task_queue,
        )
        frame = _build_native_frame(mode=1, hit_mask=0x00FF, event_count=1, timestamp=1)

        publisher.on_frame(frame)
        self.assertTrue(task_queue.empty())

        publisher.on_frame(frame)
        sampled = task_queue.get_nowait()
        self.assertEqual(sampled.board_name, "dev1")
        self.assertEqual(sampled.board_index, 0)
        self.assertGreater(len(sampled.packet), 20)

    def test_multi_watch_queue_size_is_large_enough_for_bursty_watch_every_one(self) -> None:
        self.assertGreaterEqual(DEFAULT_MULTI_WATCH_QUEUE_SIZE, 1024)

    def test_publisher_forwarded_packet_is_the_raw_wire_frame(self) -> None:
        task_queue: queue.Queue = queue.Queue(maxsize=1)
        publisher = MultiBoardWatchPublisher(
            board_order={0: ("dev1", 0)},
            watch_every=1,
            aggregation_key="event_count",
            timestamp_match_window_ticks=0,
            event_timeout_ms=50,
            task_queue=task_queue,
        )
        frame = _build_native_frame(mode=1, hit_mask=0x00FF, event_count=1, timestamp=1)

        publisher.on_frame(frame)

        sampled = task_queue.get_nowait()
        self.assertEqual(sampled.board_name, "dev1")
        # No re-encoding: the sampled packet is the exact wire bytes.
        self.assertEqual(sampled.packet, frame.raw_packet)

    def test_publish_multi_board_view_update_keeps_same_event_updates_for_two_boards(self) -> None:
        viewer_queue: queue.Queue = queue.Queue(maxsize=16)
        for board_index, board_name in ((0, "dev1"), (1, "dev2")):
            _publish_view_update(
                viewer_queue,
                MultiBoardWaveUpdate(
                    board_name=board_name,
                    board_index=board_index,
                    aggregate_event_id=123,
                    aggregate_timestamp=456,
                    board_event_count=123,
                    board_timestamp=456,
                    frame=WaveMonitorFrame(
                        device_name=board_name,
                        event_count=123,
                        timestamp=456,
                        hit_mask=0,
                        send_mode=1,
                        channels=[[board_index] * 4 for _ in range(16)],
                    ),
                ),
            )

        updates = _drain_multi_board_updates(viewer_queue)
        self.assertEqual(len(updates), 2)
        self.assertEqual(
            [(update.board_name, update.frame.event_count) for update in updates],
            [("dev1", 123), ("dev2", 123)],
        )

    def test_publish_multi_board_view_update_drops_when_queue_too_small(self) -> None:
        viewer_queue: queue.Queue = queue.Queue(maxsize=1)
        for board_index, board_name in ((0, "dev1"), (1, "dev2")):
            _publish_view_update(
                viewer_queue,
                MultiBoardWaveUpdate(
                    board_name=board_name,
                    board_index=board_index,
                    aggregate_event_id=123,
                    aggregate_timestamp=456,
                    board_event_count=123,
                    board_timestamp=456,
                    frame=WaveMonitorFrame(
                        device_name=board_name,
                        event_count=123,
                        timestamp=456,
                        hit_mask=0,
                        send_mode=1,
                        channels=[[board_index] * 4 for _ in range(16)],
                    ),
                ),
            )

        updates = _drain_multi_board_updates(viewer_queue)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].board_name, "dev2")

    def test_multi_board_watch_backend_uses_multi_board_queue_size(self) -> None:
        captured_queue_size: dict[str, int] = {}

        class FakeQueue:
            def __init__(self, maxsize: int) -> None:
                captured_queue_size["value"] = maxsize

            def put_nowait(self, _item) -> None:
                return None

            def get_nowait(self):
                raise queue.Empty

        class FakeStopEvent:
            def is_set(self) -> bool:
                return True

            def set(self) -> None:
                return None

        class FakeThread:
            def __init__(self, *args, **kwargs) -> None:
                return None

            def start(self) -> None:
                return None

            def join(self, timeout: float | None = None) -> None:
                return None

        task_queue: queue.Queue = queue.Queue()
        result_queue: queue.Queue = queue.Queue()

        with patch("queue.Queue", FakeQueue):
            with patch("threading.Event", return_value=FakeStopEvent()):
                with patch("threading.Thread", FakeThread):
                    with patch(
                        "daq_cli.presentation.wave_monitor_viewer.run_multi_board_wave_viewer"
                    ):
                        watch_backend_main(
                            task_queue=task_queue,
                            result_queue=result_queue,
                            group_label="two_board",
                            board_names=["dev1", "dev2"],
                        )

        self.assertEqual(captured_queue_size["value"], 16)

    def test_capture_multi_stops_when_watch_viewer_closes(self) -> None:
        runner = MultiCaptureRunner()
        logs: list[tuple[str, str]] = []
        stop_called = {"value": False}

        class FakeApp:
            def __init__(self) -> None:
                self.stop_event = threading.Event()
                self.receivers = []
                self.logger = SimpleNamespace(log=lambda level, message: logs.append((level, message)))

            def start(self) -> None:
                return None

            def stop(self) -> None:
                stop_called["value"] = True
                self.stop_event.set()

        fake_app = FakeApp()
        result_queue: queue.Queue = queue.Queue()
        result_queue.put(WatchControlMessage(kind="viewer_closed"))
        watch_runtime = MultiBoardWatchRuntime(
            task_queue=queue.Queue(),
            result_queue=result_queue,
            process=_FakeProcess(alive=False),
        )
        fake_app_factory = lambda _cfg, _path, **_kwargs: fake_app
        config = MultiCaptureConfig(
            run_name_prefix="two_board",
            output_base_dir=Path("out/multi"),
            tcm_ip="192.168.10.16",
            tcm_rbcp_port=4660,
            adc_length=256,
            aggregation_key="timestamp",
            timestamp_match_window_ticks=10,
            event_timeout_ms=50,
            tcp_timeout_s=1.0,
            allow_start_without_ack=True,
            boards=[
                SimpleNamespace(name="dev1", ip="192.168.10.10", tcp_port=24, board_id=0),
                SimpleNamespace(name="dev2", ip="192.168.10.11", tcp_port=24, board_id=1),
            ],
            watch_waveforms=True,
            watch_every=100,
            stop_capture_on_watch_close=True,
        )

        with patch.object(
            multi_capture_runner_module, "MultiBoardAcquisitionApp", fake_app_factory
        ):
            with patch.object(runner, "_start_multi_watch_backend", return_value=watch_runtime):
                with patch.object(runner, "_write_temp_config", return_value=Path("out/multi/.daq_cli_tmp/test.json")):
                    with patch.object(runner, "_read_status", return_value="stopped"):
                        with patch.object(
                            multi_capture_runner_module,
                            "allocate_next_run_dir",
                            return_value=Path("out/multi/two_board_00001"),
                        ):
                            result = runner.capture_multi(config)

        self.assertTrue(stop_called["value"])
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.run_output_dir, Path("out/multi/two_board_00001"))
        self.assertTrue(result.stop_capture_on_watch_close)
        self.assertIn(
            ("INFO", "waveform watch closed; stopping acquisition"),
            logs,
        )

    def test_capture_multi_waits_for_decode_backend_summary(self) -> None:
        runner = MultiCaptureRunner()

        class FakeApp:
            def __init__(self) -> None:
                self.stop_event = threading.Event()
                self.receivers = []
                self.logger = SimpleNamespace(log=lambda *_args: None)

            def start(self) -> None:
                self.stop_event.set()

            def stop(self) -> None:
                self.stop_event.set()

        fake_app_factory = lambda _cfg, _path, **_kwargs: FakeApp()
        config = MultiCaptureConfig(
            run_name_prefix="two_board",
            output_base_dir=Path("out/multi"),
            tcm_ip="192.168.10.16",
            tcm_rbcp_port=4660,
            adc_length=256,
            aggregation_key="timestamp",
            timestamp_match_window_ticks=10,
            event_timeout_ms=50,
            tcp_timeout_s=1.0,
            allow_start_without_ack=True,
            boards=[
                SimpleNamespace(name="dev1", ip="192.168.10.10", tcp_port=24, board_id=0),
                SimpleNamespace(name="dev2", ip="192.168.10.11", tcp_port=24, board_id=1),
            ],
            decode_json=True,
        )
        decode_runtime = MultiBoardDecodeRuntime(
            task_queue=queue.Queue(),
            result_queue=queue.Queue(),
            process=_FakeProcess(alive=False),
            output_dir=Path("out/multi/two_board_00001/decoded"),
        )

        with patch.object(
            multi_capture_runner_module, "MultiBoardAcquisitionApp", fake_app_factory
        ):
            with patch.object(
                runner,
                "_write_temp_config",
                return_value=Path("out/multi/.daq_cli_tmp/test.json"),
            ):
                with patch.object(runner, "_read_status", return_value="ok"):
                    with patch.object(
                        multi_capture_runner_module,
                        "allocate_next_run_dir",
                        return_value=Path("out/multi/two_board_00001"),
                    ):
                        with patch.object(
                            runner,
                            "_start_multi_decode_backend",
                            return_value=decode_runtime,
                        ) as start_decode:
                            with patch.object(
                                runner,
                                "_stop_multi_decode_backend",
                                return_value=DecodeDrainResult(
                                    decoded_complete_events=9,
                                    decoded_partial_events=2,
                                    decode_errors=0,
                                ),
                            ) as stop_decode:
                                result = runner.capture_multi(config)

        self.assertTrue(start_decode.called)
        self.assertTrue(stop_decode.called)
        self.assertTrue(result.decode_enabled)
        self.assertEqual(result.run_output_dir, Path("out/multi/two_board_00001"))
        self.assertEqual(result.decoded_complete_events, 9)
        self.assertEqual(result.decoded_partial_events, 2)
        self.assertEqual(result.decode_errors, 0)

    def test_capture_multi_moves_outputs_to_configured_directories(self) -> None:
        runner = MultiCaptureRunner()
        base_dir = Path("tmp_test_outputs") / "multi_outputs_case"
        run_dir = base_dir / "out" / "two_board_00001"
        raw_dir = base_dir / "exports" / "raw"
        json_dir = base_dir / "exports" / "json"
        text_dir = base_dir / "exports" / "text"
        log_dir = base_dir / "exports" / "log"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "complete_events.dat").write_bytes(b"complete")
        (run_dir / "partial_events.dat").write_bytes(b"partial")
        (run_dir / "run_meta.json").write_text('{"status":"ok"}\n', encoding="utf-8")
        (run_dir / "log.txt").write_text("capture log\n", encoding="utf-8")

        class FakeApp:
            def __init__(self) -> None:
                self.stop_event = threading.Event()
                self.receivers = []
                self.logger = SimpleNamespace(log=lambda *_args: None)

            def start(self) -> None:
                self.stop_event.set()

            def stop(self) -> None:
                self.stop_event.set()

        fake_app_factory = lambda _cfg, _path, **_kwargs: FakeApp()
        config = MultiCaptureConfig(
            run_name_prefix="two_board",
            output_base_dir=base_dir / "out",
            tcm_ip="192.168.10.16",
            tcm_rbcp_port=4660,
            adc_length=256,
            aggregation_key="timestamp",
            timestamp_match_window_ticks=10,
            event_timeout_ms=50,
            tcp_timeout_s=1.0,
            allow_start_without_ack=True,
            boards=[
                SimpleNamespace(name="dev1", ip="192.168.10.10", tcp_port=24, board_id=0),
                SimpleNamespace(name="dev2", ip="192.168.10.11", tcp_port=24, board_id=1),
            ],
            outputs=AcquireOutputsConfig(
                raw=OutputTargetConfig(enabled=True, dir=raw_dir),
                json=OutputTargetConfig(enabled=True, dir=json_dir),
                text=TextOutputConfig(
                    enabled=True,
                    dir=text_dir,
                    max_events_per_file=10,
                    waveform_layout="channel_blocks",
                ),
                log=OutputTargetConfig(enabled=True, dir=log_dir),
            ),
        )
        decode_runtime = MultiBoardDecodeRuntime(
            task_queue=queue.Queue(),
            result_queue=queue.Queue(),
            process=_FakeProcess(alive=False),
            output_dir=json_dir / run_dir.name,
            text_output_dir=text_dir / run_dir.name,
        )

        try:
            with patch.object(
                multi_capture_runner_module,
                "MultiBoardAcquisitionApp",
                fake_app_factory,
            ):
                with patch.object(
                    runner,
                    "_write_temp_config",
                    return_value=base_dir / "out" / ".daq_cli_tmp" / "test.json",
                ):
                    with patch.object(
                        multi_capture_runner_module,
                        "allocate_next_run_dir",
                        return_value=run_dir,
                    ):
                        with patch.object(
                            runner,
                            "_start_multi_decode_backend",
                            return_value=decode_runtime,
                        ):
                            with patch.object(
                                runner,
                                "_stop_multi_decode_backend",
                                return_value=DecodeDrainResult(
                                    decoded_complete_events=3,
                                    decoded_partial_events=1,
                                    decode_errors=0,
                                    text_output_complete_events=3,
                                    text_output_partial_events=1,
                                    text_output_files=2,
                                ),
                            ):
                                result = runner.capture_multi(config)

            self.assertEqual(result.raw_output_dir, raw_dir / run_dir.name)
            self.assertEqual(result.json_output_dir, json_dir / run_dir.name)
            self.assertEqual(result.text_output_dir, text_dir / run_dir.name)
            self.assertEqual(result.log_output_dir, log_dir / run_dir.name)
            self.assertTrue((result.raw_output_dir / "complete_events.dat").is_file())
            self.assertTrue((result.raw_output_dir / "partial_events.dat").is_file())
            self.assertTrue((result.meta_path).is_file())
            self.assertTrue((result.log_path).is_file())
            self.assertEqual(result.log_path, log_dir / run_dir.name / "log.txt")
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)

    def test_allocate_next_run_dir_uses_group_prefix_and_ignores_timestamp_dirs(self) -> None:
        base_dir = Path("tmp_test_outputs") / "multi_run_allocator" / uuid.uuid4().hex
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            (base_dir / "two_board_00007").mkdir()
            (base_dir / "two_board_20260616_120000").mkdir()
            (base_dir / "another_00001").mkdir()

            allocated = allocate_next_run_dir(base_dir, "two_board")

            self.assertEqual(allocated.name, "two_board_00008")
            self.assertTrue(allocated.is_dir())
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)

    def test_watch_publisher_assigns_same_aggregate_id_for_same_event_count(self) -> None:
        task_queue: queue.Queue = queue.Queue(maxsize=8)
        publisher = MultiBoardWatchPublisher(
            board_order={0: ("dev1", 0), 1: ("dev2", 1)},
            watch_every=1,
            aggregation_key="event_count",
            timestamp_match_window_ticks=0,
            event_timeout_ms=50,
            task_queue=task_queue,
        )
        frame_a = _build_native_frame(mode=1, hit_mask=0x00FF, event_count=12, timestamp=500)
        frame_b = _build_native_frame(
            mode=1, hit_mask=0x00FF, event_count=12, timestamp=900,
            board_id=1, board_name="dev2",
        )

        publisher.on_frame(frame_a)
        publisher.on_frame(frame_b)

        first = task_queue.get_nowait()
        second = task_queue.get_nowait()
        self.assertEqual(first.aggregate_event_id, second.aggregate_event_id)
        self.assertEqual(first.aggregate_timestamp, 500)
        self.assertEqual(second.aggregate_timestamp, 500)

    def test_watch_publisher_assigns_same_aggregate_id_within_timestamp_window(self) -> None:
        task_queue: queue.Queue = queue.Queue(maxsize=8)
        publisher = MultiBoardWatchPublisher(
            board_order={0: ("dev1", 0), 1: ("dev2", 1)},
            watch_every=1,
            aggregation_key="timestamp",
            timestamp_match_window_ticks=10,
            event_timeout_ms=50,
            task_queue=task_queue,
        )
        frame_a = _build_native_frame(mode=1, hit_mask=0x00FF, event_count=20, timestamp=1000)
        frame_b = _build_native_frame(mode=1, hit_mask=0x00FF, event_count=21, timestamp=1007)
        frame_b.board_id = 1
        frame_b.board_name = "dev2"

        publisher.on_frame(frame_a)
        publisher.on_frame(frame_b)

        first = task_queue.get_nowait()
        second = task_queue.get_nowait()
        self.assertEqual(first.aggregate_event_id, second.aggregate_event_id)
        self.assertEqual(first.aggregate_timestamp, 1000)
        self.assertEqual(second.aggregate_timestamp, 1000)

    def test_watch_publisher_splits_timestamp_aggregates_outside_window(self) -> None:
        task_queue: queue.Queue = queue.Queue(maxsize=8)
        publisher = MultiBoardWatchPublisher(
            board_order={0: ("dev1", 0), 1: ("dev2", 1)},
            watch_every=1,
            aggregation_key="timestamp",
            timestamp_match_window_ticks=10,
            event_timeout_ms=50,
            task_queue=task_queue,
        )
        frame_a = _build_native_frame(mode=1, hit_mask=0x00FF, event_count=20, timestamp=1000)
        frame_b = _build_native_frame(mode=1, hit_mask=0x00FF, event_count=21, timestamp=1020)
        frame_b.board_id = 1
        frame_b.board_name = "dev2"

        publisher.on_frame(frame_a)
        publisher.on_frame(frame_b)

        first = task_queue.get_nowait()
        second = task_queue.get_nowait()
        self.assertNotEqual(first.aggregate_event_id, second.aggregate_event_id)


def _read_fields(packet: bytes):
    class _OneShotSocket:
        def __init__(self, blob: bytes) -> None:
            self._blob = blob

        def recv(self, size: int) -> bytes:
            chunk, self._blob = self._blob[:size], self._blob[size:]
            return chunk

    reader = _TcpSentRawStreamReader(_OneShotSocket(packet), expected_send_mode=None)
    return reader.read_frame()


def _build_native_frame(
    mode: int,
    hit_mask: int,
    event_count: int,
    timestamp: int,
    *,
    format_version: int = 0,
    crossing_fine: int = 0,
    accept_fine: int = 0,
    board_id: int = 0,
    board_name: str = "dev1",
):
    """Build a :class:`MultiBoardFrame` from real wire bytes.

    The packet is constructed with the production layout, then parsed back by
    the stream reader so ``raw_packet``/``feature_bytes``/``waveform_bytes`` are
    exactly what the capture path would produce.
    """
    packet = _build_tcp_sent_packet_v2(
        mode,
        hit_mask,
        event_count,
        format_version=format_version,
        crossing_fine=crossing_fine,
        accept_fine=accept_fine,
    )
    packet = bytearray(packet)
    packet[8:16] = timestamp.to_bytes(8, "big", signed=False)

    class _OneShotSocket:
        def __init__(self, blob: bytes) -> None:
            self._blob = blob

        def recv(self, size: int) -> bytes:
            chunk, self._blob = self._blob[:size], self._blob[size:]
            return chunk

    reader = _TcpSentRawStreamReader(
        _OneShotSocket(bytes(packet)), expected_send_mode=None
    )
    fields = reader.read_frame()
    board = MultiBoardConfig(
        board_id=board_id, name=board_name, ip="192.168.10.10", tcp_port=24
    )
    return frame_from_fields(fields, board, recv_unix_ns=0)


def _bit_count(value: int) -> int:
    count = 0
    while value:
        count += value & 1
        value >>= 1
    return count


def _build_tcp_sent_packet_v2(
    send_mode: int,
    hit_mask: int,
    event_count: int,
    format_version: int = 0,
    crossing_fine: int = 0,
    accept_fine: int = 0,
) -> bytes:
    hit_channels = [channel for channel in range(16) if (hit_mask >> channel) & 0x1]
    hit_count = len(hit_channels)
    has_fine = format_version >= 1
    header = bytearray(28 if has_fine else 20)
    header[:3] = b"\xFF\xFE\x01"
    header[3] = send_mode
    header[4:8] = event_count.to_bytes(4, byteorder="big", signed=False)
    header[8:16] = (event_count * 12345).to_bytes(8, byteorder="big", signed=False)
    header[16:18] = hit_mask.to_bytes(2, byteorder="big", signed=False)
    header[18] = 10 if send_mode in (2, 3) else 0
    header[19] = format_version
    if has_fine:
        header[20:24] = crossing_fine.to_bytes(4, "big", signed=False)
        header[24:28] = accept_fine.to_bytes(4, "big", signed=False)

    payload = bytearray()
    if send_mode in (2, 3):
        for channel in hit_channels:
            payload.extend(bytes([channel]))
            payload.extend((100 + channel).to_bytes(2, "big", signed=False))
            payload.extend((200 + channel).to_bytes(2, "big", signed=False))
            payload.append((channel + 3) & 0xFF)
            payload.extend((channel - 10).to_bytes(4, "big", signed=True))

    if send_mode == 1:
        waveform_channels = list(range(16))
    elif send_mode in (0, 3):
        waveform_channels = hit_channels
    else:
        waveform_channels = []

    for sample_index in range(ADC_LENGTH):
        for channel in waveform_channels:
            value_a = (sample_index + channel) & 0x0FFF
            value_b = (sample_index + channel + 1) & 0x0FFF
            payload.extend((((value_a << 16) | value_b)).to_bytes(4, "big", signed=False))

    return bytes(header + payload)


class _FakeProcess:
    def __init__(self, *, alive: bool) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
