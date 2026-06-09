from pathlib import Path
from types import SimpleNamespace
import queue
import threading
import unittest
from unittest.mock import patch

from daq_cli.infrastructure.adapters.legacy_multi_capture_runner import (
    LegacyMultiCaptureConfig,
    LegacyMultiCaptureRunner,
    MultiBoardDecodeRuntime,
    MultiBoardWatchRuntime,
    _DecodeDrainResult,
    _WatchControlMessage,
    _legacy_frame_to_tcp_sent_packet,
    _MultiBoardWatchPublisher,
    _MultiBoardFrameQueueProxy,
)
from daq_cli.infrastructure.tcp_sent_decode import decode_tcp_sent_packet


ADC_LENGTH = 64


class MultiWaveWatchTests(unittest.TestCase):
    def test_legacy_frame_round_trips_mode1_waveform_packet(self) -> None:
        frame = _build_legacy_frame(mode=1, hit_mask=0x00FF, event_count=12, timestamp=3456)
        packet = _legacy_frame_to_tcp_sent_packet(frame)
        decoded = decode_tcp_sent_packet(packet, source_file=Path("sample.bin"))

        self.assertEqual(decoded.send_mode, 1)
        self.assertEqual(decoded.event_count, 12)
        self.assertEqual(decoded.timestamp, 3456)
        self.assertEqual(decoded.hit_mask, 0x00FF)
        self.assertEqual(len(decoded.channels), 16)
        self.assertTrue(all(channel is not None for channel in decoded.channels))

    def test_legacy_frame_round_trips_mode3_waveform_packet(self) -> None:
        frame = _build_legacy_frame(mode=3, hit_mask=0x0003, event_count=7, timestamp=99)
        packet = _legacy_frame_to_tcp_sent_packet(frame)
        decoded = decode_tcp_sent_packet(packet, source_file=Path("sample.bin"))

        self.assertEqual(decoded.send_mode, 3)
        self.assertEqual(decoded.hit_mask, 0x0003)
        self.assertIsNotNone(decoded.channels[0])
        self.assertIsNotNone(decoded.channels[1])
        self.assertIsNone(decoded.channels[2])

    def test_watch_publisher_samples_every_nth_frame_per_board(self) -> None:
        task_queue: queue.Queue = queue.Queue(maxsize=4)
        publisher = _MultiBoardWatchPublisher(
            board_order={0: ("dev1", 0)},
            watch_every=2,
            task_queue=task_queue,
        )
        frame = _build_legacy_frame(mode=1, hit_mask=0x00FF, event_count=1, timestamp=1)

        publisher.publish(frame)
        self.assertTrue(task_queue.empty())

        publisher.publish(frame)
        sampled = task_queue.get_nowait()
        self.assertEqual(sampled.board_name, "dev1")
        self.assertEqual(sampled.board_index, 0)
        self.assertGreater(len(sampled.packet), 20)

    def test_queue_proxy_forwards_to_aggregator_and_watcher(self) -> None:
        downstream_queue: queue.Queue = queue.Queue()
        task_queue: queue.Queue = queue.Queue(maxsize=1)
        publisher = _MultiBoardWatchPublisher(
            board_order={0: ("dev1", 0)},
            watch_every=1,
            task_queue=task_queue,
        )
        proxy = _MultiBoardFrameQueueProxy(downstream_queue, publisher)
        frame = _build_legacy_frame(mode=1, hit_mask=0x00FF, event_count=1, timestamp=1)

        proxy.put(frame)

        self.assertIs(downstream_queue.get_nowait(), frame)
        sampled = task_queue.get_nowait()
        self.assertEqual(sampled.board_name, "dev1")

    def test_capture_multi_stops_when_watch_viewer_closes(self) -> None:
        runner = LegacyMultiCaptureRunner("legacy")
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
        result_queue.put(_WatchControlMessage(kind="viewer_closed"))
        watch_runtime = MultiBoardWatchRuntime(
            task_queue=queue.Queue(),
            result_queue=result_queue,
            process=_FakeProcess(alive=False),
        )
        fake_module = SimpleNamespace(
            AppConfig=SimpleNamespace(from_json_file=lambda _path: SimpleNamespace()),
            AcquisitionApp=lambda _cfg, _path: fake_app,
        )
        config = LegacyMultiCaptureConfig(
            run_name_prefix="two_board",
            output_base_dir=Path("out/multi"),
            tcm_ip="192.168.10.16",
            tcm_rbcp_port=4660,
            adc_length=64,
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

        with patch(
            "daq_cli.infrastructure.adapters.legacy_multi_capture_runner.importlib.import_module",
            return_value=fake_module,
        ):
            with patch.object(runner, "_start_multi_watch_backend", return_value=watch_runtime):
                with patch.object(runner, "_write_temp_config", return_value=Path("out/multi/.daq_cli_tmp/test.json")):
                    with patch.object(runner, "_read_run_dir", return_value=None):
                        with patch.object(runner, "_read_status", return_value="stopped"):
                            result = runner.capture_multi(config)

        self.assertTrue(stop_called["value"])
        self.assertEqual(result.status, "stopped")
        self.assertTrue(result.stop_capture_on_watch_close)
        self.assertIn(
            ("INFO", "waveform watch closed; stopping acquisition"),
            logs,
        )

    def test_capture_multi_waits_for_decode_backend_summary(self) -> None:
        runner = LegacyMultiCaptureRunner("legacy")

        class FakeApp:
            def __init__(self) -> None:
                self.stop_event = threading.Event()
                self.receivers = []
                self.logger = SimpleNamespace(log=lambda *_args: None)

            def start(self) -> None:
                self.stop_event.set()

            def stop(self) -> None:
                self.stop_event.set()

        fake_module = SimpleNamespace(
            AppConfig=SimpleNamespace(from_json_file=lambda _path: SimpleNamespace()),
            AcquisitionApp=lambda _cfg, _path: FakeApp(),
        )
        config = LegacyMultiCaptureConfig(
            run_name_prefix="two_board",
            output_base_dir=Path("out/multi"),
            tcm_ip="192.168.10.16",
            tcm_rbcp_port=4660,
            adc_length=64,
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
            output_dir=Path("out/multi/two_board_20260607_220846/decoded"),
        )

        with patch(
            "daq_cli.infrastructure.adapters.legacy_multi_capture_runner.importlib.import_module",
            return_value=fake_module,
        ):
            with patch.object(
                runner,
                "_write_temp_config",
                return_value=Path("out/multi/.daq_cli_tmp/test.json"),
            ):
                with patch.object(
                    runner,
                    "_read_run_dir",
                    side_effect=[
                        Path("out/multi/two_board_20260607_220846"),
                        Path("out/multi/two_board_20260607_220846"),
                    ],
                ):
                    with patch.object(runner, "_read_status", return_value="ok"):
                        with patch.object(
                            runner,
                            "_start_multi_decode_backend",
                            return_value=decode_runtime,
                        ) as start_decode:
                            with patch.object(
                                runner,
                                "_stop_multi_decode_backend",
                                return_value=_DecodeDrainResult(
                                    decoded_complete_events=9,
                                    decoded_partial_events=2,
                                    decode_errors=0,
                                ),
                            ) as stop_decode:
                                result = runner.capture_multi(config)

        self.assertTrue(start_decode.called)
        self.assertTrue(stop_decode.called)
        self.assertTrue(result.decode_enabled)
        self.assertEqual(result.decoded_complete_events, 9)
        self.assertEqual(result.decoded_partial_events, 2)
        self.assertEqual(result.decode_errors, 0)


def _build_legacy_frame(mode: int, hit_mask: int, event_count: int, timestamp: int):
    hit_count = _bit_count(hit_mask)
    feature_size = 10 if mode in (2, 3) else 0
    feature_bytes = b""
    if mode in (2, 3):
        feature_chunks = []
        for channel_index in range(hit_count):
            feature_chunks.append(
                bytes([channel_index])
                + (100 + channel_index).to_bytes(2, "big")
                + (200 + channel_index).to_bytes(2, "big")
                + bytes([channel_index])
                + (300 + channel_index).to_bytes(4, "big", signed=True)
            )
        feature_bytes = b"".join(feature_chunks)

    waveform_channel_count = 16 if mode == 1 else hit_count if mode in (0, 3) else 0
    waveform_words = bytearray()
    for sample_index in range(ADC_LENGTH):
        for channel_index in range(waveform_channel_count):
            value_a = (sample_index + channel_index) & 0x0FFF
            value_b = (sample_index + channel_index + 1) & 0x0FFF
            word = (value_a << 16) | value_b
            waveform_words.extend(word.to_bytes(4, "big", signed=False))

    return SimpleNamespace(
        board_id=0,
        board_name="dev1",
        board_ip="192.168.10.10",
        mode=mode,
        event_count=event_count,
        timestamp=timestamp,
        hit_mask=hit_mask,
        feature_size=feature_size,
        feature_bytes=feature_bytes,
        waveform_bytes=bytes(waveform_words),
        reconnect_mark=False,
    )


def _bit_count(value: int) -> int:
    count = 0
    while value:
        count += value & 1
        value >>= 1
    return count


class _FakeProcess:
    def __init__(self, *, alive: bool) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
