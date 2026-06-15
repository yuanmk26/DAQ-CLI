from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Iterator

from importlib import resources

from daq_cli.domain.device import DeviceConfig


@dataclass(slots=True)
class WaveMonitorFrame:
    device_name: str
    event_count: int
    timestamp: int
    hit_mask: int
    send_mode: int
    channels: list[list[int]]


@dataclass(slots=True)
class MultiBoardWaveUpdate:
    board_name: str
    board_index: int
    frame: WaveMonitorFrame


class WaveMonitorError(RuntimeError):
    """Wave monitor runtime failure."""


class BaseWaveMonitorSource:
    source_label = "unknown"

    def frames(self, stop_event: threading.Event) -> Iterator[WaveMonitorFrame]:
        raise NotImplementedError


class BaseMultiBoardWaveMonitorSource:
    source_label = "unknown"

    @property
    def board_names(self) -> list[str]:
        raise NotImplementedError

    def updates(self, stop_event: threading.Event) -> Iterator[MultiBoardWaveUpdate]:
        raise NotImplementedError


def load_demo_frames() -> list[WaveMonitorFrame]:
    sample_path = resources.files("daq_cli.monitoring_samples").joinpath(
        "demo_frames.json"
    )
    raw = json.loads(sample_path.read_text(encoding="utf-8"))
    frames = []
    for item in raw["frames"]:
        channels = [[int(value) for value in channel] for channel in item["channels"]]
        _validate_channels(channels)
        frames.append(
            WaveMonitorFrame(
                device_name="demo",
                event_count=int(item["event_count"]),
                timestamp=int(item["timestamp"]),
                hit_mask=int(item["hit_mask"]),
                send_mode=int(item["send_mode"]),
                channels=channels,
            )
        )
    return frames


def parse_replay_dump(path: Path, device_name: str) -> list[WaveMonitorFrame]:
    events: dict[int, dict[str, object]] = {}
    in_dump = False
    current_event_id: int | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("TCP_SENT_DUMP_BEGIN"):
            in_dump = True
            continue
        if line.startswith("TCP_SENT_DUMP_END"):
            break
        if not in_dump:
            continue

        if line.startswith("EVENT_BEGIN "):
            fields = _parse_key_values(line)
            event_id = int(fields["id"], 10)
            events[event_id] = {
                "event_count": event_id,
                "timestamp": event_id,
                "hit_mask": int(fields.get("hit_mask", "0"), 16),
                "samples": {},
            }
            current_event_id = event_id
            continue

        if line.startswith("EVENT_END "):
            current_event_id = None
            continue

        if current_event_id is None or not line.startswith("INPUT "):
            continue

        fields = _parse_key_values(line)
        event = events[current_event_id]
        samples = event["samples"]
        sample_index = int(fields["sample"], 10)
        channel_index = int(fields["ch"], 10)
        a_value = int(fields["a"], 10)
        b_value = int(fields["b"], 10)
        samples[(sample_index, channel_index)] = (a_value, b_value)

    frames = []
    for event_id in sorted(events):
        event = events[event_id]
        channels = [[] for _ in range(16)]
        samples: dict[tuple[int, int], tuple[int, int]] = event["samples"]  # type: ignore[assignment]
        max_sample = max(sample for sample, _ in samples) if samples else -1
        for sample_index in range(max_sample + 1):
            for channel_index in range(16):
                a_value, b_value = samples.get((sample_index, channel_index), (0, 0))
                channels[channel_index].append(a_value)
                channels[channel_index].append(b_value)
        _validate_channels(channels)
        frames.append(
            WaveMonitorFrame(
                device_name=device_name,
                event_count=int(event["event_count"]),
                timestamp=int(event["timestamp"]),
                hit_mask=int(event["hit_mask"]),
                send_mode=1,
                channels=channels,
            )
        )

    if not frames:
        raise WaveMonitorError(f"No replayable events found in '{path}'.")
    return frames


class DemoWaveMonitorSource(BaseWaveMonitorSource):
    source_label = "demo"

    def __init__(self, device_name: str) -> None:
        self._device_name = device_name
        self._frames = load_demo_frames()

    def frames(self, stop_event: threading.Event) -> Iterator[WaveMonitorFrame]:
        while not stop_event.is_set():
            for frame in self._frames:
                if stop_event.is_set():
                    return
                yield WaveMonitorFrame(
                    device_name=self._device_name,
                    event_count=frame.event_count,
                    timestamp=frame.timestamp,
                    hit_mask=frame.hit_mask,
                    send_mode=frame.send_mode,
                    channels=[list(channel) for channel in frame.channels],
                )
                if stop_event.wait(0.5):
                    return


class ReplayWaveMonitorSource(BaseWaveMonitorSource):
    source_label = "replay"

    def __init__(self, device_name: str, replay_path: Path) -> None:
        self._device_name = device_name
        self._frames = parse_replay_dump(replay_path, device_name=device_name)

    def frames(self, stop_event: threading.Event) -> Iterator[WaveMonitorFrame]:
        while not stop_event.is_set():
            for frame in self._frames:
                if stop_event.is_set():
                    return
                yield frame
                if stop_event.wait(0.5):
                    return


class DemoMultiBoardWaveMonitorSource(BaseMultiBoardWaveMonitorSource):
    source_label = "multi-demo"

    def __init__(
        self,
        board_names: list[str] | None = None,
        events: int = 100,
    ) -> None:
        resolved_board_names = board_names or ["dev1", "dev2"]
        if len(resolved_board_names) < 2:
            raise WaveMonitorError("Multi-board demo requires at least two board names.")
        self._board_names = list(resolved_board_names)
        self._events = max(int(events), 1)
        self._templates = load_demo_frames()

    @property
    def board_names(self) -> list[str]:
        return list(self._board_names)

    def updates(self, stop_event: threading.Event) -> Iterator[MultiBoardWaveUpdate]:
        for event_count in range(1, self._events + 1):
            if stop_event.is_set():
                return
            for board_index, board_name in enumerate(self._board_names):
                if board_index == 1 and event_count % 7 == 0:
                    continue
                yield MultiBoardWaveUpdate(
                    board_name=board_name,
                    board_index=board_index,
                    frame=self._build_frame(
                        board_name=board_name,
                        board_index=board_index,
                        event_count=event_count,
                    ),
                )
                if stop_event.wait(0.03):
                    return

    def _build_frame(
        self,
        *,
        board_name: str,
        board_index: int,
        event_count: int,
    ) -> WaveMonitorFrame:
        template = self._templates[(event_count + board_index) % len(self._templates)]
        channel_bias = board_index * 12 + (event_count % 5)
        channels = [
            [sample + channel_bias + channel_index for sample in channel]
            for channel_index, channel in enumerate(template.channels)
        ]
        return WaveMonitorFrame(
            device_name=board_name,
            event_count=event_count,
            timestamp=(event_count * 100) + board_index,
            hit_mask=((template.hit_mask << board_index) | (template.hit_mask >> (16 - board_index))) & 0xFFFF,
            send_mode=template.send_mode,
            channels=channels,
        )


class LiveWaveMonitorSource(BaseWaveMonitorSource):
    source_label = "live"

    def __init__(
        self,
        device: DeviceConfig,
        adc_length: int = 64,
        tcp_timeout_s: float = 1.0,
    ) -> None:
        self._device = device
        self._adc_length = adc_length
        self._tcp_timeout_s = tcp_timeout_s

    def frames(self, stop_event: threading.Event) -> Iterator[WaveMonitorFrame]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self._tcp_timeout_s)
        sock.connect((self._device.ip, self._device.tcp_port))
        buffer = bytearray()
        try:
            while not stop_event.is_set():
                try:
                    chunk = sock.recv(8192)
                except socket.timeout:
                    continue
                if not chunk:
                    raise WaveMonitorError("TCP stream closed by peer.")
                buffer.extend(chunk)
                while not stop_event.is_set():
                    frame = self._try_parse_frame(buffer)
                    if frame is None:
                        break
                    yield frame
        finally:
            sock.close()

    def _try_parse_frame(self, buffer: bytearray) -> WaveMonitorFrame | None:
        header = b"\xFF\xFE\x01"
        while len(buffer) >= 3 and buffer[:3] != header:
            del buffer[0]
        if len(buffer) < 20:
            return None
        send_mode = buffer[3]
        if send_mode != 1:
            raise WaveMonitorError(
                f"Expected send_mode=1 for full-waveform monitoring, got {send_mode}."
            )
        payload_bytes = 16 * self._adc_length * 4
        frame_bytes = 20 + payload_bytes
        if len(buffer) < frame_bytes:
            return None
        raw = bytes(buffer[:frame_bytes])
        del buffer[:frame_bytes]
        event_count = int.from_bytes(raw[4:8], byteorder="big", signed=False)
        timestamp = int.from_bytes(raw[8:16], byteorder="big", signed=False)
        hit_mask = int.from_bytes(raw[16:18], byteorder="big", signed=False)
        channels = [[] for _ in range(16)]
        payload = raw[20:]
        offset = 0
        for _sample_index in range(self._adc_length):
            for channel_index in range(16):
                word = int.from_bytes(payload[offset : offset + 4], byteorder="big")
                offset += 4
                channels[channel_index].append((word >> 16) & 0x0FFF)
                channels[channel_index].append(word & 0x0FFF)
        return WaveMonitorFrame(
            device_name=self._device.name,
            event_count=event_count,
            timestamp=timestamp,
            hit_mask=hit_mask,
            send_mode=send_mode,
            channels=channels,
        )


def load_repo_replay_sample(device_name: str = "replay") -> list[WaveMonitorFrame]:
    sample_path = resources.files("daq_cli.monitoring_samples").joinpath(
        "replay_dump.txt"
    )
    return parse_replay_dump(Path(sample_path), device_name=device_name)


class WaveMonitorProducer(threading.Thread):
    def __init__(
        self,
        source: BaseWaveMonitorSource,
        queue: Queue[object],
        stop_event: threading.Event,
    ) -> None:
        super().__init__(daemon=True, name="wave_monitor_producer")
        self._source = source
        self._queue = queue
        self._stop_event = stop_event

    def run(self) -> None:
        try:
            for frame in self._source.frames(self._stop_event):
                if self._stop_event.is_set():
                    return
                self._publish(frame)
        except Exception as exc:
            self._publish(exc)

    def _publish(self, item: object) -> None:
        try:
            self._queue.put_nowait(item)
            return
        except Exception:
            pass
        try:
            self._queue.get_nowait()
        except Empty:
            pass
        self._queue.put_nowait(item)


class MultiBoardWaveMonitorProducer(threading.Thread):
    def __init__(
        self,
        source: BaseMultiBoardWaveMonitorSource,
        queue: Queue[object],
        stop_event: threading.Event,
    ) -> None:
        super().__init__(daemon=True, name="multi_board_wave_monitor_producer")
        self._source = source
        self._queue = queue
        self._stop_event = stop_event

    def run(self) -> None:
        try:
            for update in self._source.updates(self._stop_event):
                if self._stop_event.is_set():
                    return
                self._publish(update)
        except Exception as exc:
            self._publish(exc)

    def _publish(self, item: object) -> None:
        try:
            self._queue.put_nowait(item)
            return
        except Exception:
            pass
        try:
            self._queue.get_nowait()
        except Empty:
            pass
        self._queue.put_nowait(item)


def _parse_key_values(line: str) -> dict[str, str]:
    values = {}
    for item in line.split()[1:]:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        values[key] = value
    return values


def _validate_channels(channels: list[list[int]]) -> None:
    if len(channels) != 16:
        raise WaveMonitorError(
            f"Wave monitor expects 16 channels, got {len(channels)}."
        )
    expected_length = len(channels[0]) if channels else 0
    for channel in channels:
        if len(channel) != expected_length:
            raise WaveMonitorError("Wave monitor channels must be equal length.")
