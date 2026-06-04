from __future__ import annotations

import threading
from os import PathLike
from pathlib import Path
from queue import Empty, Queue
from typing import BinaryIO

import matplotlib.pyplot as plt

from daq_cli.infrastructure.wave_monitor import WaveMonitorError, WaveMonitorFrame


class WaveMonitorFigure:
    def __init__(self, source_label: str) -> None:
        self._source_label = source_label
        self._figure, axes = plt.subplots(
            4, 4, figsize=(14, 10), sharex=True, sharey=True
        )
        self._axes = list(axes.flatten())
        self._lines = []
        for index, axis in enumerate(self._axes):
            (line,) = axis.plot([], [], color="#5B8FF9", linewidth=1.2, alpha=0.55)
            axis.set_title(f"ch{index}")
            axis.set_xlim(0, 15)
            axis.set_ylim(0, 4095)
            axis.grid(True, alpha=0.25)
            self._lines.append(line)
        self._figure.supxlabel("fine sample")
        self._figure.supylabel("ADC")
        self._figure.tight_layout(rect=(0, 0, 1, 0.95))

    @property
    def figure(self):
        return self._figure

    def update(self, frame: WaveMonitorFrame) -> None:
        max_length = max(len(channel) for channel in frame.channels)
        x_values = list(range(max_length))
        for channel_index, (channel, line, axis) in enumerate(
            zip(frame.channels, self._lines, self._axes, strict=True)
        ):
            line.set_data(x_values[: len(channel)], channel)
            hit = bool(frame.hit_mask & (1 << channel_index))
            line.set_color("#D94841" if hit else "#5B8FF9")
            line.set_linewidth(1.9 if hit else 1.1)
            line.set_alpha(0.95 if hit else 0.45)
            axis.set_xlim(0, max(max_length - 1, 15))
        self._figure.suptitle(
            f"{frame.device_name} | source={self._source_label} | "
            f"event={frame.event_count} | timestamp={frame.timestamp} | "
            f"hit_mask=0x{frame.hit_mask:04X} | send_mode={frame.send_mode}"
        )
        self._figure.canvas.draw_idle()

    def save(self, output_path: Path | str | PathLike[str] | BinaryIO) -> None:
        if isinstance(output_path, (str, PathLike)):
            resolved_path = Path(output_path)
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            self._figure.savefig(resolved_path, dpi=140)
            return
        self._figure.savefig(output_path, dpi=140)


def run_wave_monitor_viewer(
    source_label: str,
    frame_queue: Queue[object],
    stop_event: threading.Event,
) -> None:
    plt.ion()
    figure = WaveMonitorFigure(source_label=source_label)
    plt.show(block=False)
    try:
        while plt.fignum_exists(figure.figure.number) and not stop_event.is_set():
            latest_frame: WaveMonitorFrame | None = None
            while True:
                try:
                    item = frame_queue.get_nowait()
                except Empty:
                    break
                if isinstance(item, Exception):
                    raise item
                latest_frame = item
            if latest_frame is not None:
                figure.update(latest_frame)
            plt.pause(0.05)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        stop_event.set()
        plt.close(figure.figure)


def render_preview_image(
    frame: WaveMonitorFrame,
    source_label: str,
    output_path: Path | str | PathLike[str] | BinaryIO,
) -> None:
    figure = WaveMonitorFigure(source_label=source_label)
    try:
        figure.update(frame)
        figure.save(output_path)
    finally:
        plt.close(figure.figure)
