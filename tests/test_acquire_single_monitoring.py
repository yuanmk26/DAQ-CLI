from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
import uuid
import queue
import threading
from unittest.mock import patch

from typer.testing import CliRunner

from daq_cli.application.acquire_service import (
    AcquireService,
    SingleAcquireProgress,
    SingleAcquireResult,
)
from daq_cli.domain.tcm import TcmConfig
from daq_cli.application.output_config import (
    AcquireOutputsConfig,
    OutputTargetConfig,
    TextOutputConfig,
)
from daq_cli.cli.app import app
from daq_cli.infrastructure.adapters.legacy_capture_runner import (
    ADC_LENGTH,
    DecodeBackendRuntime,
    FEATURE_BYTES,
    HEADER_BYTES,
    LegacySingleCaptureRunner,
    MODE2_MAGIC,
    WatchBackendRuntime,
    _decode_worker_main,
    _frame_total_size,
    _Mode2RawStreamReader,
)
from daq_cli.infrastructure.run_name_allocator import allocate_next_run_dir


class AcquireSingleMonitoringTests(unittest.TestCase):
    def test_mode2_reader_reads_complete_packet(self) -> None:
        packet = _build_tcp_sent_packet(send_mode=2, hit_mask=0x0003, event_count=1)
        reader = _Mode2RawStreamReader(
            FakeSocket([packet[:23], packet[23:]]),
            expected_send_mode=2,
        )
        self.assertEqual(reader.read_packet(), packet)

    def test_mode2_reader_rejects_non_mode2_packets(self) -> None:
        bad_packet = _build_tcp_sent_packet(send_mode=1, hit_mask=0x0001, event_count=1)
        reader = _Mode2RawStreamReader(
            FakeSocket([bad_packet]),
            expected_send_mode=2,
        )
        with self.assertRaises(ValueError):
            reader.read_packet()

    def test_mode2_reader_rejects_unexpected_feature_size(self) -> None:
        bad_packet = bytearray(
            _build_tcp_sent_packet(send_mode=2, hit_mask=0x0001, event_count=1)
        )
        bad_packet[18] = 9
        reader = _Mode2RawStreamReader(
            FakeSocket([bytes(bad_packet)]),
            expected_send_mode=2,
        )
        with self.assertRaises(ValueError):
            reader.read_packet()

    def test_frame_total_size_uses_send_mode_specific_lengths(self) -> None:
        self.assertEqual(_frame_total_size(send_mode=0, hit_count=2, adc_length=64, feature_bytes=10), 532)
        self.assertEqual(_frame_total_size(send_mode=1, hit_count=2, adc_length=64, feature_bytes=10), 4116)
        self.assertEqual(_frame_total_size(send_mode=2, hit_count=2, adc_length=64, feature_bytes=10), 40)
        self.assertEqual(_frame_total_size(send_mode=3, hit_count=2, adc_length=64, feature_bytes=10), 552)

    def test_parallel_runner_writes_files_and_reports_progress(self) -> None:
        packets = [
            _build_tcp_sent_packet(send_mode=2, hit_mask=0x0001, event_count=1),
            _build_tcp_sent_packet(send_mode=2, hit_mask=0x0003, event_count=2),
        ]
        progress_updates = []
        runner = LegacySingleCaptureRunner("legacy")

        base_dir = self._make_workspace_temp_dir()
        try:
            with patch.object(
                runner,
                "_open_socket",
                return_value=FakeSocket(packets),
            ):
                result = runner.capture_single(
                    device=SimpleNamespace(ip="192.168.10.10", tcp_port=24),
                    output_base_dir=base_dir,
                    events=2,
                    timeout_s=1.0,
                    send_mode=2,
                    progress_callback=progress_updates.append,
                )

            self.assertEqual(result.captured_events, 2)
            self.assertEqual(result.send_mode, 2)
            self.assertFalse(result.decode_enabled)
            self.assertIsNone(result.decoded_output_dir)
            self.assertEqual(result.decoded_events, 0)
            self.assertEqual(result.decode_errors, 0)
            self.assertFalse(result.watch_enabled)
            self.assertIsNone(result.watch_every)
            self.assertEqual(result.watched_frames, 0)
            self.assertIsNotNone(result.run_output_dir)
            self.assertEqual(result.run_output_dir.name, "acquire_00001")
            self.assertTrue((result.run_output_dir / "raw" / "event_00000.bin").is_file())
            self.assertTrue((result.run_output_dir / "raw" / "event_00001.bin").is_file())
            info_text = (result.run_output_dir / "capture_info.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn("captured_events=2", info_text)
            self.assertIn("send_mode=2", info_text)
            self.assertIn("queue_maxsize=128", info_text)
            self.assertIn("capture_mode=parallel", info_text)
            self.assertIn("watch_enabled=0", info_text)
            self.assertEqual(progress_updates[-1].captured_events, 2)
            self.assertEqual(progress_updates[-1].hit_mask, 0x0003)
            self.assertEqual(progress_updates[-1].output_dir, result.run_output_dir)
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)

    def test_parallel_runner_with_decode_json_writes_decoded_outputs(self) -> None:
        packets = [
            _build_tcp_sent_packet(send_mode=1, hit_mask=0x00FF, event_count=1),
            _build_tcp_sent_packet(send_mode=1, hit_mask=0x0FFF, event_count=2),
        ]
        runner = LegacySingleCaptureRunner("legacy")
        base_dir = self._make_workspace_temp_dir()
        try:
            with patch.object(
                runner,
                "_open_socket",
                return_value=FakeSocket(packets),
            ):
                with patch.object(
                    runner,
                    "_start_decode_backend",
                    return_value=_make_fake_decode_backend(),
                ):
                    result = runner.capture_single(
                        device=SimpleNamespace(ip="192.168.10.10", tcp_port=24),
                        output_base_dir=base_dir,
                        events=2,
                        timeout_s=1.0,
                        send_mode=1,
                        decode_json=True,
                    )

            self.assertTrue(result.decode_enabled)
            self.assertIsNotNone(result.decoded_output_dir)
            self.assertEqual(result.run_output_dir.name, "acquire_00001")
            self.assertEqual(result.decoded_events, 2)
            self.assertEqual(result.decode_errors, 0)
            self.assertFalse(result.watch_enabled)
            self.assertTrue((result.decoded_output_dir / "event_00000.json").is_file())
            self.assertTrue((result.decoded_output_dir / "event_00001.json").is_file())
            info_text = (result.run_output_dir / "capture_info.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn("decode_enabled=1", info_text)
            self.assertIn("decoded_events=2", info_text)
            self.assertIn("decode_errors=0", info_text)
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)

    def test_parallel_runner_text_output_appends_multiple_events_per_file(self) -> None:
        packets = [
            _build_tcp_sent_packet(send_mode=1, hit_mask=0x00FF, event_count=1),
            _build_tcp_sent_packet(send_mode=1, hit_mask=0x00FF, event_count=2),
        ]
        runner = LegacySingleCaptureRunner("legacy")
        base_dir = self._make_workspace_temp_dir()
        try:
            with patch.object(
                runner,
                "_open_socket",
                return_value=FakeSocket(packets),
            ):
                with patch.object(
                    runner,
                    "_start_decode_backend",
                    return_value=_make_fake_decode_backend(),
                ):
                    result = runner.capture_single(
                        device=SimpleNamespace(name="dev1", ip="192.168.10.10", tcp_port=24),
                        output_base_dir=base_dir,
                        events=2,
                        timeout_s=1.0,
                        send_mode=1,
                        text_output_enabled=True,
                        text_max_events_per_file=10,
                    )

            self.assertTrue(result.text_output_enabled)
            self.assertEqual(result.run_output_dir.name, "dev1_00001")
            self.assertEqual(result.text_output_events, 2)
            self.assertEqual(result.text_output_files, 1)
            text_path = result.text_output_dir / "events_00001.txt"
            self.assertTrue(text_path.is_file())
            content = text_path.read_text(encoding="utf-8")
            self.assertIn("===== EVENT 1 =====", content)
            self.assertIn("===== EVENT 2 =====", content)
            self.assertEqual(content.count("===== END EVENT"), 2)
            self.assertIn("waveforms:", content)
            self.assertNotIn("waveform_samples:", content)
            self.assertNotIn("ch00:", content)
            waveform_lines = content.splitlines()
            header_line = waveform_lines[waveform_lines.index("waveforms:") + 1]
            first_row = waveform_lines[waveform_lines.index("waveforms:") + 2]
            self.assertEqual(
                header_line.split(),
                [f"ch{channel_index:02d}" for channel_index in range(16)],
            )
            self.assertEqual(
                first_row.split(),
                [str(channel_index) for channel_index in range(16)],
            )
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)

    def test_parallel_runner_text_output_rolls_over_after_event_limit(self) -> None:
        packets = [
            _build_tcp_sent_packet(send_mode=1, hit_mask=0x00FF, event_count=1),
            _build_tcp_sent_packet(send_mode=1, hit_mask=0x00FF, event_count=2),
        ]
        runner = LegacySingleCaptureRunner("legacy")
        base_dir = self._make_workspace_temp_dir()
        try:
            with patch.object(
                runner,
                "_open_socket",
                return_value=FakeSocket(packets),
            ):
                with patch.object(
                    runner,
                    "_start_decode_backend",
                    return_value=_make_fake_decode_backend(),
                ):
                    result = runner.capture_single(
                        device=SimpleNamespace(name="dev1", ip="192.168.10.10", tcp_port=24),
                        output_base_dir=base_dir,
                        events=2,
                        timeout_s=1.0,
                        send_mode=1,
                        text_output_enabled=True,
                        text_max_events_per_file=1,
                    )

            self.assertEqual(result.text_output_files, 2)
            self.assertEqual(result.run_output_dir.name, "dev1_00001")
            self.assertTrue((result.text_output_dir / "events_00001.txt").is_file())
            self.assertTrue((result.text_output_dir / "events_00002.txt").is_file())
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)

    def test_parallel_runner_supports_custom_output_directories(self) -> None:
        packets = [_build_tcp_sent_packet(send_mode=1, hit_mask=0x00FF, event_count=1)]
        runner = LegacySingleCaptureRunner("legacy")
        base_dir = self._make_workspace_temp_dir()
        raw_dir = base_dir / "exports" / "raw"
        json_dir = base_dir / "exports" / "json"
        text_dir = base_dir / "exports" / "text"
        log_dir = base_dir / "exports" / "log"
        try:
            with patch.object(
                runner,
                "_open_socket",
                return_value=FakeSocket(packets),
            ):
                with patch.object(
                    runner,
                    "_start_decode_backend",
                    return_value=_make_fake_decode_backend(),
                ):
                    result = runner.capture_single(
                        device=SimpleNamespace(name="dev1", ip="192.168.10.10", tcp_port=24),
                        output_base_dir=base_dir,
                        events=1,
                        timeout_s=1.0,
                        send_mode=1,
                        outputs=AcquireOutputsConfig(
                            raw=OutputTargetConfig(enabled=True, dir=raw_dir),
                            json=OutputTargetConfig(enabled=True, dir=json_dir),
                            text=TextOutputConfig(
                                enabled=True,
                                dir=text_dir,
                                max_events_per_file=5,
                                waveform_layout="channel_blocks",
                            ),
                            log=OutputTargetConfig(enabled=True, dir=log_dir),
                        ),
                    )

            self.assertEqual(result.raw_output_dir, raw_dir / result.run_output_dir.name)
            self.assertEqual(result.run_output_dir.name, "dev1_00001")
            self.assertEqual(result.json_output_dir, json_dir / result.run_output_dir.name)
            self.assertEqual(result.text_output_dir, text_dir / result.run_output_dir.name)
            self.assertEqual(result.log_output_path, log_dir / result.run_output_dir.name / "capture.log")
            self.assertTrue((result.raw_output_dir / "event_00000.bin").is_file())
            self.assertTrue((result.json_output_dir / "event_00000.json").is_file())
            self.assertTrue((result.text_output_dir / "events_00001.txt").is_file())
            self.assertTrue(result.log_output_path.is_file())
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)

    def test_parallel_runner_decode_failure_keeps_raw_capture_and_counts_error(self) -> None:
        packets = [_build_tcp_sent_packet(send_mode=1, hit_mask=0xFFFF, event_count=1)]
        runner = LegacySingleCaptureRunner("legacy")
        base_dir = self._make_workspace_temp_dir()
        try:
            with patch.object(
                runner,
                "_open_socket",
                return_value=FakeSocket(packets),
            ):
                original_write_packet_file = runner._write_packet_file

                def corrupting_write_packet_file(raw_dir, packet):
                    path = original_write_packet_file(raw_dir, packet)
                    path.write_bytes(path.read_bytes()[:-1])
                    return path

                with patch.object(
                    runner,
                    "_write_packet_file",
                    side_effect=corrupting_write_packet_file,
                ):
                    with patch.object(
                        runner,
                        "_start_decode_backend",
                        return_value=_make_fake_decode_backend(),
                    ):
                        result = runner.capture_single(
                            device=SimpleNamespace(ip="192.168.10.10", tcp_port=24),
                            output_base_dir=base_dir,
                            events=1,
                            timeout_s=1.0,
                            send_mode=1,
                            decode_json=True,
                        )

            self.assertEqual(result.captured_events, 1)
            self.assertEqual(result.run_output_dir.name, "acquire_00001")
            self.assertEqual(result.decoded_events, 0)
            self.assertEqual(result.decode_errors, 1)
            self.assertEqual(result.watched_frames, 0)
            self.assertTrue((result.run_output_dir / "raw" / "event_00000.bin").is_file())
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)

    def test_parallel_runner_decode_queue_full_does_not_block_raw_capture(self) -> None:
        packets = [
            _build_tcp_sent_packet(send_mode=1, hit_mask=0xFFFF, event_count=1),
            _build_tcp_sent_packet(send_mode=1, hit_mask=0xFFFF, event_count=2),
        ]
        runner = LegacySingleCaptureRunner("legacy")
        base_dir = self._make_workspace_temp_dir()
        try:
            with patch.object(
                runner,
                "_open_socket",
                return_value=FakeSocket(packets),
            ):
                with patch.object(
                    runner,
                    "_start_decode_backend",
                    return_value=_make_fake_decode_backend(maxsize=1, slow=True),
                ):
                    with patch.object(
                        runner,
                        "_try_publish_decode_item",
                        side_effect=[False, False],
                    ):
                        result = runner.capture_single(
                            device=SimpleNamespace(ip="192.168.10.10", tcp_port=24),
                            output_base_dir=base_dir,
                            events=2,
                            timeout_s=1.0,
                            send_mode=1,
                            decode_json=True,
                        )

            self.assertEqual(result.captured_events, 2)
            self.assertEqual(result.run_output_dir.name, "acquire_00001")
            self.assertEqual(result.decoded_events, 2)
            self.assertEqual(result.decode_errors, 0)
            self.assertEqual(result.watched_frames, 0)
            self.assertTrue((result.run_output_dir / "raw" / "event_00000.bin").is_file())
            self.assertTrue((result.run_output_dir / "raw" / "event_00001.bin").is_file())
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)

    def test_parallel_runner_watch_every_samples_without_blocking_capture(self) -> None:
        packets = [
            _build_tcp_sent_packet(send_mode=1, hit_mask=0x00FF, event_count=1),
            _build_tcp_sent_packet(send_mode=1, hit_mask=0x00FF, event_count=2),
            _build_tcp_sent_packet(send_mode=1, hit_mask=0x00FF, event_count=3),
            _build_tcp_sent_packet(send_mode=1, hit_mask=0x00FF, event_count=4),
        ]
        runner = LegacySingleCaptureRunner("legacy")
        base_dir = self._make_workspace_temp_dir()
        try:
            with patch.object(
                runner,
                "_open_socket",
                return_value=FakeSocket(packets),
            ):
                with patch.object(
                    runner,
                    "_start_watch_backend",
                    return_value=_make_fake_watch_backend(),
                ):
                    result = runner.capture_single(
                        device=SimpleNamespace(name="dev1", ip="192.168.10.10", tcp_port=24),
                        output_base_dir=base_dir,
                        events=4,
                        timeout_s=1.0,
                        send_mode=1,
                        watch_every=2,
                    )

            self.assertTrue(result.watch_enabled)
            self.assertEqual(result.run_output_dir.name, "dev1_00001")
            self.assertEqual(result.watch_every, 2)
            self.assertGreaterEqual(result.watched_frames, 1)
            info_text = (result.run_output_dir / "capture_info.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn("watch_enabled=1", info_text)
            self.assertIn("watch_every=2", info_text)
            self.assertIn(f"watched_frames={result.watched_frames}", info_text)
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)

    def test_parallel_runner_raises_on_writer_error_after_partial_capture(self) -> None:
        packets = [
            _build_tcp_sent_packet(send_mode=2, hit_mask=0x0001, event_count=1),
            _build_tcp_sent_packet(send_mode=2, hit_mask=0x0003, event_count=2),
        ]
        runner = LegacySingleCaptureRunner("legacy")

        base_dir = self._make_workspace_temp_dir()
        try:
            with patch.object(
                runner,
                "_open_socket",
                return_value=FakeSocket(packets),
            ):
                with patch.object(
                    runner,
                    "_write_packet_file",
                    side_effect=[None, OSError("disk full")],
                ):
                    with self.assertRaises(OSError):
                        runner.capture_single(
                            device=SimpleNamespace(ip="192.168.10.10", tcp_port=24),
                            output_base_dir=base_dir,
                            events=2,
                            timeout_s=1.0,
                            send_mode=2,
                        )
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)

    def test_allocate_next_run_dir_uses_incrementing_numeric_suffix(self) -> None:
        base_dir = self._make_workspace_temp_dir()
        try:
            (base_dir / "dev1_00001").mkdir()
            (base_dir / "dev1_00002").mkdir()
            (base_dir / "dev1_20260616_120000").mkdir()
            (base_dir / "other_00099").mkdir()

            allocated = allocate_next_run_dir(base_dir, "dev1")

            self.assertEqual(allocated.name, "dev1_00003")
            self.assertTrue(allocated.is_dir())
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)

    def test_acquire_service_emits_progress_with_positive_rate(self) -> None:
        profile = SimpleNamespace(
            path=Path("profiles/example.yaml"),
            devices={"dev1": SimpleNamespace(name="dev1")},
            defaults={"output_dir": "out"},
            legacy=SimpleNamespace(project_root=Path("legacy")),
        )
        service = AcquireService()
        progress_updates: list[SingleAcquireProgress] = []

        def fake_capture_single(**kwargs):
            callback = kwargs["progress_callback"]
            callback(
                SimpleNamespace(
                    captured_events=1,
                    packet_bytes=3212,
                    hit_mask=0x0001,
                    output_dir=None,
                )
            )
            callback(
                SimpleNamespace(
                    captured_events=2,
                    packet_bytes=3212,
                    hit_mask=0x0003,
                    output_dir=Path("out/single/20260606_201703"),
                )
            )
            return SimpleNamespace(
                run_output_dir=Path("out/single/20260606_201703"),
                captured_events=2,
                send_mode=2,
                decode_enabled=False,
                decoded_output_dir=None,
                decoded_events=0,
                decode_errors=0,
                watch_enabled=False,
                watch_every=None,
                watched_frames=0,
                log_output="captured log",
            )

        with patch.object(service._profile_service, "load_profile", return_value=profile):
            with patch(
                "daq_cli.application.acquire_service.LegacyBoardAdapter"
            ) as board_adapter_cls:
                board_adapter_cls.return_value.read_tcp_mode2_config.return_value = (
                    SimpleNamespace(send_mode=2)
                )
                with patch(
                    "daq_cli.application.acquire_service.LegacySingleCaptureRunner"
                ) as runner_cls:
                    runner_cls.return_value.capture_single.side_effect = fake_capture_single
                    result = service.capture_single(
                        device_name="dev1",
                        profile_path="profiles/example.yaml",
                        events=2,
                        timeout_s=1.0,
                        progress_callback=progress_updates.append,
                    )
                    self.assertEqual(
                        runner_cls.return_value.capture_single.call_args.kwargs[
                            "send_mode"
                        ],
                        2,
                    )

        self.assertEqual(result.captured_events, 2)
        self.assertEqual(result.send_mode, 2)
        self.assertEqual(progress_updates[-1].requested_events, 2)
        self.assertGreater(progress_updates[-1].event_rate_hz, 0.0)
        self.assertEqual(progress_updates[-1].hit_mask, 0x0003)
        self.assertEqual(
            progress_updates[-1].output_dir, Path("out/single/20260606_201703")
        )

    def test_cli_single_shows_realtime_monitoring_fields(self) -> None:
        runner = CliRunner()
        progress = SingleAcquireProgress(
            captured_events=3,
            requested_events=10,
            packet_bytes=3212,
            hit_mask=0x00AF,
            output_dir=Path("out/single/20260606_201703"),
            event_rate_hz=12.5,
        )
        result_payload = SingleAcquireResult(
            device=SimpleNamespace(name="dev1"),
            source_profile=Path("profiles/example.yaml"),
            output_base_dir=Path("out/single"),
            run_output_dir=Path("out/single/20260606_201703"),
            requested_events=10,
            captured_events=10,
            send_mode=2,
            decode_enabled=True,
            decoded_output_dir=Path("out/single/20260606_201703/decoded"),
            decoded_events=10,
            decode_errors=0,
            watch_enabled=True,
            watch_every=5,
            watched_frames=2,
            tcp_timeout_s=10.0,
            log_output="legacy log output",
        )

        with patch("daq_cli.cli.acquire.AcquireService") as service_cls:
            service = service_cls.return_value

            def fake_capture_single(**kwargs):
                kwargs["progress_callback"](progress)
                return result_payload

            service.capture_single.side_effect = fake_capture_single
            result = runner.invoke(
                app,
                [
                    "acquire",
                    "single",
                    "dev1",
                    "--events",
                    "10",
                    "--progress-every",
                    "1",
                    "--decode-json",
                    "--profile",
                    "profiles/example.yaml",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("events=3/10", result.output)
        self.assertIn("rate=12.50Hz", result.output)
        self.assertIn("hit_mask=0x00AF", result.output)
        self.assertIn("bytes=3212", result.output)
        self.assertIn("Single Acquire: dev1", result.output)
        self.assertIn("send_mode", result.output)
        self.assertIn("decode_enabled", result.output)
        self.assertIn("decoded_events", result.output)
        self.assertIn("watch_enabled", result.output)
        self.assertIn("watched_frames", result.output)

    def test_cli_single_throttles_progress_output_by_event_interval(self) -> None:
        runner = CliRunner()
        result_payload = SingleAcquireResult(
            device=SimpleNamespace(name="dev1"),
            source_profile=Path("profiles/example.yaml"),
            output_base_dir=Path("out/single"),
            run_output_dir=Path("out/single/20260606_201703"),
            requested_events=10,
            captured_events=10,
            send_mode=2,
            decode_enabled=False,
            decoded_output_dir=None,
            decoded_events=0,
            decode_errors=0,
            watch_enabled=False,
            watch_every=None,
            watched_frames=0,
            tcp_timeout_s=10.0,
            log_output="legacy log output",
        )

        with patch("daq_cli.cli.acquire.AcquireService") as service_cls:
            service = service_cls.return_value

            def fake_capture_single(**kwargs):
                callback = kwargs["progress_callback"]
                for event_index in range(1, 11):
                    callback(
                        SingleAcquireProgress(
                            captured_events=event_index,
                            requested_events=10,
                            packet_bytes=3212,
                            hit_mask=0x00AF,
                            output_dir=Path("out/single/20260606_201703"),
                            event_rate_hz=12.5,
                        )
                    )
                return result_payload

            service.capture_single.side_effect = fake_capture_single
            result = runner.invoke(
                app,
                [
                    "acquire",
                    "single",
                    "dev1",
                    "--events",
                    "10",
                    "--progress-every",
                    "5",
                    "--profile",
                    "profiles/example.yaml",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("events=0/10", result.output)
        self.assertIn("events=5/10", result.output)
        self.assertIn("events=10/10", result.output)
        self.assertNotIn("events=1/10", result.output)
        self.assertNotIn("events=6/10", result.output)

    def test_cli_single_uses_profile_acquire_defaults_when_options_omitted(self) -> None:
        runner = CliRunner()
        profile = SimpleNamespace(
            defaults={
                "acquire_single": {
                    "events": 25,
                    "timeout_s": 3.5,
                    "decode_json": True,
                    "watch_every": 5,
                    "progress_every": 10,
                }
            }
        )
        result_payload = SingleAcquireResult(
            device=SimpleNamespace(name="dev1"),
            source_profile=Path("profiles/example.yaml"),
            output_base_dir=Path("out/single"),
            run_output_dir=Path("out/single/20260606_201703"),
            requested_events=25,
            captured_events=25,
            send_mode=2,
            decode_enabled=True,
            decoded_output_dir=Path("out/single/20260606_201703/decoded"),
            decoded_events=25,
            decode_errors=0,
            watch_enabled=True,
            watch_every=5,
            watched_frames=5,
            tcp_timeout_s=3.5,
            log_output="legacy log output",
        )

        with patch("daq_cli.cli.acquire.ProfileService") as profile_service_cls:
            profile_service_cls.return_value.load_profile.return_value = profile
            with patch("daq_cli.cli.acquire.AcquireService") as service_cls:
                service = service_cls.return_value
                service.capture_single.return_value = result_payload
                result = runner.invoke(
                    app,
                    [
                        "acquire",
                        "single",
                        "dev1",
                        "--profile",
                        "profiles/example.yaml",
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        kwargs = service.capture_single.call_args.kwargs
        self.assertEqual(kwargs["events"], 25)
        self.assertEqual(kwargs["timeout_s"], 3.5)
        self.assertIsInstance(kwargs["outputs"], AcquireOutputsConfig)
        self.assertTrue(kwargs["outputs"].json.enabled)
        self.assertEqual(kwargs["watch_every"], 5)
        self.assertIn("events=0/25", result.output)

    def test_cli_multi_uses_profile_acquire_defaults_when_options_omitted(self) -> None:
        runner = CliRunner()
        profile = SimpleNamespace(
            defaults={
                "acquire_multi": {
                    "aggregation_key": "event_count",
                    "timestamp_match_window_ticks": 20,
                    "event_timeout_ms": 80,
                    "tcp_timeout_s": 2.5,
                    "allow_start_without_ack": True,
                    "decode_json": True,
                }
            }
        )
        result_payload = SimpleNamespace(
            group=SimpleNamespace(name="two_board"),
            devices=[SimpleNamespace(name="dev1"), SimpleNamespace(name="dev2")],
            source_profile=Path("profiles/example.yaml"),
            output_base_dir=Path("out/multi"),
            run_output_dir=Path("out/multi/two_board_20260607_220846"),
            aggregation_key="event_count",
            timestamp_match_window_ticks=20,
            tcp_timeout_s=2.5,
            allow_start_without_ack=True,
            decode_enabled=True,
            decoded_output_dir=Path("out/multi/two_board_20260607_220846/decoded"),
            decoded_complete_events=20,
            decoded_partial_events=1,
            decode_errors=0,
            watch_waveforms=False,
            watch_every=None,
            watched_frames=0,
            stop_capture_on_watch_close=True,
            config_path=Path("out/multi/.daq_cli_tmp/multi_board_acquire.config.json"),
            meta_path=Path("out/multi/two_board_20260607_220846/run_meta.json"),
            log_path=Path("out/multi/two_board_20260607_220846/log.txt"),
            status="ok",
        )

        with patch("daq_cli.cli.acquire.ProfileService") as profile_service_cls:
            profile_service_cls.return_value.load_profile.return_value = profile
            with patch("daq_cli.cli.acquire.AcquireService") as service_cls:
                service = service_cls.return_value
                service.capture_multi.return_value = result_payload
                result = runner.invoke(
                    app,
                    [
                        "acquire",
                        "multi",
                        "two_board",
                        "--profile",
                        "profiles/example.yaml",
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        kwargs = service.capture_multi.call_args.kwargs
        self.assertEqual(kwargs["aggregation_key"], "event_count")
        self.assertEqual(kwargs["timestamp_match_window_ticks"], 20)
        self.assertEqual(kwargs["event_timeout_ms"], 80)
        self.assertEqual(kwargs["tcp_timeout_s"], 2.5)
        self.assertTrue(kwargs["allow_start_without_ack"])
        self.assertIsInstance(kwargs["outputs"], AcquireOutputsConfig)
        self.assertTrue(kwargs["outputs"].json.enabled)
        self.assertTrue(kwargs["stop_capture_on_watch_close"])

    def test_cli_multi_accepts_keep_running_after_watch_close(self) -> None:
        runner = CliRunner()
        result_payload = SimpleNamespace(
            group=SimpleNamespace(name="two_board"),
            devices=[SimpleNamespace(name="dev1"), SimpleNamespace(name="dev2")],
            source_profile=Path("profiles/example.yaml"),
            output_base_dir=Path("out/multi"),
            run_output_dir=Path("out/multi/two_board_20260607_220846"),
            aggregation_key="event_count",
            timestamp_match_window_ticks=20,
            tcp_timeout_s=2.5,
            allow_start_without_ack=True,
            decode_enabled=False,
            decoded_output_dir=None,
            decoded_complete_events=0,
            decoded_partial_events=0,
            decode_errors=0,
            watch_waveforms=True,
            watch_every=100,
            watched_frames=2,
            stop_capture_on_watch_close=False,
            config_path=Path("out/multi/.daq_cli_tmp/multi_board_acquire.config.json"),
            meta_path=Path("out/multi/two_board_20260607_220846/run_meta.json"),
            log_path=Path("out/multi/two_board_20260607_220846/log.txt"),
            status="ok",
        )

        with patch("daq_cli.cli.acquire.AcquireService") as service_cls:
            service = service_cls.return_value
            service.capture_multi.return_value = result_payload
            result = runner.invoke(
                app,
                [
                    "acquire",
                    "multi",
                    "two_board",
                    "--watch-waveforms",
                    "--keep-running-after-watch-close",
                    "--profile",
                    "profiles/example.yaml",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        kwargs = service.capture_multi.call_args.kwargs
        self.assertTrue(kwargs["watch_waveforms"])
        self.assertFalse(kwargs["stop_capture_on_watch_close"])
        self.assertIsInstance(kwargs["outputs"], AcquireOutputsConfig)

    def test_cli_multi_passes_decode_json_flag(self) -> None:
        runner = CliRunner()
        result_payload = SimpleNamespace(
            group=SimpleNamespace(name="two_board"),
            devices=[SimpleNamespace(name="dev1"), SimpleNamespace(name="dev2")],
            source_profile=Path("profiles/example.yaml"),
            output_base_dir=Path("out/multi"),
            run_output_dir=Path("out/multi/two_board_20260607_220846"),
            aggregation_key="timestamp",
            timestamp_match_window_ticks=10,
            tcp_timeout_s=1.0,
            allow_start_without_ack=True,
            decode_enabled=True,
            decoded_output_dir=Path("out/multi/two_board_20260607_220846/decoded"),
            decoded_complete_events=2,
            decoded_partial_events=1,
            decode_errors=0,
            watch_waveforms=False,
            watch_every=None,
            watched_frames=0,
            stop_capture_on_watch_close=True,
            config_path=Path("out/multi/.daq_cli_tmp/multi_board_acquire.config.json"),
            meta_path=Path("out/multi/two_board_20260607_220846/run_meta.json"),
            log_path=Path("out/multi/two_board_20260607_220846/log.txt"),
            status="ok",
        )

        with patch("daq_cli.cli.acquire.AcquireService") as service_cls:
            service = service_cls.return_value
            service.capture_multi.return_value = result_payload
            result = runner.invoke(
                app,
                [
                    "acquire",
                    "multi",
                    "two_board",
                    "--decode-json",
                    "--profile",
                    "profiles/example.yaml",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        kwargs = service.capture_multi.call_args.kwargs
        self.assertIsInstance(kwargs["outputs"], AcquireOutputsConfig)
        self.assertTrue(kwargs["outputs"].json.enabled)
        self.assertIn("decode_enabled", result.output)
        self.assertIn("decoded_complete_events", result.output)

    def test_cli_single_outputs_can_enable_text_without_json(self) -> None:
        runner = CliRunner()
        profile = SimpleNamespace(
            defaults={
                "acquire_single": {
                    "outputs": {
                        "json": {"enabled": False},
                        "text": {
                            "enabled": True,
                            "dir": "txt_out",
                            "max_events_per_file": 7,
                            "waveform_layout": "channel_blocks",
                        },
                        "raw": {"enabled": True, "dir": "raw_out"},
                        "log": {"enabled": False},
                    }
                }
            }
        )
        result_payload = SingleAcquireResult(
            device=SimpleNamespace(name="dev1"),
            source_profile=Path("profiles/example.yaml"),
            output_base_dir=Path("out/single"),
            run_output_dir=Path("out/single/20260606_201703"),
            requested_events=10,
            captured_events=10,
            send_mode=1,
            decode_enabled=False,
            decoded_output_dir=None,
            decoded_events=0,
            decode_errors=0,
            watch_enabled=False,
            watch_every=None,
            watched_frames=0,
            tcp_timeout_s=10.0,
            log_output="parallel log output",
        )

        with patch("daq_cli.cli.acquire.ProfileService") as profile_service_cls:
            profile_service_cls.return_value.load_profile.return_value = profile
            with patch("daq_cli.cli.acquire.AcquireService") as service_cls:
                service = service_cls.return_value
                service.capture_single.return_value = result_payload
                result = runner.invoke(
                    app,
                    [
                        "acquire",
                        "single",
                        "dev1",
                        "--profile",
                        "profiles/example.yaml",
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        outputs = service.capture_single.call_args.kwargs["outputs"]
        self.assertFalse(outputs.json.enabled)
        self.assertTrue(outputs.text.enabled)
        self.assertEqual(outputs.text.dir, Path("txt_out"))
        self.assertEqual(outputs.text.max_events_per_file, 7)
        self.assertEqual(outputs.text.waveform_layout, "channel_blocks")
        self.assertTrue(outputs.raw.enabled)
        self.assertEqual(outputs.raw.dir, Path("raw_out"))

    def test_cli_multi_raw_only_does_not_disable_text_output(self) -> None:
        runner = CliRunner()
        profile = SimpleNamespace(
            defaults={
                "acquire_multi": {
                    "outputs": {
                        "json": {"enabled": True},
                        "text": {"enabled": True, "dir": "text_out"},
                        "log": {"enabled": True, "dir": "log_out"},
                    }
                }
            }
        )
        result_payload = SimpleNamespace(
            group=SimpleNamespace(name="two_board"),
            devices=[SimpleNamespace(name="dev1"), SimpleNamespace(name="dev2")],
            source_profile=Path("profiles/example.yaml"),
            output_base_dir=Path("out/multi"),
            run_output_dir=Path("out/multi/two_board_20260607_220846"),
            aggregation_key="timestamp",
            timestamp_match_window_ticks=10,
            tcp_timeout_s=1.0,
            allow_start_without_ack=True,
            decode_enabled=False,
            decoded_output_dir=None,
            decoded_complete_events=0,
            decoded_partial_events=0,
            decode_errors=0,
            watch_waveforms=False,
            watch_every=None,
            watched_frames=0,
            stop_capture_on_watch_close=True,
            config_path=Path("out/multi/.daq_cli_tmp/multi_board_acquire.config.json"),
            meta_path=Path("out/multi/two_board_20260607_220846/run_meta.json"),
            log_path=Path("out/multi/two_board_20260607_220846/log.txt"),
            status="ok",
        )

        with patch("daq_cli.cli.acquire.ProfileService") as profile_service_cls:
            profile_service_cls.return_value.load_profile.return_value = profile
            with patch("daq_cli.cli.acquire.AcquireService") as service_cls:
                service = service_cls.return_value
                service.capture_multi.return_value = result_payload
                result = runner.invoke(
                    app,
                    [
                        "acquire",
                        "multi",
                        "two_board",
                        "--raw-only",
                        "--profile",
                        "profiles/example.yaml",
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        outputs = service.capture_multi.call_args.kwargs["outputs"]
        self.assertFalse(outputs.json.enabled)
        self.assertTrue(outputs.text.enabled)
        self.assertEqual(outputs.text.dir, Path("text_out"))
        self.assertTrue(outputs.log.enabled)
        self.assertEqual(outputs.log.dir, Path("log_out"))

    def test_acquire_service_multi_uses_runner_decode_results(self) -> None:
        profile = SimpleNamespace(
            path=Path("profiles/example.yaml"),
            devices={
                "dev1": SimpleNamespace(
                    name="dev1", ip="192.168.10.10", tcp_port=24, board_id=0
                ),
                "dev2": SimpleNamespace(
                    name="dev2", ip="192.168.10.11", tcp_port=24, board_id=1
                ),
            },
            groups={
                "two_board": SimpleNamespace(
                    name="two_board", devices=["dev1", "dev2"], tcm="main"
                )
            },
            tcm={
                "main": TcmConfig(
                    name="main", ip="192.168.10.16", rbcp_port=4660
                )
            },
            defaults={"output_dir": "out", "adc_length": 64},
            legacy=SimpleNamespace(project_root=Path("legacy")),
        )
        service = AcquireService()

        with patch.object(service._profile_service, "load_profile", return_value=profile):
            with patch(
                "daq_cli.application.acquire_service.LegacyMultiCaptureRunner"
            ) as runner_cls:
                runner_cls.return_value.capture_multi.return_value = SimpleNamespace(
                    config_path=Path("out/multi/.daq_cli_tmp/multi_board_acquire.config.json"),
                    run_output_dir=Path("out/multi/two_board_20260607_220846"),
                    status="ok",
                    log_path=Path("out/multi/two_board_20260607_220846/log.txt"),
                    meta_path=Path("out/multi/two_board_20260607_220846/run_meta.json"),
                    decode_enabled=True,
                    decoded_output_dir=Path("out/multi/two_board_20260607_220846/decoded"),
                    decoded_complete_events=12,
                    decoded_partial_events=1,
                    decode_errors=0,
                    watch_waveforms=False,
                    watch_every=None,
                    watched_frames=0,
                    stop_capture_on_watch_close=True,
                )
                result = service.capture_multi(
                    group_name="two_board",
                    profile_path="profiles/example.yaml",
                    decode_json=True,
                )

        self.assertTrue(result.decode_enabled)
        self.assertEqual(
            result.decoded_output_dir,
            Path("out/multi/two_board_20260607_220846/decoded"),
        )
        self.assertEqual(result.decoded_complete_events, 12)
        self.assertEqual(result.decoded_partial_events, 1)
        self.assertEqual(result.decode_errors, 0)

    def test_cli_single_shows_initial_pending_status_before_progress(self) -> None:
        runner = CliRunner()
        result_payload = SingleAcquireResult(
            device=SimpleNamespace(name="dev1"),
            source_profile=Path("profiles/example.yaml"),
            output_base_dir=Path("out/single"),
            run_output_dir=Path("out/single/20260606_201703"),
            requested_events=10,
            captured_events=0,
            send_mode=2,
            decode_enabled=False,
            decoded_output_dir=None,
            decoded_events=0,
            decode_errors=0,
            watch_enabled=False,
            watch_every=None,
            watched_frames=0,
            tcp_timeout_s=10.0,
            log_output="parallel log output",
        )

        with patch("daq_cli.cli.acquire.AcquireService") as service_cls:
            service = service_cls.return_value
            service.capture_single.return_value = result_payload
            result = runner.invoke(
                app,
                [
                    "acquire",
                    "single",
                    "dev1",
                    "--events",
                    "10",
                    "--profile",
                    "profiles/example.yaml",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("events=0/10", result.output)
        self.assertIn("rate=0.00Hz", result.output)
        self.assertIn("hit_mask=pending", result.output)
        self.assertIn("bytes=pending", result.output)

    def _make_workspace_temp_dir(self) -> Path:
        path = Path("tmp_test_outputs") / uuid.uuid4().hex
        path.mkdir(parents=True, exist_ok=False)
        return path


class FakeSocket:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)
        self.closed = False

    def recv(self, _size: int) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        return b""

    def settimeout(self, _timeout: float) -> None:
        return None

    def connect(self, _addr) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeDecodeProcess:
    def __init__(self, thread: threading.Thread) -> None:
        self._thread = thread
        self.exitcode = 0

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread.is_alive()


class FakeWatchProcess:
    def __init__(self, thread: threading.Thread) -> None:
        self._thread = thread
        self.exitcode = 0

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread.is_alive()


def _build_tcp_sent_packet(send_mode: int, hit_mask: int, event_count: int) -> bytes:
    hit_count = max(1, _bit_count(hit_mask))
    header = bytearray(HEADER_BYTES)
    header[:3] = MODE2_MAGIC[:3]
    header[3] = send_mode
    header[4:8] = event_count.to_bytes(4, byteorder="big", signed=False)
    header[16:18] = hit_mask.to_bytes(2, byteorder="big", signed=False)
    header[18] = FEATURE_BYTES if send_mode in (2, 3) else 0
    payload = bytearray()
    if send_mode in (2, 3):
        for channel_index in range(hit_count):
            payload.extend(bytes([channel_index]) + b"\x00" * 9)
    if send_mode in (0, 3):
        waveform_channels = hit_count
    elif send_mode == 1:
        waveform_channels = 16
    else:
        waveform_channels = 0
    for sample_index in range(ADC_LENGTH):
        for channel_index in range(waveform_channels):
            value_a = (sample_index + channel_index) & 0x0FFF
            value_b = (sample_index + channel_index + 1) & 0x0FFF
            word = (value_a << 16) | value_b
            payload.extend(word.to_bytes(4, byteorder="big", signed=False))
    return bytes(header + payload)


def _bit_count(value: int) -> int:
    count = 0
    while value:
        count += value & 1
        value >>= 1
    return count


def _make_fake_decode_backend(maxsize: int = 128, slow: bool = False) -> DecodeBackendRuntime:
    task_queue: queue.Queue = queue.Queue(maxsize=maxsize)
    result_queue: queue.Queue = queue.Queue()

    if slow:
        def run_slow_worker() -> None:
            writers: dict[str, object] = {}
            while True:
                item = task_queue.get()
                if item is None:
                    for writer in writers.values():
                        writer.close()
                    return
                try:
                    from daq_cli.infrastructure.adapters.legacy_capture_runner import (
                        decode_tcp_sent_file,
                        write_decoded_event_json,
                        DecodeWorkerResult,
                    )

                    event = decode_tcp_sent_file(
                        item.raw_event_path,
                        expected_send_mode=item.expected_send_mode,
                        adc_length=item.adc_length,
                    )
                    if item.json_output_path is not None:
                        write_decoded_event_json(event, item.json_output_path)
                    from daq_cli.infrastructure.text_event_writer import (
                        SegmentedTextEventWriter,
                        format_single_event_text,
                    )

                    text_written = 0
                    if item.text_output_dir is not None:
                        writer_key = str(item.text_output_dir)
                        writer = writers.get(writer_key)
                        if writer is None:
                            writer = SegmentedTextEventWriter(
                                item.text_output_dir,
                                item.text_max_events_per_file,
                            )
                            writers[writer_key] = writer
                        writer.append_event(
                            format_single_event_text(
                                event,
                                device_name=item.device_name,
                                board_ip=item.board_ip,
                            )
                        )
                        text_written = 1
                    result_queue.put(
                        DecodeWorkerResult(
                            success=True,
                            json_written=1 if item.json_output_path is not None else 0,
                            text_written=text_written,
                        )
                    )
                except Exception as exc:
                    from daq_cli.infrastructure.adapters.legacy_capture_runner import (
                        DecodeWorkerResult,
                    )
                    result_queue.put(
                        DecodeWorkerResult(success=False, error_message=str(exc))
                    )
                threading.Event().wait(0.01)

        thread = threading.Thread(target=run_slow_worker, daemon=True)
    else:
        thread = threading.Thread(
            target=_decode_worker_main,
            args=(task_queue, result_queue),
            daemon=True,
        )
    thread.start()
    return DecodeBackendRuntime(
        task_queue=task_queue,
        result_queue=result_queue,
        process=FakeDecodeProcess(thread),
    )


def _make_fake_watch_backend() -> WatchBackendRuntime:
    task_queue: queue.Queue = queue.Queue(maxsize=1)
    result_queue: queue.Queue = queue.Queue()

    def run_worker() -> None:
        while True:
            item = task_queue.get()
            if item is None:
                return
            result_queue.put(SimpleNamespace(success=True))

    worker_thread = threading.Thread(target=run_worker, daemon=True)
    worker_thread.start()
    return WatchBackendRuntime(
        task_queue=task_queue,
        result_queue=result_queue,
        process=FakeWatchProcess(worker_thread),
    )


if __name__ == "__main__":
    unittest.main()
