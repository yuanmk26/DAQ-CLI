"""监视 tab：live/demo/replay 波形监视（matplotlib 嵌入 tkinter）。

Reuses the pure viewer layer from ``wave_monitor_viewer`` (WaveMonitorFigure,
_advance_loop_state, _drain_latest_frame) driven by a ``root.after`` poll
loop instead of the blocking ``run_wave_monitor_viewer`` entry point.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from daq_cli.application.monitor_service import MonitorService
from daq_cli.presentation.gui import threads
from daq_cli.presentation.gui.widgets import ResultArea
from daq_cli.presentation.wave_monitor_viewer import (
    WaveMonitorFigure,
    WaveMonitorLoopState,
    WaveMonitorRunState,
    _advance_loop_state,
    _drain_latest_frame,
)

_SOURCES = ("live", "demo", "replay")


class MonitorTab:
    def __init__(self, app, notebook) -> None:
        self.app = app
        self.frame = ttk.Frame(notebook, padding=8)
        self.monitor_service = MonitorService()
        self._context = None  # active monitor session context manager
        self._session = None  # WaveMonitorSession
        self._figure: WaveMonitorFigure | None = None
        self._canvas = None  # FigureCanvasTkAgg
        self._loop_state = None
        self._run_state = WaveMonitorRunState.RUN

        self._build_source_row()
        self._build_canvas_area()
        self._build_control_row()
        self.result = ResultArea(self.frame, text="状态")
        self.result.pack(fill=tk.X)

    # ---------------------------------------------------------------- layout

    def _build_source_row(self) -> None:
        row = ttk.Frame(self.frame)
        row.pack(fill=tk.X)
        ttk.Label(row, text="设备:").pack(side=tk.LEFT)
        self._device_var = tk.StringVar()
        self._device_combo = ttk.Combobox(
            row, textvariable=self._device_var, state="readonly", width=18
        )
        self._device_combo.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(row, text="源:").pack(side=tk.LEFT)
        self._source_var = tk.StringVar(value="live")
        ttk.Combobox(
            row,
            textvariable=self._source_var,
            state="readonly",
            width=10,
            values=_SOURCES,
        ).pack(side=tk.LEFT, padx=(4, 12))
        self._replay_path_var = tk.StringVar(value="")
        self._replay_entry = ttk.Entry(row, textvariable=self._replay_path_var, width=28)
        self._replay_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(row, text="选择文件", command=self._choose_replay).pack(side=tk.LEFT)
        self._start_button = ttk.Button(row, text="启动监视", command=self._start)
        self._start_button.pack(side=tk.LEFT, padx=(8, 0))
        self._stop_button = ttk.Button(
            row, text="停止监视", command=self._stop, state=tk.DISABLED
        )
        self._stop_button.pack(side=tk.LEFT, padx=(4, 0))

    def _build_canvas_area(self) -> None:
        self._canvas_frame = ttk.Frame(self.frame)
        self._canvas_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 4))

    def _build_control_row(self) -> None:
        row = ttk.Frame(self.frame)
        row.pack(fill=tk.X)
        for text, callback in (
            ("RUN", self._set_run),
            ("STOP", self._set_stop),
            ("SINGLE", self._set_single),
        ):
            ttk.Button(row, text=text, command=callback).pack(
                side=tk.LEFT, padx=(0, 6)
            )
        self._run_state_label = ttk.Label(row, text="RUN")
        self._run_state_label.pack(side=tk.LEFT, padx=(12, 0))

    # ---------------------------------------------------------------- actions

    def _choose_replay(self) -> None:
        chosen = filedialog.askopenfilename(title="选择 replay dump 文件")
        if chosen:
            self._replay_path_var.set(chosen)

    def _start(self) -> None:
        if self._session is not None:
            self.app.log("监视已在进行中")
            return
        if self.app.profile is None:
            self.result.show("请先加载 profile")
            return
        source = self._source_var.get()
        try:
            if source == "live":
                device = self._selected_device()
                context = self.monitor_service.open_live_wave_session(
                    device_name=device, profile_path=self.app.profile_path
                )
            elif source == "demo":
                device = self._device_var.get() or "demo"
                context = self.monitor_service.open_demo_wave_session(device_name=device)
            else:  # replay
                device = self._device_var.get() or "replay"
                replay_path = Path(self._replay_path_var.get())
                if not replay_path.is_file():
                    raise ValueError(f"replay 文件不存在: {replay_path}")
                context = self.monitor_service.open_replay_wave_session(
                    device_name=device, replay_path=replay_path
                )
        except Exception as exc:  # noqa: BLE001 - surface to the user
            self.result.show(f"启动失败: {exc}")
            self.app.log(f"监视启动失败: {exc}")
            return

        self._context = context
        self._session = context.__enter__()
        self._run_state = WaveMonitorRunState.RUN
        self._loop_state = WaveMonitorLoopState()
        self._figure = WaveMonitorFigure(
            source_label=self._session.source_label,
            help_text="RUN/STOP/SINGLE 按钮控制显示",
        )
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

        self._canvas = FigureCanvasTkAgg(self._figure.figure, master=self._canvas_frame)
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._canvas.draw()
        self._start_button.configure(state=tk.DISABLED)
        self._stop_button.configure(state=tk.NORMAL)
        self.result.show(f"监视已启动: {self._session.source_label}")
        self.app.log(f"监视启动: {self._session.source_label}")
        self.app.schedule(self._poll_frames)

    def _poll_frames(self) -> None:
        if self._session is None or self._figure is None or self._canvas is None:
            return
        latest_frame = _drain_latest_frame(self._session.frame_queue)
        step_result = _advance_loop_state(
            loop_state=self._loop_state, latest_frame=latest_frame
        )
        self._loop_state = step_result.loop_state
        if step_result.should_render and self._loop_state.last_frame is not None:
            self._figure.update(
                frame=self._loop_state.last_frame,
                run_state=self._loop_state.run_state,
            )
            self._canvas.draw_idle()
        self.app.schedule(self._poll_frames)

    def _stop(self) -> None:
        if self._context is None:
            return
        try:
            self._context.__exit__(None, None, None)
        except Exception as exc:  # noqa: BLE001 - send_mode restore is best effort
            self.app.log(f"监视退出异常: {exc}")
        finally:
            self._context = None
            self._session = None
        if self._canvas is not None:
            self._canvas.get_tk_widget().destroy()
            self._canvas = None
        self._figure = None
        self._start_button.configure(state=tk.NORMAL)
        self._stop_button.configure(state=tk.DISABLED)
        self._run_state_label.configure(text="RUN")
        self.result.show("监视已停止")

    def _apply_run_state(self, state: WaveMonitorRunState) -> None:
        self._run_state = state
        self._run_state_label.configure(text=state.value)
        if self._loop_state is not None:
            self._loop_state.run_state = state
            if self._figure is not None:
                self._figure.set_state(
                    run_state=state, frame=self._loop_state.last_frame
                )
                if self._canvas is not None:
                    self._canvas.draw_idle()

    def _set_run(self) -> None:
        self._apply_run_state(WaveMonitorRunState.RUN)

    def _set_stop(self) -> None:
        self._apply_run_state(WaveMonitorRunState.STOP)

    def _set_single(self) -> None:
        self._apply_run_state(WaveMonitorRunState.SINGLE_ARMED)

    # ---------------------------------------------------------------- helpers

    def _selected_device(self) -> str:
        value = self._device_var.get()
        if not value:
            raise ValueError("请选择设备")
        return value

    def refresh(self, profile) -> None:
        devices = sorted(profile.devices)
        self._device_combo.configure(values=devices)
        if devices and self._device_var.get() not in devices:
            self._device_var.set(devices[0])

    def shutdown(self) -> None:
        self._stop()
