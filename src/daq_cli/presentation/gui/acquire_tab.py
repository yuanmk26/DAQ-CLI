"""采集 tab：单板/多板采集控制与进度。"""

from __future__ import annotations

import queue
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from daq_cli.application.acquire_service import AcquireService
from daq_cli.application.output_config import (
    AcquireOutputsConfig,
    OutputTargetConfig,
    TextOutputConfig,
)
from daq_cli.infrastructure.tcp_sent_decode import decode_tcp_sent_packet
from daq_cli.infrastructure.wave_monitor import MultiBoardWaveUpdate, WaveMonitorFrame
from daq_cli.presentation.gui import formatting, threads
from daq_cli.presentation.gui.widgets import ResultArea, ScrollableFrame
from daq_cli.presentation.wave_monitor_viewer import (
    DEFAULT_MULTI_BOARD_HISTORY_LIMIT,
    MultiBoardViewerState,
    WaveMonitorFigure,
    WaveMonitorRunState,
    _advance_multi_board_viewer_state,
    _can_navigate_multi_board_history,
    _format_multi_board_title,
    _get_selected_multi_board_aggregate_timestamp,
    _get_selected_multi_board_frame,
    _jump_to_latest_multi_board_event,
    _select_next_multi_board_event,
    _select_previous_multi_board_event,
)


class AcquireTab:
    def __init__(self, app, notebook) -> None:
        self.app = app
        # The whole tab is scrollable so the result strip stays reachable
        # even on short windows; children go into frame.inner.
        self.frame = ScrollableFrame(notebook, padding=8)
        self.acquire_service = AcquireService()
        self._single_busy = False
        self._multi_busy = False
        self._progress_queue: queue.Queue[object] | None = None
        self._watch_frame_queue: queue.Queue[bytes] | None = None
        self._watch_figure: WaveMonitorFigure | None = None
        self._watch_canvas = None  # FigureCanvasTkAgg
        # multi-board embedded watch state
        self._multi_watch_queue: queue.Queue[object] | None = None
        self._multi_watch_figure: WaveMonitorFigure | None = None
        self._multi_watch_canvas = None  # FigureCanvasTkAgg
        self._multi_viewer_state = None  # MultiBoardViewerState
        self._multi_board_names: list[str] = []
        self._multi_group_label = ""

        # The acquire tab splits into two pages so each capture mode gets
        # the full height (the embedded waveform monitor in particular).
        self._inner_notebook = ttk.Notebook(self.frame.inner)
        self._inner_notebook.pack(fill=tk.BOTH, expand=True)
        self._single_page = ttk.Frame(self._inner_notebook, padding=8)
        self._multi_page = ttk.Frame(self._inner_notebook, padding=8)
        self._inner_notebook.add(self._single_page, text="单板采集")
        self._inner_notebook.add(self._multi_page, text="多板采集")

        self._build_single_group(self._single_page)
        self._build_watch_host(self._single_page)
        self._ensure_watch_canvas("")  # canvas is always present
        self.single_result = ResultArea(self._single_page, text="单板结果", height=5)
        # Fixed-height strip so the embedded waveform gets the remaining space.
        self.single_result.pack(fill=tk.X)

        self._build_multi_group(self._multi_page)
        self._build_multi_watch_host(self._multi_page)
        self._build_multi_watch_controls(self._multi_page)
        self._ensure_multi_watch_canvas()
        self.multi_result = ResultArea(self._multi_page, text="多板结果", height=5)
        self.multi_result.pack(fill=tk.X)

    def _build_watch_host(self, parent) -> None:
        """Frame hosting the embedded waveform canvas; always visible."""
        self._watch_host = ttk.Frame(parent)
        self._watch_host.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

    def _build_multi_watch_host(self, parent) -> None:
        """Frame hosting the embedded multi-board waveform canvas; always visible."""
        self._multi_watch_host = ttk.Frame(parent)
        self._multi_watch_host.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

    def _build_multi_watch_controls(self, parent) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(row, text="显示板:").pack(side=tk.LEFT)
        self._multi_board_var = tk.StringVar()
        self._multi_board_combo = ttk.Combobox(
            row, textvariable=self._multi_board_var, state="readonly", width=14
        )
        self._multi_board_combo.pack(side=tk.LEFT, padx=(4, 12))
        self._multi_board_combo.bind("<<ComboboxSelected>>", self._on_multi_board_select)
        for text, callback in (
            ("上一事件", self._multi_prev_event),
            ("下一事件", self._multi_next_event),
            ("最新", self._multi_latest_event),
        ):
            ttk.Button(row, text=text, command=callback).pack(
                side=tk.LEFT, padx=(0, 6)
            )
        self._multi_watch_status_label = ttk.Label(row, text="")
        self._multi_watch_status_label.pack(side=tk.LEFT, padx=(12, 0))

    # ---------------------------------------------------------------- forms

    def _build_single_group(self, parent) -> None:
        group = ttk.LabelFrame(parent, text="单板采集", padding=(8, 4))
        group.pack(fill=tk.X, pady=(0, 6))

        row = ttk.Frame(group)
        row.pack(fill=tk.X)
        ttk.Label(row, text="设备:").pack(side=tk.LEFT)
        self._device_var = tk.StringVar()
        self._device_combo = ttk.Combobox(
            row, textvariable=self._device_var, state="readonly", width=18
        )
        self._device_combo.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(row, text="事件数:").pack(side=tk.LEFT)
        self._events_var = tk.StringVar(value="1000")
        ttk.Entry(row, textvariable=self._events_var, width=7).pack(
            side=tk.LEFT, padx=(4, 12)
        )
        ttk.Label(row, text="超时 (s):").pack(side=tk.LEFT)
        self._timeout_var = tk.StringVar(value="10.0")
        ttk.Entry(row, textvariable=self._timeout_var, width=7).pack(
            side=tk.LEFT, padx=(4, 0)
        )

        output_row = ttk.Frame(group)
        output_row.pack(fill=tk.X, pady=(6, 0))
        self._json_enabled = tk.BooleanVar(value=False)
        self._text_enabled = tk.BooleanVar(value=False)
        self._log_enabled = tk.BooleanVar(value=True)
        for text, var in (
            ("JSON", self._json_enabled),
            ("TXT", self._text_enabled),
            ("LOG", self._log_enabled),
        ):
            ttk.Checkbutton(output_row, text=text, variable=var).pack(
                side=tk.LEFT, padx=(0, 10)
            )
        watch_row = ttk.Frame(group)
        watch_row.pack(fill=tk.X, pady=(6, 0))
        self._watch_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            watch_row, text="采集时监视波形", variable=self._watch_enabled
        ).pack(side=tk.LEFT)
        ttk.Label(watch_row, text="每 N 帧:").pack(side=tk.LEFT, padx=(12, 0))
        self._watch_every_var = tk.StringVar(value="1")
        ttk.Entry(watch_row, textvariable=self._watch_every_var, width=5).pack(
            side=tk.LEFT, padx=(4, 0)
        )
        self._single_start_button = ttk.Button(
            group, text="开始单板采集", command=self._run_single
        )
        self._single_start_button.pack(anchor="w", pady=(8, 0))

        self._progress = ttk.Progressbar(group, mode="determinate", maximum=1)
        self._progress.pack(fill=tk.X, pady=(6, 0))
        self._progress_label = ttk.Label(group, text="")
        self._progress_label.pack(anchor="w")

    def _build_multi_group(self, parent) -> None:
        group = ttk.LabelFrame(parent, text="多板采集", padding=(8, 4))
        group.pack(fill=tk.X, pady=(0, 6))

        watch_row = ttk.Frame(group)
        watch_row.pack(fill=tk.X, pady=(6, 0))
        self._multi_watch_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            watch_row, text="采集时监视波形", variable=self._multi_watch_enabled
        ).pack(side=tk.LEFT)
        ttk.Label(watch_row, text="每 N 帧:").pack(side=tk.LEFT, padx=(12, 0))
        self._multi_watch_every_var = tk.StringVar(value="1")
        ttk.Entry(watch_row, textvariable=self._multi_watch_every_var, width=5).pack(
            side=tk.LEFT, padx=(4, 0)
        )

        row = ttk.Frame(group)
        row.pack(fill=tk.X)
        ttk.Label(row, text="组:").pack(side=tk.LEFT)
        self._group_var = tk.StringVar()
        self._group_combo = ttk.Combobox(
            row, textvariable=self._group_var, state="readonly", width=18
        )
        self._group_combo.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(row, text="聚合 key:").pack(side=tk.LEFT)
        self._aggregation_var = tk.StringVar(value="timestamp")
        ttk.Combobox(
            row,
            textvariable=self._aggregation_var,
            state="readonly",
            width=14,
            values=("timestamp", "event_count"),
        ).pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(row, text="匹配窗口:").pack(side=tk.LEFT)
        self._match_window_var = tk.StringVar(value="10")
        ttk.Entry(row, textvariable=self._match_window_var, width=5).pack(
            side=tk.LEFT, padx=(4, 0)
        )

        option_row = ttk.Frame(group)
        option_row.pack(fill=tk.X, pady=(6, 0))
        self._allow_no_ack = tk.BooleanVar(value=False)
        self._multi_json_enabled = tk.BooleanVar(value=False)
        self._multi_text_enabled = tk.BooleanVar(value=False)
        for text, var in (
            ("无 ack 放行", self._allow_no_ack),
            ("JSON", self._multi_json_enabled),
            ("TXT", self._multi_text_enabled),
        ):
            ttk.Checkbutton(option_row, text=text, variable=var).pack(
                side=tk.LEFT, padx=(0, 10)
            )
        self._multi_status_label = ttk.Label(option_row, text="")
        self._multi_status_label.pack(side=tk.LEFT, padx=(12, 0))
        self._multi_start_button = ttk.Button(
            group, text="开始多板采集", command=self._run_multi
        )
        self._multi_start_button.pack(anchor="w", pady=(8, 0))

    # ---------------------------------------------------------------- single

    def _run_single(self) -> None:
        if self.app.profile is None:
            self.single_result.show("请先加载 profile")
            return
        if self._single_busy:
            self.app.log("单板采集进行中")
            return
        try:
            device = self._selected("device", self._device_var)
            events = int(self._events_var.get(), 0)
            timeout_s = float(self._timeout_var.get())
        except ValueError as exc:
            self.single_result.show(f"参数错误: {exc}")
            return
        outputs = AcquireOutputsConfig(
            raw=OutputTargetConfig(enabled=True),
            json=OutputTargetConfig(enabled=self._json_enabled.get()),
            text=TextOutputConfig(enabled=self._text_enabled.get()),
            log=OutputTargetConfig(enabled=self._log_enabled.get()),
        )
        self._single_busy = True  # set before scheduling the watch poll
        watch_every: int | None = None
        watch_callback = None
        if self._watch_enabled.get():
            try:
                watch_every = int(self._watch_every_var.get())
            except ValueError as exc:
                self._single_busy = False
                self.single_result.show(f"参数错误: 每 N 帧必须是整数 ({exc})")
                return
            if watch_every < 1:
                self._single_busy = False
                self.single_result.show("参数错误: 每 N 帧需 >= 1")
                return
            self._watch_frame_queue = queue.Queue()
            watch_callback = self._watch_frame_queue.put
            self._ensure_watch_canvas(device)
            self.app.schedule(self._poll_watch_frames)

        self._single_start_button.configure(state=tk.DISABLED)
        self._progress.configure(value=0)
        self._progress_label.configure(text="连接中...")
        self._progress_queue = queue.Queue()

        def task():
            return self.acquire_service.capture_single(
                device_name=device,
                profile_path=self.app.profile_path,
                events=events,
                timeout_s=timeout_s,
                outputs=outputs,
                progress_callback=self._progress_queue.put,
                watch_every=watch_every,
                watch_frame_callback=watch_callback,
            )

        threads.run_in_background(
            fn=task,
            on_done=self._single_done,
            on_error=self._single_error,
            schedule=self.app.schedule,
        )
        self.app.schedule(self._poll_progress)

    def _poll_progress(self) -> None:
        if not self._single_busy or self._progress_queue is None:
            return
        for item in threads.drain_queue(self._progress_queue):
            self._progress.configure(maximum=item.requested_events or 1)
            self._progress.configure(value=item.captured_events)
            self._progress_label.configure(
                text=formatting.format_single_progress(item)
            )
        self.app.schedule(self._poll_progress)

    def _ensure_watch_canvas(self, device: str) -> None:
        """(Re)create the embedded waveform canvas for a capture.

        The host frame is always visible; each capture gets a fresh figure
        so the previous run's waveforms do not linger.
        """
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

        if self._watch_canvas is not None:
            self._watch_canvas.get_tk_widget().destroy()
            self._watch_canvas = None
        self._watch_device_name = device or "单板采集"
        self._watch_figure = WaveMonitorFigure(
            source_label=self._watch_device_name,
            help_text="采集开始后实时滚动（每 N 帧采样）",
            figsize=(11.0, 6.5),
        )
        self._watch_canvas = FigureCanvasTkAgg(
            self._watch_figure.figure, master=self._watch_host
        )
        self._watch_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._watch_canvas.draw()
        self.frame.bind_wheel(self._watch_canvas.get_tk_widget())

    def _teardown_watch_canvas(self) -> None:
        # Keep the canvas and last frame visible for inspection; only stop
        # delivering new frames.
        self._watch_frame_queue = None

    def _poll_watch_frames(self) -> None:
        if (
            not self._single_busy
            or self._watch_frame_queue is None
            or self._watch_figure is None
            or self._watch_canvas is None
        ):
            return
        if not self.app.root.winfo_exists():
            return
        for packet in threads.drain_queue(self._watch_frame_queue):
            try:
                decoded = decode_tcp_sent_packet(
                    packet, source_file=Path("gui_watch.bin")
                )
            except Exception:  # noqa: BLE001 - partial frames are skipped
                continue
            frame = WaveMonitorFrame(
                device_name=self._watch_device_name,
                event_count=decoded.event_count,
                timestamp=decoded.timestamp,
                hit_mask=decoded.hit_mask,
                send_mode=decoded.send_mode,
                channels=[
                    list(channel) if channel is not None else []
                    for channel in decoded.channels
                ],
            )
            self._watch_figure.update(frame, WaveMonitorRunState.RUN)
            self._watch_canvas.draw_idle()
        self.app.schedule(self._poll_watch_frames)

    def _single_done(self, result) -> None:
        self._single_busy = False
        self._single_start_button.configure(state=tk.NORMAL)
        self._progress_queue = None
        self._teardown_watch_canvas()
        self.single_result.show(formatting.format_single_acquire_result(result))
        self._progress_label.configure(
            text=f"完成: {result.captured_events} 个事件"
        )
        self.app.log(f"单板采集完成: {result.run_output_dir}")

    def _single_error(self, exc: BaseException) -> None:
        self._single_busy = False
        self._single_start_button.configure(state=tk.NORMAL)
        self._progress_queue = None
        self._teardown_watch_canvas()
        self.single_result.show(f"错误: {exc}")
        self._progress_label.configure(text="失败")
        self.app.log(f"单板采集失败: {exc}")

    # ---------------------------------------------------------------- multi

    def _ensure_multi_watch_canvas(self) -> None:
        """(Re)create the embedded multi-board waveform canvas.

        The host frame is always visible; each capture gets a fresh figure.
        """
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

        if self._multi_watch_canvas is not None:
            self._multi_watch_canvas.get_tk_widget().destroy()
            self._multi_watch_canvas = None
        self._multi_watch_figure = WaveMonitorFigure(
            source_label=f"multi-watch:{self._multi_group_label or '未开始'}",
            help_text="采集开始后实时滚动（板/事件可切换）",
            figsize=(11.0, 6.5),
        )
        self._multi_watch_canvas = FigureCanvasTkAgg(
            self._multi_watch_figure.figure, master=self._multi_watch_host
        )
        self._multi_watch_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._multi_watch_canvas.draw()
        self.frame.bind_wheel(self._multi_watch_canvas.get_tk_widget())

    def _teardown_multi_watch_canvas(self) -> None:
        # Keep the canvas and last frame visible for inspection; only stop
        # delivering new frames.
        self._multi_watch_queue = None
        self._multi_viewer_state = None

    def _render_multi_selected(self) -> None:
        viewer_state = self._multi_viewer_state
        if viewer_state is None or self._multi_watch_figure is None:
            return
        board_name = self._multi_board_names[viewer_state.selected_board_index]
        current_frame = _get_selected_multi_board_frame(viewer_state)
        title = _format_multi_board_title(
            group_label=self._multi_group_label,
            board_name=board_name,
            board_index=viewer_state.selected_board_index,
            board_count=len(self._multi_board_names),
            run_state=viewer_state.run_state,
            selected_aggregate_event_id=viewer_state.selected_aggregate_event_id,
            aggregate_timestamp=_get_selected_multi_board_aggregate_timestamp(
                viewer_state
            ),
            frame=current_frame,
        )
        if current_frame is None:
            self._multi_watch_figure.set_custom_title(title)
        else:
            self._multi_watch_figure.update_custom(current_frame, title)
        self._multi_watch_status_label.configure(
            text=f"事件 #{viewer_state.selected_aggregate_event_id}"
            if viewer_state.selected_aggregate_event_id is not None
            else ""
        )

    def _poll_multi_watch(self) -> None:
        if (
            not self._multi_busy
            or self._multi_watch_queue is None
            or self._multi_watch_figure is None
            or self._multi_watch_canvas is None
        ):
            return
        if not self.app.root.winfo_exists():
            return
        for item in threads.drain_queue(self._multi_watch_queue):
            try:
                decoded = decode_tcp_sent_packet(
                    item.packet, source_file=Path("gui_multi_watch.bin")
                )
            except Exception:  # noqa: BLE001 - partial frames are skipped
                continue
            frame = WaveMonitorFrame(
                device_name=item.board_name,
                event_count=decoded.event_count,
                timestamp=decoded.timestamp,
                hit_mask=decoded.hit_mask,
                send_mode=decoded.send_mode,
                channels=[
                    list(channel) if channel is not None else []
                    for channel in decoded.channels
                ],
            )
            update = MultiBoardWaveUpdate(
                board_name=item.board_name,
                board_index=item.board_index,
                aggregate_event_id=item.aggregate_event_id,
                aggregate_timestamp=item.aggregate_timestamp,
                board_event_count=item.board_event_count,
                board_timestamp=item.board_timestamp,
                frame=frame,
            )
            step_result = _advance_multi_board_viewer_state(
                viewer_state=self._multi_viewer_state,
                update=update,
                history_limit=DEFAULT_MULTI_BOARD_HISTORY_LIMIT,
            )
            self._multi_viewer_state = step_result.viewer_state
            if step_result.should_render:
                self._render_multi_selected()
        self.app.schedule(self._poll_multi_watch)

    def _on_multi_board_select(self, _event=None) -> None:
        if self._multi_viewer_state is None:
            return
        try:
            index = self._multi_board_names.index(self._multi_board_var.get())
        except ValueError:
            return
        self._multi_viewer_state.selected_board_index = index
        _jump_to_latest_multi_board_event(self._multi_viewer_state)
        self._render_multi_selected()

    def _multi_prev_event(self) -> None:
        if self._multi_viewer_state is None:
            return
        if _can_navigate_multi_board_history(
            self._multi_viewer_state
        ) and _select_previous_multi_board_event(self._multi_viewer_state):
            self._render_multi_selected()

    def _multi_next_event(self) -> None:
        if self._multi_viewer_state is None:
            return
        if _can_navigate_multi_board_history(
            self._multi_viewer_state
        ) and _select_next_multi_board_event(self._multi_viewer_state):
            self._render_multi_selected()

    def _multi_latest_event(self) -> None:
        if self._multi_viewer_state is None:
            return
        _jump_to_latest_multi_board_event(self._multi_viewer_state)
        self._render_multi_selected()

    def _run_multi(self) -> None:
        if self.app.profile is None:
            self.multi_result.show("请先加载 profile")
            return
        if self._multi_busy:
            self.app.log("多板采集进行中")
            return
        try:
            group = self._selected("group", self._group_var)
            match_window = int(self._match_window_var.get(), 0)
        except ValueError as exc:
            self.multi_result.show(f"参数错误: {exc}")
            return
        outputs = AcquireOutputsConfig(
            raw=OutputTargetConfig(enabled=True),
            json=OutputTargetConfig(enabled=self._multi_json_enabled.get()),
            text=TextOutputConfig(enabled=self._multi_text_enabled.get()),
            log=OutputTargetConfig(enabled=True),
        )
        self._multi_busy = True  # set before scheduling the watch poll
        watch_every: int | None = None
        watch_callback = None
        if self._multi_watch_enabled.get():
            try:
                watch_every = int(self._multi_watch_every_var.get())
            except ValueError as exc:
                self._multi_busy = False
                self.multi_result.show(f"参数错误: 每 N 帧必须是整数 ({exc})")
                return
            if watch_every < 1:
                self._multi_busy = False
                self.multi_result.show("参数错误: 每 N 帧需 >= 1")
                return
            group_cfg = self.app.profile.groups[group]
            self._multi_board_names = [
                self.app.profile.devices[device_name].name
                for device_name in group_cfg.devices
            ]
            self._multi_group_label = group
            self._multi_viewer_state = MultiBoardViewerState()
            self._multi_board_combo.configure(values=self._multi_board_names)
            if self._multi_board_names:
                self._multi_board_var.set(self._multi_board_names[0])
            self._multi_watch_queue = queue.Queue()
            watch_callback = self._multi_watch_queue.put
            self._ensure_multi_watch_canvas()
            self.app.schedule(self._poll_multi_watch)

        self._multi_start_button.configure(state=tk.DISABLED)
        self._multi_status_label.configure(text="● 运行中...")
        self.multi_result.show("运行中...")
        # All form values are read on the GUI thread (tkinter variables are
        # not thread-safe); the task closure only uses captured values.
        aggregation_key = self._aggregation_var.get()
        allow_start_without_ack = self._allow_no_ack.get()

        def task():
            return self.acquire_service.capture_multi(
                group_name=group,
                profile_path=self.app.profile_path,

                outputs=outputs,
                aggregation_key=aggregation_key,
                timestamp_match_window_ticks=match_window,
                allow_start_without_ack=allow_start_without_ack,
                watch_waveforms=watch_every is not None,
                watch_every=watch_every,
                watch_update_callback=watch_callback,
            )

        threads.run_in_background(
            fn=task,
            on_done=self._multi_done,
            on_error=self._multi_error,
            schedule=self.app.schedule,
        )

    def _multi_done(self, result) -> None:
        self._multi_busy = False
        self._multi_start_button.configure(state=tk.NORMAL)
        self._multi_status_label.configure(text="")
        self._teardown_multi_watch_canvas()
        self.multi_result.show(formatting.format_multi_acquire_result(result))
        self.app.log(f"多板采集完成: {result.run_output_dir}")

    def _multi_error(self, exc: BaseException) -> None:
        self._multi_busy = False
        self._multi_start_button.configure(state=tk.NORMAL)
        self._multi_status_label.configure(text="失败")
        self._teardown_multi_watch_canvas()
        self.multi_result.show(f"错误: {exc}")
        self.app.log(f"多板采集失败: {exc}")

    # ---------------------------------------------------------------- helpers

    def _selected(self, label: str, var: tk.StringVar) -> str:
        value = var.get()
        if not value:
            raise ValueError(f"请选择{label}")
        return value

    def refresh(self, profile) -> None:
        devices = sorted(profile.devices)
        self._device_combo.configure(values=devices)
        if devices and self._device_var.get() not in devices:
            self._device_var.set(devices[0])
        groups = sorted(profile.groups)
        self._group_combo.configure(values=groups)
        if groups and self._group_var.get() not in groups:
            self._group_var.set(groups[0])

    def shutdown(self) -> None:
        self._teardown_watch_canvas()
        self._teardown_multi_watch_canvas()
