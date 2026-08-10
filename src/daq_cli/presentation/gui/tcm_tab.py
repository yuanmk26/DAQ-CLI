"""TCM tab：TCM 板触发联动配置与状态。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from daq_cli.application.tcm_service import TcmService
from daq_cli.presentation.gui import formatting, threads
from daq_cli.presentation.gui.widgets import ResultArea


class TcmTab:
    def __init__(self, app, notebook) -> None:
        self.app = app
        self.frame = ttk.Frame(notebook, padding=8)
        self.tcm_service = TcmService()
        self._busy = False

        row = ttk.Frame(self.frame)
        row.pack(fill=tk.X)
        ttk.Label(row, text="TCM:").pack(side=tk.LEFT)
        self._tcm_var = tk.StringVar()
        self._tcm_combo = ttk.Combobox(
            row, textvariable=self._tcm_var, state="readonly", width=18
        )
        self._tcm_combo.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Button(row, text="show 配置与状态", command=self._run_show).pack(
            side=tk.LEFT
        )

        form = ttk.LabelFrame(self.frame, text="配置 (0x20..0x23)", padding=(8, 4))
        form.pack(fill=tk.X, pady=(8, 0))

        fields = (
            ("mask (8 位)", "mask_var", "0x01"),
            ("width (20M 周期)", "width_var", "32"),
            ("debounce (20M 周期)", "debounce_var", "20"),
        )
        self._form_vars: dict[str, tk.StringVar] = {}
        for index, (label, key, default) in enumerate(fields):
            frow = ttk.Frame(form)
            frow.pack(fill=tk.X, pady=1)
            ttk.Label(frow, text=label, width=18).pack(side=tk.LEFT)
            var = tk.StringVar(value=default)
            self._form_vars[key] = var
            ttk.Entry(frow, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        option_row = ttk.Frame(form)
        option_row.pack(fill=tk.X, pady=(6, 0))
        self._enable_var = tk.BooleanVar(value=True)
        self._clear_sticky_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(option_row, text="使能", variable=self._enable_var).pack(
            side=tk.LEFT, padx=(0, 12)
        )
        ttk.Checkbutton(option_row, text="清 sticky", variable=self._clear_sticky_var).pack(
            side=tk.LEFT
        )
        ttk.Button(form, text="配置", command=self._run_config).pack(
            anchor="w", pady=(8, 0)
        )

        self.result = ResultArea(self.frame, text="结果")
        self.result.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

    # ---------------------------------------------------------------- actions

    def _selected_tcm(self) -> str:
        if self.app.profile is None:
            raise ValueError("请先加载 profile")
        value = self._tcm_var.get()
        if not value:
            raise ValueError("请选择 TCM")
        return value

    def _run_task(self, fn, on_result) -> None:
        if self._busy:
            self.app.log("TCM tab 有操作进行中，请等待完成")
            return
        self._busy = True
        self.result.show("运行中...")

        def on_error(exc: BaseException) -> None:
            self._busy = False
            self.result.show(f"错误: {exc}")
            self.app.log(f"TCM 操作失败: {exc}")

        threads.run_in_background(
            fn=fn,
            on_done=lambda result: self._finish(result, on_result),
            on_error=on_error,
            schedule=self.app.schedule,
        )

    def _finish(self, result, on_result) -> None:
        self._busy = False
        on_result(result)

    def _run_show(self) -> None:
        def task():
            return self.tcm_service.read_trigger_config(
                tcm_name=self._selected_tcm(), profile_path=self.app.profile_path
            )

        def render(result) -> None:
            self.result.show(
                formatting.format_tcm_trigger_read(
                    result.tcm,
                    source_profile=result.source_profile,
                    enable=result.enable,
                    mask=result.mask,
                    pulse_width=result.pulse_width,
                    debounce=result.debounce,
                    trig_sticky=result.trig_sticky,
                    pending=result.pending,
                    wide_pulse_active=result.wide_pulse_active,
                    last_trigger_channels=result.last_trigger_channels,
                )
            )
            if result.trig_sticky:
                self.result.append("提示: trig_sticky 已置位（上次触发已送达）")

        self._run_task(task, render)

    def _run_config(self) -> None:
        def task():
            result = self.tcm_service.configure_trigger(
                tcm_name=self._selected_tcm(),
                profile_path=self.app.profile_path,
                enable=self._enable_var.get(),
                mask=int(self._form_vars["mask_var"].get(), 0),
                pulse_width=int(self._form_vars["width_var"].get(), 0),
                debounce=int(self._form_vars["debounce_var"].get(), 0),
            )
            if self._clear_sticky_var.get():
                self.tcm_service.clear_trigger_sticky(
                    tcm_name=self._selected_tcm(), profile_path=self.app.profile_path
                )
            return result

        def render(result) -> None:
            self.result.show(
                formatting.format_tcm_trigger_read(
                    result.tcm,
                    source_profile=result.source_profile,
                    enable=result.enable,
                    mask=result.mask,
                    pulse_width=result.pulse_width,
                    debounce=result.debounce,
                    trig_sticky=False,
                    pending=False,
                    wide_pulse_active=False,
                    last_trigger_channels=0,
                ).replace("TCM Trigger Config:", "TCM Trigger Config Written:")
            )

        self._run_task(task, render)

    # ---------------------------------------------------------------- lifecycle

    def refresh(self, profile) -> None:
        tcm_names = sorted(profile.tcm)
        self._tcm_combo.configure(values=tcm_names)
        if tcm_names and self._tcm_var.get() not in tcm_names:
            self._tcm_var.set(tcm_names[0])

    def shutdown(self) -> None:
        pass
