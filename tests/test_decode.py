from pathlib import Path
import json
import shutil
import unittest
import uuid

from typer.testing import CliRunner

from daq_cli.application.decode_service import DecodeService
from daq_cli.cli.app import app
from daq_cli.infrastructure.tcp_sent_decode import (
    ADC_LENGTH,
    DecodedTcpSentEvent,
    TcpSentDecodeError,
    decode_tcp_sent_file,
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


def _build_tcp_sent_packet(send_mode: int, hit_mask: int, event_count: int) -> bytes:
    hit_channels = [channel for channel in range(16) if (hit_mask >> channel) & 0x1]
    hit_count = len(hit_channels)
    header = bytearray(20)
    header[:3] = b"\xFF\xFE\x01"
    header[3] = send_mode
    header[4:8] = event_count.to_bytes(4, byteorder="big", signed=False)
    header[8:16] = (event_count * 12345).to_bytes(8, byteorder="big", signed=False)
    header[16:18] = hit_mask.to_bytes(2, byteorder="big", signed=False)
    header[18] = 10 if send_mode in (2, 3) else 0

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


if __name__ == "__main__":
    unittest.main()
