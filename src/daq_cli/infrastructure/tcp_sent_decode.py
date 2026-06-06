from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from daq_cli.infrastructure.tcp_sent_protocol import (
    ADC_LENGTH,
    FEATURE_BYTES,
    FRAME_PREFIX,
    HEADER_BYTES,
    frame_total_size,
)


@dataclass(slots=True)
class TcpSentFeatureRecord:
    channel: int
    baseline: int
    peak_amp: int
    peak_pos: int
    integral: int


@dataclass(slots=True)
class DecodedTcpSentEvent:
    source_file: Path
    send_mode: int
    event_count: int
    timestamp: int
    hit_mask: int
    feature_record_length: int
    channels: list[list[int] | None]
    feature_records: list[TcpSentFeatureRecord]
    raw_packet_bytes: int

    def to_json_dict(self) -> dict[str, object]:
        return {
            "source_file": str(self.source_file),
            "send_mode": self.send_mode,
            "event_count": self.event_count,
            "timestamp": self.timestamp,
            "hit_mask": self.hit_mask,
            "hit_mask_hex": f"0x{self.hit_mask:04X}",
            "feature_record_length": self.feature_record_length,
            "channels": self.channels,
            "feature_records": [
                {
                    "channel": record.channel,
                    "baseline": record.baseline,
                    "peak_amp": record.peak_amp,
                    "peak_pos": record.peak_pos,
                    "integral": record.integral,
                }
                for record in self.feature_records
            ],
            "raw_packet_bytes": self.raw_packet_bytes,
        }


class TcpSentDecodeError(RuntimeError):
    """Raised when an offline TCP_SENT packet cannot be decoded."""


def decode_tcp_sent_file(
    path: Path,
    *,
    expected_send_mode: int | None = None,
    adc_length: int = ADC_LENGTH,
) -> DecodedTcpSentEvent:
    return decode_tcp_sent_packet(
        path.read_bytes(),
        source_file=path,
        expected_send_mode=expected_send_mode,
        adc_length=adc_length,
    )


def decode_tcp_sent_packet(
    packet: bytes,
    *,
    source_file: Path,
    expected_send_mode: int | None = None,
    adc_length: int = ADC_LENGTH,
) -> DecodedTcpSentEvent:
    if len(packet) < HEADER_BYTES:
        raise TcpSentDecodeError(
            f"Packet '{source_file}' is shorter than {HEADER_BYTES} bytes."
        )
    if packet[:3] != FRAME_PREFIX:
        raise TcpSentDecodeError(
            f"Packet '{source_file}' does not start with the TCP_SENT frame prefix."
        )

    send_mode = packet[3]
    if send_mode not in {0, 1, 2, 3}:
        raise TcpSentDecodeError(
            f"Packet '{source_file}' has unsupported send_mode {send_mode}."
        )
    if expected_send_mode is not None and send_mode != expected_send_mode:
        raise TcpSentDecodeError(
            f"Packet '{source_file}' send_mode {send_mode} does not match expected "
            f"send_mode {expected_send_mode}."
        )

    event_count = int.from_bytes(packet[4:8], byteorder="big", signed=False)
    timestamp = int.from_bytes(packet[8:16], byteorder="big", signed=False)
    hit_mask = int.from_bytes(packet[16:18], byteorder="big", signed=False)
    feature_record_length = packet[18]
    hit_channels = _hit_channels(hit_mask)
    hit_count = len(hit_channels)

    if send_mode in {0, 1}:
        if feature_record_length != 0:
            raise TcpSentDecodeError(
                f"Packet '{source_file}' send_mode {send_mode} has feature record "
                f"length {feature_record_length}, expected 0."
            )
    elif feature_record_length != FEATURE_BYTES:
        raise TcpSentDecodeError(
            f"Packet '{source_file}' send_mode {send_mode} has feature record length "
            f"{feature_record_length}, expected {FEATURE_BYTES}."
        )

    expected_bytes = frame_total_size(
        send_mode=send_mode,
        hit_count=hit_count,
        adc_length=adc_length,
        feature_bytes=FEATURE_BYTES,
    )
    if len(packet) != expected_bytes:
        raise TcpSentDecodeError(
            f"Packet '{source_file}' has {len(packet)} bytes, expected {expected_bytes} "
            f"for send_mode {send_mode} with hit_count {hit_count}."
        )

    offset = HEADER_BYTES
    feature_records: list[TcpSentFeatureRecord] = []
    if send_mode in {2, 3}:
        for _ in range(hit_count):
            feature = packet[offset : offset + FEATURE_BYTES]
            offset += FEATURE_BYTES
            feature_records.append(
                TcpSentFeatureRecord(
                    channel=feature[0],
                    baseline=int.from_bytes(feature[1:3], "big", signed=False),
                    peak_amp=int.from_bytes(feature[3:5], "big", signed=False),
                    peak_pos=feature[5],
                    integral=int.from_bytes(feature[6:10], "big", signed=True),
                )
            )

    channels: list[list[int] | None] = [None] * 16
    if send_mode == 1:
        waveform_channels = list(range(16))
    elif send_mode in {0, 3}:
        waveform_channels = hit_channels
    else:
        waveform_channels = []

    if waveform_channels:
        for channel_index in waveform_channels:
            channels[channel_index] = []
        for _sample_index in range(adc_length):
            for channel_index in waveform_channels:
                word = int.from_bytes(
                    packet[offset : offset + 4],
                    byteorder="big",
                    signed=False,
                )
                offset += 4
                assert channels[channel_index] is not None
                channels[channel_index].append((word >> 16) & 0x0FFF)
                channels[channel_index].append(word & 0x0FFF)

    return DecodedTcpSentEvent(
        source_file=source_file,
        send_mode=send_mode,
        event_count=event_count,
        timestamp=timestamp,
        hit_mask=hit_mask,
        feature_record_length=feature_record_length,
        channels=channels,
        feature_records=feature_records,
        raw_packet_bytes=len(packet),
    )


def load_capture_info(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def write_decoded_event_json(
    event: DecodedTcpSentEvent,
    output_path: Path,
) -> None:
    output_path.write_text(
        json.dumps(event.to_json_dict(), indent=2),
        encoding="utf-8",
    )


def _hit_channels(hit_mask: int) -> list[int]:
    return [channel for channel in range(16) if (hit_mask >> channel) & 0x1]
