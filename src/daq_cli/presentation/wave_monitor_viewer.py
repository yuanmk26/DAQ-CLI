from __future__ import annotations

import threading
from bisect import bisect_left
from dataclasses import dataclass
from enum import Enum
from os import PathLike
from pathlib import Path
from queue import Empty, Queue
from typing import BinaryIO
import tkinter

import matplotlib.pyplot as plt

from daq_cli.infrastructure.wave_monitor import MultiBoardWaveUpdate, WaveMonitorFrame


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
DEFAULT_MULTI_BOARD_HISTORY_LIMIT = 200


@dataclass(slots=True)
class MultiBoardViewerState:
    run_state: WaveMonitorRunState = WaveMonitorRunState.RUN
    selected_board_index: int = 0
    selected_event_count: int | None = None
    board_histories: dict[int, dict[int, WaveMonitorFrame]] | None = None
    board_event_order: dict[int, list[int]] | None = None

    def __post_init__(self) -> None:
        if self.board_histories is None:
            self.board_histories = {}
        if self.board_event_order is None:
            self.board_event_order = {}


@dataclass(slots=True)
class MultiBoardViewerStepResult:
    viewer_state: MultiBoardViewerState
    should_render: bool


class WaveMonitorFigure:
    def __init__(self, source_label: str, help_text: str | None = None) -> None:
        self._source_label = source_label
        figsize = _compute_default_figsize()
        self._figure, axes = plt.subplots(4, 4, figsize=figsize, sharex=True)
        self._axes = list(axes.flatten())
        self._lines = []
        for index, axis in enumerate(self._axes):
            (line,) = axis.plot([], [], color="#5B8FF9", linewidth=1.2, alpha=0.55)
            axis.set_title(f"ch{index}")
            axis.set_xlim(0, 15)
            axis.grid(True, alpha=0.25)
            self._lines.append(line)
        self._figure.supxlabel("fine sample")
        self._figure.supylabel("ADC")
        self._figure.text(
            0.01,
            0.945,
            help_text or "space: run/stop | s: single | r: run | q: quit",
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
            axis.set_ylim(*_compute_channel_ylim(channel))
        self._set_title(frame=frame, run_state=run_state)
        self._figure.canvas.draw_idle()

    def update_custom(self, frame: WaveMonitorFrame, title: str) -> None:
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
            axis.set_ylim(*_compute_channel_ylim(channel))
        self.set_custom_title(title)

    def set_state(
        self,
        run_state: WaveMonitorRunState,
        frame: WaveMonitorFrame | None = None,
    ) -> None:
        self._set_title(frame=frame, run_state=run_state)
        self._figure.canvas.draw_idle()

    def set_custom_title(self, title: str) -> None:
        self._figure.suptitle(title)
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
    figure.figure.canvas.mpl_connect("close_event", lambda _event: stop_event.set())
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


def run_multi_board_wave_viewer(
    group_label: str,
    board_names: list[str],
    frame_queue: Queue[object],
    stop_event: threading.Event,
) -> None:
    plt.ion()
    figure = WaveMonitorFigure(
        source_label=f"multi-watch:{group_label}",
        help_text=(
            "tab/[ ]/1-9: switch board | ,/left: prev event (STOP) | "
            "./right: next event (STOP) | space: run/stop | s: single | r: run | q: quit"
        ),
    )
    viewer_state = MultiBoardViewerState()
    _disconnect_default_key_handler(figure.figure)

    def render_selected() -> None:
        board_name = board_names[viewer_state.selected_board_index]
        current_frame = _get_selected_multi_board_frame(viewer_state)
        title = _format_multi_board_title(
            group_label=group_label,
            board_name=board_name,
            board_index=viewer_state.selected_board_index,
            board_count=len(board_names),
            run_state=viewer_state.run_state,
            selected_event_count=viewer_state.selected_event_count,
            frame=current_frame,
        )
        if current_frame is None:
            figure.set_custom_title(title)
        else:
            figure.update_custom(current_frame, title)

    def on_key_press(event) -> None:
        nonlocal viewer_state
        key = (event.key or "").lower()
        if key == " ":
            if viewer_state.run_state == WaveMonitorRunState.RUN:
                viewer_state.run_state = WaveMonitorRunState.STOP
            else:
                _jump_to_latest_multi_board_event(viewer_state)
                viewer_state.run_state = WaveMonitorRunState.RUN
            render_selected()
        elif key == "s":
            viewer_state.run_state = WaveMonitorRunState.SINGLE_ARMED
            render_selected()
        elif key == "r":
            _jump_to_latest_multi_board_event(viewer_state)
            viewer_state.run_state = WaveMonitorRunState.RUN
            render_selected()
        elif key == "tab" or key == "]":
            viewer_state.selected_board_index = (
                viewer_state.selected_board_index + 1
            ) % len(board_names)
            if viewer_state.run_state == WaveMonitorRunState.RUN:
                _jump_to_latest_multi_board_event(viewer_state)
            render_selected()
        elif key == "[":
            viewer_state.selected_board_index = (
                viewer_state.selected_board_index - 1
            ) % len(board_names)
            if viewer_state.run_state == WaveMonitorRunState.RUN:
                _jump_to_latest_multi_board_event(viewer_state)
            render_selected()
        elif key.isdigit():
            target_index = int(key) - 1
            if 0 <= target_index < len(board_names):
                viewer_state.selected_board_index = target_index
                if viewer_state.run_state == WaveMonitorRunState.RUN:
                    _jump_to_latest_multi_board_event(viewer_state)
                render_selected()
        elif key in {",", "left"}:
            if (
                _can_navigate_multi_board_history(viewer_state)
                and _select_previous_multi_board_event(viewer_state)
            ):
                render_selected()
        elif key in {".", "right"}:
            if (
                _can_navigate_multi_board_history(viewer_state)
                and _select_next_multi_board_event(viewer_state)
            ):
                render_selected()
        elif key == "q":
            stop_event.set()

    figure.figure.canvas.mpl_connect("key_press_event", on_key_press)
    figure.figure.canvas.mpl_connect("close_event", lambda _event: stop_event.set())
    render_selected()
    plt.show(block=False)
    try:
        while plt.fignum_exists(figure.figure.number) and not stop_event.is_set():
            updates = _drain_multi_board_updates(frame_queue)
            should_render = False
            for update in updates:
                step_result = _advance_multi_board_viewer_state(
                    viewer_state=viewer_state,
                    update=update,
                    history_limit=DEFAULT_MULTI_BOARD_HISTORY_LIMIT,
                )
                viewer_state = step_result.viewer_state
                should_render = should_render or step_result.should_render
            if should_render:
                render_selected()
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


def _drain_multi_board_updates(frame_queue: Queue[object]) -> list[MultiBoardWaveUpdate]:
    updates: list[MultiBoardWaveUpdate] = []
    while True:
        try:
            item = frame_queue.get_nowait()
        except Empty:
            break
        if isinstance(item, Exception):
            raise item
        updates.append(item)
    return updates


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


def _advance_multi_board_viewer_state(
    viewer_state: MultiBoardViewerState,
    update: MultiBoardWaveUpdate,
    *,
    history_limit: int = DEFAULT_MULTI_BOARD_HISTORY_LIMIT,
) -> MultiBoardViewerStepResult:
    _store_multi_board_frame(viewer_state, update, history_limit=history_limit)
    if update.board_index != viewer_state.selected_board_index:
        return MultiBoardViewerStepResult(
            viewer_state=viewer_state,
            should_render=False,
        )

    if viewer_state.run_state == WaveMonitorRunState.RUN:
        viewer_state.selected_event_count = update.frame.event_count
        return MultiBoardViewerStepResult(
            viewer_state=viewer_state,
            should_render=True,
        )
    if viewer_state.run_state == WaveMonitorRunState.SINGLE_ARMED:
        viewer_state.selected_event_count = update.frame.event_count
        viewer_state.run_state = WaveMonitorRunState.STOP
        return MultiBoardViewerStepResult(
            viewer_state=viewer_state,
            should_render=True,
        )
    return MultiBoardViewerStepResult(
        viewer_state=viewer_state,
        should_render=False,
    )


def _store_multi_board_frame(
    viewer_state: MultiBoardViewerState,
    update: MultiBoardWaveUpdate,
    *,
    history_limit: int = DEFAULT_MULTI_BOARD_HISTORY_LIMIT,
) -> None:
    history = viewer_state.board_histories.setdefault(update.board_index, {})
    order = viewer_state.board_event_order.setdefault(update.board_index, [])
    event_count = update.frame.event_count
    if event_count not in history:
        order.append(event_count)
    history[event_count] = update.frame
    while len(order) > history_limit:
        dropped_event_count = order.pop(0)
        history.pop(dropped_event_count, None)


def _get_selected_multi_board_frame(
    viewer_state: MultiBoardViewerState,
) -> WaveMonitorFrame | None:
    selected_event_count = viewer_state.selected_event_count
    if selected_event_count is None:
        return None
    history = viewer_state.board_histories.get(viewer_state.selected_board_index, {})
    return history.get(selected_event_count)


def _get_latest_multi_board_event_count(
    viewer_state: MultiBoardViewerState,
) -> int | None:
    order = viewer_state.board_event_order.get(viewer_state.selected_board_index, [])
    if not order:
        return None
    return order[-1]


def _jump_to_latest_multi_board_event(viewer_state: MultiBoardViewerState) -> bool:
    latest_event_count = _get_latest_multi_board_event_count(viewer_state)
    if latest_event_count is None:
        return False
    viewer_state.selected_event_count = latest_event_count
    return True


def _select_previous_multi_board_event(viewer_state: MultiBoardViewerState) -> bool:
    return _select_relative_multi_board_event(viewer_state, step=-1)


def _select_next_multi_board_event(viewer_state: MultiBoardViewerState) -> bool:
    return _select_relative_multi_board_event(viewer_state, step=1)


def _select_relative_multi_board_event(
    viewer_state: MultiBoardViewerState,
    *,
    step: int,
) -> bool:
    order = viewer_state.board_event_order.get(viewer_state.selected_board_index, [])
    if not order:
        return False
    if viewer_state.selected_event_count is None:
        viewer_state.selected_event_count = order[-1 if step < 0 else 0]
        return True

    insertion_index = bisect_left(order, viewer_state.selected_event_count)
    if step < 0:
        candidate_index = insertion_index - 1
        if (
            insertion_index < len(order)
            and order[insertion_index] == viewer_state.selected_event_count
        ):
            candidate_index = insertion_index - 1
    else:
        candidate_index = insertion_index
        if (
            insertion_index < len(order)
            and order[insertion_index] == viewer_state.selected_event_count
        ):
            candidate_index = insertion_index + 1
    if not (0 <= candidate_index < len(order)):
        return False
    viewer_state.selected_event_count = order[candidate_index]
    return True


def _can_navigate_multi_board_history(viewer_state: MultiBoardViewerState) -> bool:
    return viewer_state.run_state == WaveMonitorRunState.STOP


def _disconnect_default_key_handler(figure) -> None:
    manager = getattr(figure.canvas, "manager", None)
    if manager is None:
        return
    handler_id = getattr(manager, "key_press_handler_id", None)
    if handler_id is None:
        return
    figure.canvas.mpl_disconnect(handler_id)


def _compute_channel_ylim(channel: list[int]) -> tuple[float, float]:
    min_value = min(channel)
    max_value = max(channel)
    span = max_value - min_value
    if span > 0:
        padding = max(span * 0.08, 1.0)
    else:
        padding = max(abs(max_value) * 0.02, 1.0)
    return (min_value - padding, max_value + padding)


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


def _format_multi_board_title(
    group_label: str,
    board_name: str,
    board_index: int,
    board_count: int,
    run_state: WaveMonitorRunState,
    selected_event_count: int | None,
    frame: WaveMonitorFrame | None,
) -> str:
    prefix = (
        f"group={group_label} | board={board_name} ({board_index + 1}/{board_count}) | "
        f"state={run_state.value}"
    )
    if frame is None:
        if selected_event_count is None:
            return f"{prefix} | no frame yet"
        return f"{prefix} | event={selected_event_count} | missing on this board"
    return (
        f"{prefix} | event={selected_event_count if selected_event_count is not None else frame.event_count} | "
        f"timestamp={frame.timestamp} | "
        f"hit_mask=0x{frame.hit_mask:04X} | send_mode={frame.send_mode}"
    )
