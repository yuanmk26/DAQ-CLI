from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from os import PathLike
from pathlib import Path
from queue import Empty, Queue
from typing import BinaryIO
import tkinter

import matplotlib.pyplot as plt

from daq_cli.infrastructure.wave_monitor import WaveMonitorFrame


class WaveMonitorRunState(str, Enum):
    RUN = "RUN"
    STOP = "STOP"
    SINGLE_ARMED = "SINGLE-ARMED"


@dataclass(slots=True)
class WaveMonitorLoopState:
    run_state: WaveMonitorRunState = WaveMonitorRunState.RUN
    last_frame: WaveMonitorFrame | None = None


@dataclass(slots=True)
class WaveMonitorLoopStepResult:
    loop_state: WaveMonitorLoopState
    should_render: bool


DEFAULT_FIGSIZE = (14.0, 10.0)


class WaveMonitorFigure:
    def __init__(self, source_label: str) -> None:
        self._source_label = source_label
        figsize = _compute_default_figsize()
        self._figure, axes = plt.subplots(
            4, 4, figsize=figsize, sharex=True, sharey=True
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
        self._figure.text(
            0.01,
            0.945,
            "space: run/stop | s: single | r: run | q: quit",
            ha="left",
            va="top",
            fontsize=9,
            color="#555555",
        )
        self._figure.tight_layout(rect=(0, 0, 1, 0.9))
        self.set_state(WaveMonitorRunState.RUN)

    @property
    def figure(self):
        return self._figure

    def update(
        self, frame: WaveMonitorFrame, run_state: WaveMonitorRunState
    ) -> None:
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
        self._set_title(frame=frame, run_state=run_state)
        self._figure.canvas.draw_idle()

    def set_state(
        self,
        run_state: WaveMonitorRunState,
        frame: WaveMonitorFrame | None = None,
    ) -> None:
        self._set_title(frame=frame, run_state=run_state)
        self._figure.canvas.draw_idle()

    def _set_title(
        self,
        frame: WaveMonitorFrame | None,
        run_state: WaveMonitorRunState,
    ) -> None:
        if frame is None:
            self._figure.suptitle(
                f"no frame yet | source={self._source_label} | state={run_state.value}"
            )
            return
        self._figure.suptitle(
            f"{frame.device_name} | source={self._source_label} | "
            f"state={run_state.value} | "
            f"event={frame.event_count} | timestamp={frame.timestamp} | "
            f"hit_mask=0x{frame.hit_mask:04X} | send_mode={frame.send_mode}"
        )

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
    loop_state = WaveMonitorLoopState()
    _disconnect_default_key_handler(figure.figure)

    def on_key_press(event) -> None:
        key = (event.key or "").lower()
        if key == " ":
            loop_state.run_state = (
                WaveMonitorRunState.STOP
                if loop_state.run_state == WaveMonitorRunState.RUN
                else WaveMonitorRunState.RUN
            )
            figure.set_state(
                run_state=loop_state.run_state,
                frame=loop_state.last_frame,
            )
        elif key == "s":
            loop_state.run_state = WaveMonitorRunState.SINGLE_ARMED
            figure.set_state(
                run_state=loop_state.run_state,
                frame=loop_state.last_frame,
            )
        elif key == "r":
            loop_state.run_state = WaveMonitorRunState.RUN
            figure.set_state(
                run_state=loop_state.run_state,
                frame=loop_state.last_frame,
            )
        elif key == "q":
            stop_event.set()

    figure.figure.canvas.mpl_connect("key_press_event", on_key_press)
    plt.show(block=False)
    try:
        while plt.fignum_exists(figure.figure.number) and not stop_event.is_set():
            latest_frame = _drain_latest_frame(frame_queue)
            step_result = _advance_loop_state(
                loop_state=loop_state,
                latest_frame=latest_frame,
            )
            loop_state = step_result.loop_state
            if step_result.should_render and loop_state.last_frame is not None:
                figure.update(
                    frame=loop_state.last_frame,
                    run_state=loop_state.run_state,
                )
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
        figure.update(frame, run_state=WaveMonitorRunState.RUN)
        figure.save(output_path)
    finally:
        plt.close(figure.figure)


def _drain_latest_frame(frame_queue: Queue[object]) -> WaveMonitorFrame | None:
    latest_frame: WaveMonitorFrame | None = None
    while True:
        try:
            item = frame_queue.get_nowait()
        except Empty:
            break
        if isinstance(item, Exception):
            raise item
        latest_frame = item
    return latest_frame


def _advance_loop_state(
    loop_state: WaveMonitorLoopState,
    latest_frame: WaveMonitorFrame | None,
) -> WaveMonitorLoopStepResult:
    if latest_frame is None:
        return WaveMonitorLoopStepResult(loop_state=loop_state, should_render=False)
    if loop_state.run_state == WaveMonitorRunState.RUN:
        return WaveMonitorLoopStepResult(
            loop_state=WaveMonitorLoopState(
                run_state=WaveMonitorRunState.RUN,
                last_frame=latest_frame,
            ),
            should_render=True,
        )
    if loop_state.run_state == WaveMonitorRunState.SINGLE_ARMED:
        return WaveMonitorLoopStepResult(
            loop_state=WaveMonitorLoopState(
                run_state=WaveMonitorRunState.STOP,
                last_frame=latest_frame,
            ),
            should_render=True,
        )
    return WaveMonitorLoopStepResult(
        loop_state=loop_state,
        should_render=False,
    )


def _disconnect_default_key_handler(figure) -> None:
    manager = getattr(figure.canvas, "manager", None)
    if manager is None:
        return
    handler_id = getattr(manager, "key_press_handler_id", None)
    if handler_id is None:
        return
    figure.canvas.mpl_disconnect(handler_id)


def _compute_default_figsize() -> tuple[float, float]:
    screen_size = _get_screen_size_px()
    if screen_size is None:
        return DEFAULT_FIGSIZE

    screen_width_px, screen_height_px = screen_size
    dpi = float(plt.rcParams.get("figure.dpi", 100.0))
    target_width_in = max((screen_width_px - 160) / dpi, 8.0)
    target_height_in = max((screen_height_px - 180) / dpi, 6.0)

    base_width_in, base_height_in = DEFAULT_FIGSIZE
    scale = min(
        target_width_in / base_width_in,
        target_height_in / base_height_in,
        1.0,
    )
    return (base_width_in * scale, base_height_in * scale)


def _get_screen_size_px() -> tuple[int, int] | None:
    root = None
    try:
        root = tkinter.Tk()
        root.withdraw()
        return (int(root.winfo_screenwidth()), int(root.winfo_screenheight()))
    except tkinter.TclError:
        return None
    finally:
        if root is not None:
            root.destroy()
