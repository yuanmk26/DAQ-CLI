"""TCM trigger-link calibration: capture a short full-waveform stream and
estimate per-channel baseline / noise / signal direction to suggest crossing
thresholds and polarities.

Algorithm mirrors FDU-ADC-250M-16ch/script/sipm_trigger_setup.py measure:
per channel, histogram-mode baseline, noise sigma from samples near the
baseline, peak deviation and direction, then
suggested threshold = baseline + direction * max(5*sigma, 0.5*peak_dev).
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from pathlib import Path

from daq_cli.domain.device import DeviceConfig
from daq_cli.infrastructure.adapters.legacy_capture_runner import (
    _TcpSentRawStreamReader,
)
from daq_cli.infrastructure.tcp_sent_decode import decode_tcp_sent_packet


@dataclass(slots=True)
class ChannelCalibration:
    channel: int
    samples: int
    baseline: int
    sigma: float
    direction: int  # +1 = positive pulses, -1 = negative pulses
    peak_dev: int
    suggested_threshold: int

    @property
    def suggested_polarity(self) -> int:
        """0 = pos (adc > thr), 1 = neg (adc < thr)."""
        return 1 if self.direction < 0 else 0


@dataclass(slots=True)
class TcmLinkCalibration:
    device_name: str
    duration_s: float
    frames: int
    channels: list[ChannelCalibration]

    def suggested_polarity_mask(self) -> int:
        mask = 0
        for channel in self.channels:
            if channel.suggested_polarity:
                mask |= 1 << channel.channel
        return mask


def analyze_channel_samples(values: list[int]) -> tuple[int, float, int, int]:
    """Baseline (histogram mode), noise sigma, direction, peak deviation."""
    if not values:
        return 0, 0.0, 0, 0
    hist: dict[int, int] = {}
    for value in values:
        hist[value] = hist.get(value, 0) + 1
    baseline = max(hist, key=hist.get)
    nearby = [value for value in values if abs(value - baseline) < 64]
    if len(nearby) > 8:
        mean = sum(nearby) / len(nearby)
        sigma = (sum((value - mean) ** 2 for value in nearby) / len(nearby)) ** 0.5
    else:
        sigma = 0.0
    peak_dev = max(abs(value - baseline) for value in values)
    direction = 1 if (sum(values) / len(values)) > baseline else -1
    return baseline, sigma, direction, peak_dev


def calibrate_from_stream(
    device: DeviceConfig,
    *,
    seconds: float,
    tcp_timeout_s: float = 1.0,
) -> TcmLinkCalibration:
    """Read ``seconds`` of send_mode=1 frames from the board and analyze.

    The caller is responsible for having the board in send_mode=1 (and for
    restoring it afterwards).
    """
    per_channel: list[list[int]] = [[] for _ in range(16)]
    frames = 0
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(tcp_timeout_s)
    try:
        sock.connect((device.ip, device.tcp_port))
        reader = _TcpSentRawStreamReader(sock=sock, expected_send_mode=1)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                packet = reader.read_packet()
            except socket.timeout:
                continue
            frames += 1
            decoded = decode_tcp_sent_packet(
                packet, source_file=Path("tcm_link_calibration.bin")
            )
            for channel_index in range(16):
                channel_data = decoded.channels[channel_index]
                if channel_data:
                    per_channel[channel_index].extend(channel_data)
    finally:
        sock.close()

    if frames == 0:
        raise RuntimeError(
            f"未收到事件（{seconds}s 内）。请确认：板卡已配置、TCP 端口可连、"
            f"send_mode=1 已生效、有信号到达。"
        )

    calibrations: list[ChannelCalibration] = []
    for channel_index in range(16):
        values = per_channel[channel_index]
        baseline, sigma, direction, peak_dev = analyze_channel_samples(values)
        if sigma <= 0 or peak_dev == 0:
            suggested = baseline  # no signal seen; keep the baseline level
        else:
            suggested = baseline + direction * int(max(5 * sigma, 0.5 * peak_dev))
        calibrations.append(
            ChannelCalibration(
                channel=channel_index,
                samples=len(values),
                baseline=baseline,
                sigma=sigma,
                direction=direction,
                peak_dev=peak_dev,
                suggested_threshold=suggested,
            )
        )
    return TcmLinkCalibration(
        device_name=device.name,
        duration_s=seconds,
        frames=frames,
        channels=calibrations,
    )
