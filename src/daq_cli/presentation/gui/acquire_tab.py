"""采集 tab：单板/多板采集控制与进度。"""

from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk

from daq_cli.application.acquire_service import AcquireService
from daq_cli.application.output_config import (
    AcquireOutputsConfig,
    OutputTargetConfig,
    TextOutputConfig,
)
from daq_cli.presentation.gui import formatting, threads
from daq_cli.presentation.gui.widgets import ResultArea


class AcquireTab:
    def __init__(self, app, notebook) -> None:
        self.app = app
        self.frame = ttk.Frame(notebook, padding=8)
        self.acquire_service = AcquireService()
        self._single_busy = False
        self._multi_busy = False
        self._progress_queue: queue.Queue[object] | None = None

        self._build_single_group()
        self._build_multi_group()
        self.result = ResultArea(self.frame, text="结果")
        self.result.pack(fill=tk.BOTH, expand=True)

    # ---------------------------------------------------------------- forms

    def _build_single_group(self) -> None:
        group = ttk.LabelFrame(self.frame, text="单板采集", padding=(8, 4))
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
        self._single_start_button = ttk.Button(
            group, text="开始单板采集", command=self._run_single
        )
        self._single_start_button.pack(anchor="w", pady=(8, 0))

        self._progress = ttk.Progressbar(group, mode="determinate", maximum=1)
        self._progress.pack(fill=tk.X, pady=(6, 0))
        self._progress_label = ttk.Label(group, text="")
        self._progress_label.pack(anchor="w")

    def _build_multi_group(self) -> None:
        group = ttk.LabelFrame(self.frame, text="多板采集", padding=(8, 4))
        group.pack(fill=tk.X, pady=(0, 6))

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
            self.result.show("请先加载 profile")
            return
        if self._single_busy:
            self.app.log("单板采集进行中")
            return
        try:
            device = self._selected("device", self._device_var)
            events = int(self._events_var.get(), 0)
            timeout_s = float(self._timeout_var.get())
        except ValueError as exc:
            self.result.show(f"参数错误: {exc}")
            return
        outputs = AcquireOutputsConfig(
            raw=OutputTargetConfig(enabled=True),
            json=OutputTargetConfig(enabled=self._json_enabled.get()),
            text=TextOutputConfig(enabled=self._text_enabled.get()),
            log=OutputTargetConfig(enabled=self._log_enabled.get()),
        )
        self._single_busy = True
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

    def _single_done(self, result) -> None:
        self._single_busy = False
        self._single_start_button.configure(state=tk.NORMAL)
        self._progress_queue = None
        self.result.show(formatting.format_single_acquire_result(result))
        self._progress_label.configure(
            text=f"完成: {result.captured_events} 个事件"
        )
        self.app.log(f"单板采集完成: {result.run_output_dir}")

    def _single_error(self, exc: BaseException) -> None:
        self._single_busy = False
        self._single_start_button.configure(state=tk.NORMAL)
        self._progress_queue = None
        self.result.show(f"错误: {exc}")
        self._progress_label.configure(text="失败")
        self.app.log(f"单板采集失败: {exc}")

    # ---------------------------------------------------------------- multi

    def _run_multi(self) -> None:
        if self.app.profile is None:
            self.result.show("请先加载 profile")
            return
        if self._multi_busy:
            self.app.log("多板采集进行中")
            return
        try:
            group = self._selected("group", self._group_var)
            match_window = int(self._match_window_var.get(), 0)
        except ValueError as exc:
            self.result.show(f"参数错误: {exc}")
            return
        outputs = AcquireOutputsConfig(
            raw=OutputTargetConfig(enabled=True),
            json=OutputTargetConfig(enabled=self._multi_json_enabled.get()),
            text=TextOutputConfig(enabled=self._multi_text_enabled.get()),
            log=OutputTargetConfig(enabled=True),
        )
        self._multi_busy = True
        self._multi_start_button.configure(state=tk.DISABLED)
        self._multi_status_label.configure(text="● 运行中...")
        self.result.show("运行中...")

        def task():
            return self.acquire_service.capture_multi(
                group_name=group,
                profile_path=self.app.profile_path,
                outputs=outputs,
                aggregation_key=self._aggregation_var.get(),
                timestamp_match_window_ticks=match_window,
                allow_start_without_ack=self._allow_no_ack.get(),
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
        self.result.show(formatting.format_multi_acquire_result(result))
        self.app.log(f"多板采集完成: {result.run_output_dir}")

    def _multi_error(self, exc: BaseException) -> None:
        self._multi_busy = False
        self._multi_start_button.configure(state=tk.NORMAL)
        self._multi_status_label.configure(text="失败")
        self.result.show(f"错误: {exc}")
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
        pass
