import socket
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from daq_cli.infrastructure.tcm_link_calibration import (
    analyze_channel_samples,
    calibrate_from_stream,
)


def _build_mode1_packet(
    event_count: int, pulses: dict[int, int] | None = None
) -> bytes:
    """Mode-1 packet with a baseline of 2048; every 8th sample of a pulsed
    channel jumps to its pulse amplitude (so the baseline stays dominant)."""
    pulses = pulses or {}
    header = bytearray(28)
    header[:3] = b"\xFF\xFE\x01"
    header[3] = 1
    header[4:8] = event_count.to_bytes(4, "big")
    header[8:16] = (event_count * 100).to_bytes(8, "big")
    header[16:18] = b"\xFF\xFF"
    header[19] = 1
    payload = bytearray()
    for sample in range(64):
        for channel in range(16):
            if channel in pulses and sample % 8 == 0:
                value = pulses[channel]
            else:
                value = 2048 + (sample + channel) % 5 - 2  # small baseline noise
            word = (value << 16) | value
            payload.extend(word.to_bytes(4, "big"))
    return bytes(header + payload)


class AnalyzeChannelTests(unittest.TestCase):
    def test_positive_pulse_suggests_above_baseline(self) -> None:
        values = [2048 + (i % 5) - 2 for i in range(500)] + [2700] * 20
        baseline, sigma, direction, peak = analyze_channel_samples(values)
        self.assertLessEqual(abs(baseline - 2048), 2)
        self.assertGreater(sigma, 0)
        self.assertEqual(direction, 1)
        self.assertGreaterEqual(peak, 652)
        suggested = baseline + direction * int(max(5 * sigma, 0.5 * peak))
        self.assertGreater(suggested, baseline)

    def test_negative_pulse_suggests_below_baseline(self) -> None:
        values = [2048] * 400 + [1500] * 20  # negative pulse
        baseline, sigma, direction, peak = analyze_channel_samples(values)
        self.assertEqual(baseline, 2048)
        self.assertEqual(direction, -1)
        suggested = baseline + direction * int(max(5 * sigma, 0.5 * peak))
        self.assertLess(suggested, baseline)

    def test_flat_noise_has_no_direction(self) -> None:
        values = [2048] * 100
        baseline, sigma, direction, peak = analyze_channel_samples(values)
        self.assertEqual(baseline, 2048)
        self.assertEqual(peak, 0)

    def test_empty_values(self) -> None:
        self.assertEqual(analyze_channel_samples([]), (0, 0.0, 0, 0))


class FakeCalibSocket:
    def __init__(self, packets: list[bytes]) -> None:
        self._packets = list(packets)
        self._buffer = b""
        self.timeout: float | None = None
        self.closed = False

    def connect(self, _address) -> None:
        pass

    def settimeout(self, timeout: float | None) -> None:
        self.timeout = timeout

    def recv(self, size: int) -> bytes:
        # Mimic real socket chunking: serve buffered bytes first, then pull
        # the next packet into the buffer.
        if not self._buffer:
            if not self._packets:
                raise socket.timeout("fake socket exhausted")
            self._buffer = self._packets.pop(0)
        chunk = self._buffer[:size]
        self._buffer = self._buffer[size:]
        return chunk

    def close(self) -> None:
        self.closed = True


class CalibrateFromStreamTests(unittest.TestCase):
    def test_calibrates_from_frames(self) -> None:
        device = SimpleNamespace(name="dev1", ip="192.168.10.10", tcp_port=24)
        pulses = {0: 2700, 1: 1500}  # ch0 pos pulse, ch1 neg pulse
        packets = [_build_mode1_packet(1, pulses), _build_mode1_packet(2, pulses)]
        fake_socket = FakeCalibSocket(packets)
        with patch(
            "daq_cli.infrastructure.tcm_link_calibration.socket.socket",
            return_value=fake_socket,
        ):
            calibration = calibrate_from_stream(
                device, seconds=0.2, tcp_timeout_s=0.1
            )

        self.assertEqual(calibration.frames, 2)
        self.assertEqual(len(calibration.channels), 16)
        ch0 = calibration.channels[0]
        self.assertGreaterEqual(ch0.samples, 128)
        self.assertEqual(ch0.baseline, 2048)
        self.assertEqual(ch0.suggested_polarity, 0)  # positive pulse
        self.assertGreater(ch0.suggested_threshold, 2048)
        ch1 = calibration.channels[1]
        self.assertEqual(ch1.suggested_polarity, 1)  # negative pulse
        self.assertLess(ch1.suggested_threshold, 2048)
        self.assertTrue(fake_socket.closed)

    def test_raises_when_no_frames_received(self) -> None:
        device = SimpleNamespace(name="dev1", ip="192.168.10.10", tcp_port=24)
        with patch(
            "daq_cli.infrastructure.tcm_link_calibration.socket.socket",
            return_value=FakeCalibSocket(packets=[]),
        ):
            with self.assertRaisesRegex(RuntimeError, "未收到事件"):
                calibrate_from_stream(device, seconds=0.05, tcp_timeout_s=0.01)


class MeasureTcmLinkServiceTests(unittest.TestCase):
    def _service_and_patches(self):
        from daq_cli.application.board_service import BoardService

        profile = SimpleNamespace(
            path=Path("profiles/example.yaml"),
            legacy=SimpleNamespace(project_root=Path("legacy")),
        )
        device = SimpleNamespace(name="dev1")
        service = BoardService()
        adapter = SimpleNamespace(
            read_tcp_mode2_config=lambda d: SimpleNamespace(send_mode=1),
            write_send_mode=lambda d, m: None,
        )
        calibration = SimpleNamespace(
            device_name="dev1", duration_s=1.0, frames=10,
            channels=[], suggested_polarity_mask=lambda: 0,
        )
        return service, profile, device, adapter, calibration

    def test_measure_skips_switch_when_already_mode1(self) -> None:
        service, profile, device, adapter, calibration = self._service_and_patches()
        with patch.object(service, "_resolve_device", return_value=(profile, device)):
            with patch.object(service, "_make_adapter", return_value=adapter):
                with patch(
                    "daq_cli.application.board_service.calibrate_from_stream",
                    return_value=calibration,
                ) as calibrate:
                    result = service.measure_tcm_link(
                        device_name="dev1",
                        profile_path="profiles/example.yaml",
                        seconds=1.0,
                    )
        calibrate.assert_called_once()
        self.assertEqual(result.original_send_mode, 1)

    def test_measure_switches_and_restores_send_mode(self) -> None:
        service, profile, device, adapter, calibration = self._service_and_patches()
        adapter.read_tcp_mode2_config = lambda d: SimpleNamespace(send_mode=0)
        writes: list[int] = []
        adapter.write_send_mode = lambda d, m: writes.append(m)
        with patch.object(service, "_resolve_device", return_value=(profile, device)):
            with patch.object(service, "_make_adapter", return_value=adapter):
                with patch(
                    "daq_cli.application.board_service.calibrate_from_stream",
                    return_value=calibration,
                ):
                    result = service.measure_tcm_link(
                        device_name="dev1",
                        profile_path="profiles/example.yaml",
                        seconds=1.0,
                    )
        self.assertEqual(writes, [1, 0])  # switch to 1, restore to 0
        self.assertEqual(result.original_send_mode, 0)


if __name__ == "__main__":
    unittest.main()
