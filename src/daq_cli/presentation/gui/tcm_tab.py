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

        coinc = ttk.LabelFrame(self.frame, text="符合触发 (v3, 0x27..0x2F)", padding=(8, 4))
        coinc.pack(fill=tk.X, pady=(8, 0))
        row = ttk.Frame(coinc)
        row.pack(fill=tk.X)
        self._coinc_enable_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="符合模式", variable=self._coinc_enable_var).pack(
            side=tk.LEFT
        )
        ttk.Label(row, text="组数(0=默认2):").pack(side=tk.LEFT, padx=(12, 0))
        self._coinc_groups_var = tk.StringVar(value="0")
        ttk.Entry(row, textvariable=self._coinc_groups_var, width=3).pack(
            side=tk.LEFT, padx=(4, 12)
        )
        ttk.Label(row, text="窗口(20M周期, 0=默认4):").pack(side=tk.LEFT)
        self._coinc_window_var = tk.StringVar(value="0")
        ttk.Entry(row, textvariable=self._coinc_window_var, width=4).pack(
            side=tk.LEFT, padx=(4, 0)
        )
        grid = ttk.Frame(coinc)
        grid.pack(fill=tk.X, pady=(6, 0))
        self._grp_mask_vars: list[tk.StringVar] = []
        self._grp_n_vars: list[tk.StringVar] = []
        for index in range(4):
            ttk.Label(grid, text=f"组{index} mask:").grid(
                row=index // 2, column=(index % 2) * 3, sticky="w", padx=(0, 4), pady=2
            )
            mask_var = tk.StringVar(value="0x00")
            self._grp_mask_vars.append(mask_var)
            ttk.Entry(grid, textvariable=mask_var, width=6).grid(
                row=index // 2, column=(index % 2) * 3 + 1, sticky="w", pady=2
            )
            ttk.Label(grid, text="N:").grid(
                row=index // 2, column=(index % 2) * 3 + 1, sticky="e", padx=(52, 0)
            )
            n_var = tk.StringVar(value="0")
            self._grp_n_vars.append(n_var)
            ttk.Entry(grid, textvariable=n_var, width=3).grid(
                row=index // 2, column=(index % 2) * 3 + 2, sticky="w", padx=(4, 12), pady=2
            )
        ttk.Label(
            coinc,
            text="触发 = AND_i (组 i 内过阈路数 ≥ N_i)。例：(板A∨板B)∧(板C∨板D) → "
            "组0 mask=0x03、组1 mask=0x0C、组数=2。",
            foreground="#666666",
        ).pack(anchor="w", pady=(4, 0))

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
        tcm_name = self._selected_tcm()  # read on the GUI thread

        def task():
            return self.tcm_service.read_trigger_config(
                tcm_name=tcm_name, profile_path=self.app.profile_path
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
                    coincidence_enabled=result.coincidence_enabled,
                    grp_count=result.grp_count,
                    coinc_window=result.coinc_window,
                    coinc_timeout_sticky=result.coinc_timeout_sticky,
                    collected_count=result.collected_count,
                    collecting=result.collecting,
                    grp_ok=result.grp_ok,
                    group_masks=result.group_masks,
                    group_n=result.group_n,
                )
            )
            if result.trig_sticky:
                self.result.append("提示: trig_sticky 已置位（上次触发已送达）")
            if result.coinc_timeout_sticky:
                self.result.append("提示: 符合窗口超时丢弃已发生（单组/窗口过短）")

        self._run_task(task, render)

    def _run_config(self) -> None:
        tcm_name = self._selected_tcm()  # read on the GUI thread
        enable = self._enable_var.get()
        mask = formatting.parse_int_field(self._form_vars["mask_var"].get(), "mask")
        pulse_width = formatting.parse_int_field(self._form_vars["width_var"].get(), "width")
        debounce = formatting.parse_int_field(self._form_vars["debounce_var"].get(), "debounce")
        clear_sticky = self._clear_sticky_var.get()
        coincidence_enabled = self._coinc_enable_var.get()
        grp_count = formatting.parse_int_field(self._coinc_groups_var.get(), "组数")
        coinc_window = formatting.parse_int_field(self._coinc_window_var.get(), "窗口")
        group_masks = tuple(
            formatting.parse_int_field(var.get(), f"组{index} mask")
            for index, var in enumerate(self._grp_mask_vars)
        )
        group_n = tuple(
            formatting.parse_int_field(var.get(), f"组{index} N")
            for index, var in enumerate(self._grp_n_vars)
        )

        def task():
            result = self.tcm_service.configure_trigger(
                tcm_name=tcm_name,
                profile_path=self.app.profile_path,
                enable=enable,
                mask=mask,
                pulse_width=pulse_width,
                debounce=debounce,
                coincidence_enabled=coincidence_enabled,
                grp_count=grp_count,
                coinc_window=coinc_window,
                group_masks=group_masks,
                group_n=group_n,
            )
            if clear_sticky:
                self.tcm_service.clear_trigger_sticky(
                    tcm_name=tcm_name, profile_path=self.app.profile_path
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
                    coincidence_enabled=result.coincidence_enabled,
                    grp_count=result.grp_count,
                    coinc_window=result.coinc_window,
                    group_masks=result.group_masks,
                    group_n=result.group_n,
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
