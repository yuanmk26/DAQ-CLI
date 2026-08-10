from pathlib import Path
import json
import queue
import shutil
import unittest
import uuid

from typer.testing import CliRunner

from daq_cli.application.decode_service import DecodeService
from daq_cli.application.multi_decode_service import MultiDecodeService
from daq_cli.cli.app import app
from daq_cli.infrastructure.multi_board_decode import (
    BOARD_FLAG_HAS_FEATURE,
    BOARD_FLAG_HAS_FINE,
    BOARD_FLAG_HAS_WAVEFORM,
    BOARD_FLAG_TCP_RECONNECTED_BEFORE_FRAME,
    EVENT_FLAG_COMPLETE,
    EVENT_FLAG_EVENT_COUNT_MISMATCH,
    EVENT_FLAG_PARTIAL,
    EVENT_FLAG_TIMEOUT_FLUSH,
    FILE_HEADER_SIZE,
    MultiBoardAggregatedEventReader,
    MultiBoardTailReadState,
    read_available_tail_events,
)
from daq_cli.infrastructure.tcp_sent_decode import (
    ADC_LENGTH,
    DecodedTcpSentEvent,
    TcpSentDecodeError,
    decode_tcp_sent_file,
    decode_tcp_sent_packet,
)
from daq_cli.infrastructure.adapters.legacy_multi_capture_runner import (
    _DecodeControlMessage,
    _multi_board_decode_backend_main,
)


class DecodeTests(unittest.TestCase):
    def test_decode_mode1_file_parses_full_waveforms(self) -> None:
        event_path = self._write_event_file(
            _build_tcp_sent_packet(send_mode=1, hit_mask=0xF0FF, event_count=15),
        )
        try:
            event = decode_tcp_sent_file(event_path, expected_send_mode=1)
            self.assertEqual(event.send_mode, 1)
            self.assertEqual(event.event_count, 15)
            self.assertEqual(event.hit_mask, 0xF0FF)
            self.assertEqual(len(event.channels), 16)
            self.assertTrue(all(channel is not None for channel in event.channels))
            self.assertTrue(all(len(channel) == ADC_LENGTH * 2 for channel in event.channels if channel is not None))
            self.assertEqual(event.raw_packet_bytes, 4116)
        finally:
            shutil.rmtree(event_path.parent.parent.parent, ignore_errors=True)

    def test_decode_mode2_file_produces_null_channels_and_features(self) -> None:
        event_path = self._write_event_file(
            _build_tcp_sent_packet(send_mode=2, hit_mask=0x0003, event_count=4),
        )
        try:
            event = decode_tcp_sent_file(event_path, expected_send_mode=2)
            self.assertEqual(event.send_mode, 2)
            self.assertTrue(all(channel is None for channel in event.channels))
            self.assertEqual(len(event.feature_records), 2)
            self.assertEqual(event.feature_records[0].channel, 0)
            self.assertEqual(event.feature_records[1].channel, 1)
        finally:
            shutil.rmtree(event_path.parent.parent.parent, ignore_errors=True)

    def test_decode_mode3_file_includes_features_and_hit_waveforms(self) -> None:
        event_path = self._write_event_file(
            _build_tcp_sent_packet(send_mode=3, hit_mask=0x8003, event_count=7),
        )
        try:
            event = decode_tcp_sent_file(event_path, expected_send_mode=3)
            self.assertEqual(event.send_mode, 3)
            self.assertEqual(len(event.feature_records), 3)
            self.assertIsNotNone(event.channels[0])
            self.assertIsNotNone(event.channels[1])
            self.assertIsNotNone(event.channels[15])
            self.assertIsNone(event.channels[2])
        finally:
            shutil.rmtree(event_path.parent.parent.parent, ignore_errors=True)

    def test_decode_rejects_invalid_length(self) -> None:
        event_path = self._write_event_file(
            _build_tcp_sent_packet(send_mode=1, hit_mask=0x0001, event_count=1)[:-1],
        )
        try:
            with self.assertRaises(TcpSentDecodeError):
                decode_tcp_sent_file(event_path, expected_send_mode=1)
        finally:
            shutil.rmtree(event_path.parent.parent.parent, ignore_errors=True)

    def test_decode_rejects_invalid_header(self) -> None:
        event_path = self._write_event_file(b"\x00\x01\x02\x03" + b"\x00" * 20)
        try:
            with self.assertRaises(TcpSentDecodeError):
                decode_tcp_sent_file(event_path)
        finally:
            shutil.rmtree(event_path.parent.parent.parent, ignore_errors=True)

    def test_decode_run_creates_json_outputs(self) -> None:
        run_dir = self._make_run_dir(send_mode=1)
        try:
            for index in range(3):
                packet = _build_tcp_sent_packet(
                    send_mode=1,
                    hit_mask=0x00FF,
                    event_count=index + 1,
                )
                (run_dir / "raw" / f"event_{index:05d}.bin").write_bytes(packet)
            (run_dir / "capture_info.txt").write_text(
                "\n".join(
                    [
                        "send_mode=1",
                        "adc_length=64",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            result = DecodeService().decode_run(run_dir=run_dir, limit=2)
            self.assertEqual(result.success_count, 2)
            self.assertEqual(result.send_mode, 1)
            self.assertTrue((run_dir / "decoded" / "event_00000.json").is_file())
            self.assertTrue((run_dir / "decoded" / "event_00001.json").is_file())
            self.assertFalse((run_dir / "decoded" / "event_00002.json").exists())
        finally:
            shutil.rmtree(run_dir.parent, ignore_errors=True)

    def test_decode_event_creates_single_json_output(self) -> None:
        event_path = self._write_event_file(
            _build_tcp_sent_packet(send_mode=1, hit_mask=0x0F0F, event_count=22),
        )
        try:
            result = DecodeService().decode_event(event_file=event_path)
            self.assertEqual(result.send_mode, 1)
            payload = json.loads(result.output_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["event_count"], 22)
            self.assertEqual(payload["send_mode"], 1)
        finally:
            shutil.rmtree(event_path.parent.parent.parent, ignore_errors=True)

    def test_decode_event_refuses_to_overwrite_by_default(self) -> None:
        event_path = self._write_event_file(
            _build_tcp_sent_packet(send_mode=1, hit_mask=0x0F0F, event_count=22),
        )
        try:
            service = DecodeService()
            service.decode_event(event_file=event_path)
            with self.assertRaises(ValueError):
                service.decode_event(event_file=event_path)
            service.decode_event(event_file=event_path, overwrite=True)
        finally:
            shutil.rmtree(event_path.parent.parent.parent, ignore_errors=True)

    def test_cli_decode_run_outputs_summary(self) -> None:
        run_dir = self._make_run_dir(send_mode=1)
        try:
            (run_dir / "raw" / "event_00000.bin").write_bytes(
                _build_tcp_sent_packet(send_mode=1, hit_mask=0xFFFF, event_count=1)
            )
            runner = CliRunner()
            result = runner.invoke(app, ["decode", "run", str(run_dir)])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Decoded run:", result.output)
            self.assertIn("success_count=1", result.output)
            self.assertIn("send_mode=1", result.output)
        finally:
            shutil.rmtree(run_dir.parent, ignore_errors=True)

    def test_cli_decode_event_outputs_summary(self) -> None:
        event_path = self._write_event_file(
            _build_tcp_sent_packet(send_mode=1, hit_mask=0xFFFF, event_count=5),
        )
        try:
            runner = CliRunner()
            result = runner.invoke(app, ["decode", "event", str(event_path)])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Decoded event:", result.output)
            self.assertIn("send_mode=1", result.output)
            self.assertIn("raw_packet_bytes=4116", result.output)
        finally:
            shutil.rmtree(event_path.parent.parent.parent, ignore_errors=True)

    def test_multi_reader_round_trips_complete_and_partial_records(self) -> None:
        run_dir = self._make_multi_run_dir()
        try:
            complete_event = _build_multi_event(
                aggregate_seq=1,
                timestamp=1000,
                status_flags=EVENT_FLAG_COMPLETE,
                board_packets=[
                    _build_multi_board_packet(
                        board_id=0,
                        packet=_build_tcp_sent_packet(
                            send_mode=1, hit_mask=0x0003, event_count=11
                        ),
                        recv_unix_ns=111,
                    ),
                    _build_multi_board_packet(
                        board_id=1,
                        packet=_build_tcp_sent_packet(
                            send_mode=3, hit_mask=0x0003, event_count=11
                        ),
                        recv_unix_ns=222,
                    ),
                ],
            )
            partial_event = _build_multi_event(
                aggregate_seq=2,
                timestamp=2000,
                status_flags=EVENT_FLAG_PARTIAL | EVENT_FLAG_TIMEOUT_FLUSH,
                boards_missing_mask=0x00000002,
                board_packets=[
                    _build_multi_board_packet(
                        board_id=0,
                        packet=_build_tcp_sent_packet(
                            send_mode=0, hit_mask=0x0001, event_count=12
                        ),
                        recv_unix_ns=333,
                    ),
                ],
            )
            _write_multi_data_file(run_dir / "complete_events.dat", [complete_event])
            _write_multi_data_file(run_dir / "partial_events.dat", [partial_event])

            reader = MultiBoardAggregatedEventReader(
                run_dir / "complete_events.dat",
                event_kind="complete",
            )
            events = list(reader.iter_events())
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].aggregate_seq, 1)
            self.assertEqual(len(events[0].boards), 2)
            self.assertEqual(events[0].boards[1].mode, 3)
            self.assertGreater(events[0].boards[1].feature_len, 0)
            self.assertGreater(events[0].boards[1].waveform_len, 0)
        finally:
            shutil.rmtree(run_dir.parent, ignore_errors=True)

    def test_multi_tail_reader_waits_for_incomplete_record_then_resumes(self) -> None:
        run_dir = self._make_multi_run_dir()
        try:
            complete_event = _build_multi_event(
                aggregate_seq=1,
                timestamp=1234,
                status_flags=EVENT_FLAG_COMPLETE,
                board_packets=[
                    _build_multi_board_packet(
                        board_id=0,
                        packet=_build_tcp_sent_packet(
                            send_mode=1, hit_mask=0x0001, event_count=41
                        ),
                        recv_unix_ns=100,
                    )
                ],
            )
            full_payload = _build_multi_data_file_bytes([complete_event])
            (run_dir / "complete_events.dat").write_bytes(full_payload[:-8])

            first_read = read_available_tail_events(
                path=run_dir / "complete_events.dat",
                event_kind="complete",
                state=MultiBoardTailReadState(),
            )
            self.assertEqual(first_read.events, [])
            self.assertTrue(first_read.state.header_read)
            self.assertEqual(first_read.state.offset, FILE_HEADER_SIZE)

            (run_dir / "complete_events.dat").write_bytes(full_payload)
            second_read = read_available_tail_events(
                path=run_dir / "complete_events.dat",
                event_kind="complete",
                state=first_read.state,
            )
            self.assertEqual(len(second_read.events), 1)
            self.assertEqual(second_read.events[0].aggregate_seq, 1)
            self.assertGreater(second_read.state.offset, first_read.state.offset)
        finally:
            shutil.rmtree(run_dir.parent, ignore_errors=True)

    def test_multi_decode_run_creates_complete_and_partial_json(self) -> None:
        run_dir = self._make_multi_run_dir()
        try:
            complete_event = _build_multi_event(
                aggregate_seq=1,
                timestamp=5000,
                status_flags=EVENT_FLAG_COMPLETE | EVENT_FLAG_EVENT_COUNT_MISMATCH,
                board_packets=[
                    _build_multi_board_packet(
                        board_id=0,
                        packet=_build_tcp_sent_packet(
                            send_mode=1, hit_mask=0x0003, event_count=21
                        ),
                        recv_unix_ns=444,
                    ),
                    _build_multi_board_packet(
                        board_id=1,
                        packet=_build_tcp_sent_packet(
                            send_mode=2, hit_mask=0x0003, event_count=22
                        ),
                        recv_unix_ns=555,
                        board_flags=BOARD_FLAG_HAS_FEATURE
                        | BOARD_FLAG_TCP_RECONNECTED_BEFORE_FRAME,
                    ),
                ],
            )
            partial_event = _build_multi_event(
                aggregate_seq=2,
                timestamp=6000,
                status_flags=EVENT_FLAG_PARTIAL | EVENT_FLAG_TIMEOUT_FLUSH,
                boards_missing_mask=0x00000002,
                board_packets=[
                    _build_multi_board_packet(
                        board_id=0,
                        packet=_build_tcp_sent_packet(
                            send_mode=3, hit_mask=0x0001, event_count=23
                        ),
                        recv_unix_ns=666,
                    ),
                ],
            )
            _write_multi_data_file(run_dir / "complete_events.dat", [complete_event])
            _write_multi_data_file(run_dir / "partial_events.dat", [partial_event])

            result = MultiDecodeService().decode_multi_run(run_dir=run_dir)

            self.assertEqual(result.decoded_complete_events, 1)
            self.assertEqual(result.decoded_partial_events, 1)
            self.assertEqual(result.decode_errors, 0)
            complete_json = json.loads(
                (run_dir / "decoded" / "complete" / "event_00001.json").read_text(
                    encoding="utf-8"
                )
            )
            partial_json = json.loads(
                (run_dir / "decoded" / "partial" / "event_00002.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(complete_json["event_kind"], "complete")
            self.assertEqual(complete_json["aggregate_seq"], 1)
            self.assertEqual(complete_json["boards"][0]["send_mode"], 1)
            self.assertTrue(complete_json["boards"][1]["reconnect_mark"])
            self.assertEqual(partial_json["event_kind"], "partial")
            self.assertEqual(partial_json["missing_board_ids"], [1])
            self.assertEqual(len(partial_json["boards"]), 1)
        finally:
            shutil.rmtree(run_dir.parent, ignore_errors=True)

    def test_multi_decode_backend_appends_multiple_events_to_text_files(self) -> None:
        run_dir = self._make_multi_run_dir()
        try:
            complete_events = [
                _build_multi_event(
                    aggregate_seq=1,
                    timestamp=5000,
                    status_flags=EVENT_FLAG_COMPLETE,
                    board_packets=[
                        _build_multi_board_packet(
                            board_id=0,
                            packet=_build_tcp_sent_packet(
                                send_mode=1, hit_mask=0x0003, event_count=21
                            ),
                            recv_unix_ns=444,
                        )
                    ],
                ),
                _build_multi_event(
                    aggregate_seq=2,
                    timestamp=5001,
                    status_flags=EVENT_FLAG_COMPLETE,
                    board_packets=[
                        _build_multi_board_packet(
                            board_id=1,
                            packet=_build_tcp_sent_packet(
                                send_mode=1, hit_mask=0x0003, event_count=22
                            ),
                            recv_unix_ns=445,
                        )
                    ],
                ),
            ]
            partial_events = [
                _build_multi_event(
                    aggregate_seq=3,
                    timestamp=6000,
                    status_flags=EVENT_FLAG_PARTIAL | EVENT_FLAG_TIMEOUT_FLUSH,
                    boards_missing_mask=0x00000002,
                    board_packets=[
                        _build_multi_board_packet(
                            board_id=0,
                            packet=_build_tcp_sent_packet(
                                send_mode=3, hit_mask=0x0001, event_count=23
                            ),
                            recv_unix_ns=666,
                        ),
                    ],
                )
            ]
            _write_multi_data_file(run_dir / "complete_events.dat", complete_events)
            _write_multi_data_file(run_dir / "partial_events.dat", partial_events)

            control_queue: queue.Queue = queue.Queue()
            result_queue: queue.Queue = queue.Queue()
            control_queue.put(_DecodeControlMessage(kind="capture_finished"))
            _multi_board_decode_backend_main(
                task_queue=control_queue,
                result_queue=result_queue,
                run_output_dir=str(run_dir),
                decoded_output_dir="",
                decode_json=False,
                text_output_dir=str(run_dir / "text"),
                text_output_enabled=True,
                text_max_events_per_file=10,
                text_waveform_layout="channel_blocks",
            )

            summary = result_queue.get_nowait()
            self.assertEqual(summary.text_output_complete_events, 2)
            self.assertEqual(summary.text_output_partial_events, 1)
            complete_text = (run_dir / "text" / "complete" / "events_00001.txt").read_text(
                encoding="utf-8"
            )
            partial_text = (run_dir / "text" / "partial" / "events_00001.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn("===== EVENT 1 =====", complete_text)
            self.assertIn("===== EVENT 2 =====", complete_text)
            self.assertIn("===== EVENT 3 =====", partial_text)
            self.assertIn("waveforms:", complete_text)
            self.assertIn("NA", partial_text)
            self.assertNotIn("waveform_samples:", complete_text)
            self.assertNotIn("ch00:", complete_text)
            waveform_lines = complete_text.splitlines()
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
            shutil.rmtree(run_dir.parent, ignore_errors=True)

    def test_cli_decode_multi_run_outputs_summary(self) -> None:
        run_dir = self._make_multi_run_dir()
        try:
            complete_event = _build_multi_event(
                aggregate_seq=1,
                timestamp=7000,
                status_flags=EVENT_FLAG_COMPLETE,
                board_packets=[
                    _build_multi_board_packet(
                        board_id=0,
                        packet=_build_tcp_sent_packet(
                            send_mode=1, hit_mask=0x0001, event_count=31
                        ),
                        recv_unix_ns=777,
                    )
                ],
            )
            _write_multi_data_file(run_dir / "complete_events.dat", [complete_event])
            _write_multi_data_file(run_dir / "partial_events.dat", [])
            runner = CliRunner()
            result = runner.invoke(app, ["decode", "multi-run", str(run_dir)])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Decoded multi run:", result.output)
            self.assertIn("decoded_complete_events=1", result.output)
            self.assertIn("decoded_partial_events=0", result.output)
        finally:
            shutil.rmtree(run_dir.parent, ignore_errors=True)

    def _write_event_file(self, packet: bytes) -> Path:
        run_dir = self._make_run_dir(send_mode=packet[3])
        event_path = run_dir / "raw" / "event_00000.bin"
        event_path.write_bytes(packet)
        return event_path

    def _make_run_dir(self, send_mode: int) -> Path:
        root = Path("tmp_test_decode") / uuid.uuid4().hex / "run"
        (root / "raw").mkdir(parents=True, exist_ok=False)
        (root / "capture_info.txt").write_text(
            f"send_mode={send_mode}\nadc_length=64\n",
            encoding="utf-8",
        )
        return root

    def _make_multi_run_dir(self) -> Path:
        root = Path("tmp_test_decode") / uuid.uuid4().hex / "multi_run"
        root.mkdir(parents=True, exist_ok=False)
        (root / "run_meta.json").write_text(
            json.dumps(
                {
                    "format_name": "FDU_ADC_AGGR",
                    "format_version": 1,
                    "aggregation_key": "timestamp",
                    "boards_expected": [
                        {
                            "board_id": 0,
                            "name": "dev1",
                            "ip": "192.168.10.10",
                            "tcp_port": 24,
                        },
                        {
                            "board_id": 1,
                            "name": "dev2",
                            "ip": "192.168.10.11",
                            "tcp_port": 24,
                        },
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return root


def _build_tcp_sent_packet(
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


def _build_multi_board_packet(
    *,
    board_id: int,
    packet: bytes,
    recv_unix_ns: int,
    board_flags: int | None = None,
) -> dict[str, object]:
    mode = packet[3]
    hit_mask = int.from_bytes(packet[16:18], "big", signed=False)
    feature_size = packet[18]
    hit_count = sum(1 for channel in range(16) if (hit_mask >> channel) & 0x1)
    feature_len = hit_count * feature_size
    waveform_len = len(packet) - 20 - feature_len
    flags = 0 if board_flags is None else board_flags
    if feature_len:
        flags |= BOARD_FLAG_HAS_FEATURE
    if waveform_len:
        flags |= BOARD_FLAG_HAS_WAVEFORM
    return {
        "board_id": board_id,
        "board_flags": flags,
        "event_count": int.from_bytes(packet[4:8], "big", signed=False),
        "timestamp": int.from_bytes(packet[8:16], "big", signed=False),
        "mode": mode,
        "hit_mask": hit_mask,
        "hit_count": hit_count,
        "feature_size": feature_size,
        "feature_len": feature_len,
        "waveform_len": waveform_len,
        "recv_unix_ns": recv_unix_ns,
        "feature_bytes": packet[20 : 20 + feature_len],
        "waveform_bytes": packet[20 + feature_len :],
    }


def _build_multi_event(
    *,
    aggregate_seq: int,
    timestamp: int,
    status_flags: int,
    board_packets: list[dict[str, object]],
    boards_missing_mask: int = 0,
) -> dict[str, object]:
    event_count_values = [int(item["event_count"]) for item in board_packets] or [0]
    boards_present_mask = 0
    for item in board_packets:
        boards_present_mask |= 1 << int(item["board_id"])
    return {
        "aggregate_seq": aggregate_seq,
        "timestamp": timestamp,
        "first_recv_unix_ns": min(int(item["recv_unix_ns"]) for item in board_packets)
        if board_packets
        else 0,
        "flush_unix_ns": max(int(item["recv_unix_ns"]) for item in board_packets)
        if board_packets
        else 0,
        "boards_present_mask": boards_present_mask,
        "boards_missing_mask": boards_missing_mask,
        "status_flags": status_flags,
        "event_count_min": min(event_count_values),
        "event_count_max": max(event_count_values),
        "boards": board_packets,
    }


def _write_multi_data_file(path: Path, events: list[dict[str, object]]) -> None:
    path.write_bytes(_build_multi_data_file_bytes(events))


def _build_multi_data_file_bytes(events: list[dict[str, object]]) -> bytes:
    import struct

    file_header_fmt = "<8sHHIQIII"
    event_header_fmt = "<IHHQQQQIIIIQQ"
    board_header_fmt = "<IHHIIQHHHHIIQ"
    payload = bytearray()
    payload.extend(
        struct.pack(
            file_header_fmt,
            b"FDUAGGR1",
            struct.calcsize(file_header_fmt),
            1,
            0,
            123456789,
            0,
            2,
            64,
        )
    )
    for event in events:
        board_chunks = []
        for board in event["boards"]:
            board_header_bytes = struct.calcsize(board_header_fmt)
            board_record_bytes = board_header_bytes + len(board["feature_bytes"]) + len(
                board["waveform_bytes"]
            )
            board_chunk = struct.pack(
                board_header_fmt,
                board_record_bytes,
                board_header_bytes,
                board["board_id"],
                board["board_flags"],
                board["event_count"],
                board["timestamp"],
                board["mode"],
                board["hit_mask"],
                board["hit_count"],
                16,
                board["feature_len"],
                board["waveform_len"],
                board["recv_unix_ns"],
            )
            board_chunk += board["feature_bytes"] + board["waveform_bytes"]
            board_chunks.append(board_chunk)

        event_header_bytes = struct.calcsize(event_header_fmt)
        record_bytes = event_header_bytes + sum(len(chunk) for chunk in board_chunks)
        payload.extend(
            struct.pack(
                event_header_fmt,
                record_bytes,
                event_header_bytes,
                len(board_chunks),
                event["aggregate_seq"],
                event["timestamp"],
                event["first_recv_unix_ns"],
                event["flush_unix_ns"],
                event["boards_present_mask"],
                event["boards_missing_mask"],
                event["status_flags"],
                0,
                event["event_count_min"],
                event["event_count_max"],
            )
        )
        payload.extend(b"".join(board_chunks))
    return bytes(payload)


class FineFrameDecodeTests(unittest.TestCase):
    """28-byte header (format_version=1) decoding and fine-field semantics."""

    def test_v1_mode1_parses_fine_fields(self) -> None:
        packet = _build_tcp_sent_packet(
            1, 0xFFFF, 7, format_version=1, crossing_fine=0x12345678,
            accept_fine=0x12345678 + 157,
        )
        event = decode_tcp_sent_packet(packet, source_file=Path("v1_mode1.bin"))
        self.assertEqual(event.format_version, 1)
        self.assertEqual(event.crossing_fine, 0x12345678)
        self.assertEqual(event.accept_fine, 0x12345678 + 157)
        self.assertEqual(event.delta_fine, 157)
        self.assertEqual(event.raw_packet_bytes, len(packet))

    def test_v1_all_modes_parse_fine_fields(self) -> None:
        for send_mode, hit_mask in ((0, 0x0003), (1, 0xFFFF), (2, 0x0003), (3, 0x0003)):
            with self.subTest(send_mode=send_mode):
                packet = _build_tcp_sent_packet(
                    send_mode, hit_mask, 11, format_version=1,
                    crossing_fine=0xA0, accept_fine=0xB4,
                )
                event = decode_tcp_sent_packet(
                    packet, source_file=Path(f"v1_mode{send_mode}.bin")
                )
                self.assertEqual(event.format_version, 1)
                self.assertEqual(event.delta_fine, 0xB4 - 0xA0)
                self.assertEqual(event.send_mode, send_mode)

    def test_legacy_v0_frame_has_no_fine_fields(self) -> None:
        packet = _build_tcp_sent_packet(1, 0xFFFF, 3)
        event = decode_tcp_sent_packet(packet, source_file=Path("v0_mode1.bin"))
        self.assertEqual(event.format_version, 0)
        self.assertIsNone(event.crossing_fine)
        self.assertIsNone(event.accept_fine)
        self.assertIsNone(event.delta_fine)

    def test_version_discrimination_same_payload(self) -> None:
        # Same event, byte 19 decides header length; the 20-byte variant keeps
        # the same event_count/timestamp/hit_mask.
        payload_with_fine = _build_tcp_sent_packet(
            1, 0x00FF, 5, format_version=1, crossing_fine=100, accept_fine=200,
        )
        payload_legacy = _build_tcp_sent_packet(1, 0x00FF, 5)
        self.assertEqual(len(payload_with_fine), len(payload_legacy) + 8)
        event_fine = decode_tcp_sent_packet(
            payload_with_fine, source_file=Path("v1.bin")
        )
        event_legacy = decode_tcp_sent_packet(
            payload_legacy, source_file=Path("v0.bin")
        )
        self.assertEqual(event_fine.event_count, event_legacy.event_count)
        self.assertEqual(event_fine.timestamp, event_legacy.timestamp)
        self.assertEqual(event_fine.hit_mask, event_legacy.hit_mask)
        self.assertIsNone(event_legacy.delta_fine)
        self.assertEqual(event_fine.delta_fine, 100)

    def test_delta_fine_wraps_around(self) -> None:
        # 32-bit counter rollover: crossing near the top, accept wrapped past 0.
        crossing = 0xFFFFFFF0
        accept = 0x00000020
        packet = _build_tcp_sent_packet(
            0, 0x0001, 1, format_version=1,
            crossing_fine=crossing, accept_fine=accept,
        )
        event = decode_tcp_sent_packet(packet, source_file=Path("wrap.bin"))
        self.assertEqual(event.delta_fine, (accept - crossing) & 0xFFFFFFFF)
        self.assertEqual(event.delta_fine, 0x30)

    def test_v1_json_includes_fine_fields(self) -> None:
        packet = _build_tcp_sent_packet(
            3, 0x0001, 2, format_version=1, crossing_fine=10, accept_fine=25,
        )
        event = decode_tcp_sent_packet(packet, source_file=Path("v1.bin"))
        raw = json.dumps(event.to_json_dict())
        payload = json.loads(raw)
        self.assertEqual(payload["format_version"], 1)
        self.assertEqual(payload["crossing_fine"], 10)
        self.assertEqual(payload["accept_fine"], 25)
        self.assertEqual(payload["delta_fine"], 15)

    def test_v1_packet_length_is_checked_with_fine_header(self) -> None:
        # A 20-byte packet whose byte 19 says version 1 must be rejected by the
        # 28-byte-based length formula, not silently accepted.
        legacy_packet = bytearray(_build_tcp_sent_packet(1, 0xFFFF, 1))
        self.assertEqual(legacy_packet[19], 0)
        legacy_packet[19] = 1
        with self.assertRaises(TcpSentDecodeError):
            decode_tcp_sent_packet(
                bytes(legacy_packet), source_file=Path("short_v1.bin")
            )


class FineAggregateRoundTripTests(unittest.TestCase):
    """Aggregated format v2 writer -> reader round trip, including mixed
    old/new firmware frames in one file."""

    def test_vendored_writer_v2_round_trips_fine_fields(self) -> None:
        import types

        from daq_cli.infrastructure.adapters.legacy_runtime import (
            bundled_legacy_script_dir,
            temporary_sys_path,
        )
        from daq_cli.infrastructure.multi_board_decode import (
            build_board_packet,
        )

        root = Path("tmp_test_decode") / uuid.uuid4().hex
        run_dir = root / "run"
        run_dir.mkdir(parents=True, exist_ok=False)

        with temporary_sys_path(bundled_legacy_script_dir()):
            import multi_board_acquire as mba

            # Two boards: one 28-byte (fine) frame, one legacy 20-byte frame.
            fine_packet = _build_tcp_sent_packet(
                1, 0xFFFF, 100, format_version=1,
                crossing_fine=0x11111110, accept_fine=0x11111150,
            )
            legacy_packet = _build_tcp_sent_packet(1, 0xFFFF, 100)

            frames = {
                0: mba.Frame(
                    board_id=0, board_name="dev1", board_ip="192.168.10.10",
                    mode=fine_packet[3], event_count=100,
                    timestamp=5000, hit_mask=0xFFFF, feature_size=0,
                    feature_bytes=b"", waveform_bytes=fine_packet[28:],
                    recv_unix_ns=1000, crossing_fine=0x11111110,
                    accept_fine=0x11111150, format_version=1,
                ),
                1: mba.Frame(
                    board_id=1, board_name="dev2", board_ip="192.168.10.11",
                    mode=legacy_packet[3], event_count=100,
                    timestamp=5000, hit_mask=0xFFFF, feature_size=0,
                    feature_bytes=b"", waveform_bytes=legacy_packet[20:],
                    recv_unix_ns=1001, format_version=0,
                ),
            }
            event = mba.AggregatedEvent(
                aggregate_seq=0, aggregation_value=5000, timestamp=5000,
                created_unix_ns=999, first_recv_unix_ns=1000,
                flush_unix_ns=1001, frames=frames,
                boards_present_mask=0b11, boards_missing_mask=0,
                status_flags=mba.EVENT_FLAG_COMPLETE,
                event_count_min=100, event_count_max=100,
            )
            writer = mba.DataWriter(
                types.SimpleNamespace(
                    boards=[], adc_length=64, run_name=None,
                    run_name_prefix="test",
                ),
                str(run_dir),
                mba.EventLogger(str(root / "run.log")),
            )
            writer.write_event(event)
            writer.close()

        reader = MultiBoardAggregatedEventReader(
            run_dir / "complete_events.dat", event_kind="complete"
        )
        events = list(reader.iter_events())
        self.assertEqual(len(events), 1)
        boards = {board.board_id: board for board in events[0].boards}
        self.assertEqual(set(boards), {0, 1})

        # Fine board: flag set, fields preserved, packet reconstructs as v1.
        fine_board = boards[0]
        self.assertTrue(fine_board.board_flags & BOARD_FLAG_HAS_FINE)
        self.assertEqual(fine_board.crossing_fine, 0x11111110)
        self.assertEqual(fine_board.accept_fine, 0x11111150)
        decoded_fine = decode_tcp_sent_packet(
            build_board_packet(fine_board), source_file=Path("b0.bin")
        )
        self.assertEqual(decoded_fine.format_version, 1)
        self.assertEqual(decoded_fine.delta_fine, 0x40)

        # Legacy board: no flag, fields zero, packet reconstructs as v0.
        legacy_board = boards[1]
        self.assertFalse(legacy_board.board_flags & BOARD_FLAG_HAS_FINE)
        decoded_legacy = decode_tcp_sent_packet(
            build_board_packet(legacy_board), source_file=Path("b1.bin")
        )
        self.assertEqual(decoded_legacy.format_version, 0)
        self.assertIsNone(decoded_legacy.delta_fine)


if __name__ == "__main__":
    unittest.main()
