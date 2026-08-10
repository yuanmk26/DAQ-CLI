"""板卡 tab：info / sysmon / config / 各 show / tcm-link / reg-read。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from daq_cli.application.board_service import BoardService
from daq_cli.application.telemetry_service import TelemetryService
from daq_cli.presentation.gui import formatting, threads
from daq_cli.presentation.gui.widgets import ResultArea


class BoardTab:
    def __init__(self, app, notebook) -> None:
        self.app = app
        self.frame = ttk.Frame(notebook, padding=8)
        self.board_service = BoardService()
        self.telemetry_service = TelemetryService()
        self._busy = False

        row = ttk.Frame(self.frame)
        row.pack(fill=tk.X)
        ttk.Label(row, text="设备:").pack(side=tk.LEFT)
        self._device_var = tk.StringVar()
        self._device_combo = ttk.Combobox(
            row, textvariable=self._device_var, state="readonly", width=24
        )
        self._device_combo.pack(side=tk.LEFT, padx=(4, 0))

        action_row = ttk.Frame(self.frame)
        action_row.pack(fill=tk.X, pady=(8, 4))
        for label, callback in (
            ("info", self._run_info),
            ("sysmon", self._run_sysmon),
            ("trigger-show", self._run_trigger_show),
            ("tcp-mode2-show", self._run_tcp_mode2_show),
            ("config-show", self._run_config_show),
            ("tcm-link-show", self._run_tcm_link_show),
        ):
            ttk.Button(action_row, text=label, command=callback).pack(
                side=tk.LEFT, padx=(0, 6)
            )
        self._action_buttons = action_row.winfo_children()

        body = ttk.Frame(self.frame)
        body.pack(fill=tk.BOTH, expand=True, pady=(4, 4))
        self._build_config_form(body)
        self._build_tcm_link_form(body)
        self._build_reg_read_row(body)

        self.result = ResultArea(self.frame, text="结果")
        self.result.pack(fill=tk.BOTH, expand=True)

    # ---------------------------------------------------------------- forms

    def _build_config_form(self, parent) -> None:
        group = ttk.LabelFrame(parent, text="板卡配置", padding=(8, 4))
        group.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        self._adc_enabled = tk.BooleanVar(value=False)
        self._clock_enabled = tk.BooleanVar(value=False)
        self._trigger_enabled = tk.BooleanVar(value=True)
        self._tcp_mode2_enabled = tk.BooleanVar(value=True)
        step_row = ttk.Frame(group)
        step_row.pack(fill=tk.X)
        for text, var in (
            ("ADC", self._adc_enabled),
            ("时钟", self._clock_enabled),
            ("触发", self._trigger_enabled),
            ("TCP-mode2", self._tcp_mode2_enabled),
        ):
            ttk.Checkbutton(step_row, text=text, variable=var).pack(
                side=tk.LEFT, padx=(0, 10)
            )

        self._trigger_mode_var = tk.StringVar(value="1")
        self._trigger_position_var = tk.StringVar(value="40")
        param_grid = ttk.Frame(group)
        param_grid.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(param_grid, text="trigger-mode:").grid(row=0, column=0, sticky="w")
        ttk.Entry(param_grid, textvariable=self._trigger_mode_var, width=6).grid(
            row=0, column=1, sticky="w", padx=(4, 12)
        )
        ttk.Label(param_grid, text="trigger-position:").grid(row=0, column=2, sticky="w")
        ttk.Entry(param_grid, textvariable=self._trigger_position_var, width=6).grid(
            row=0, column=3, sticky="w", padx=(4, 0)
        )

        ttk.Label(group, text="阈值 (4 个):").pack(anchor="w", pady=(6, 0))
        threshold_row = ttk.Frame(group)
        threshold_row.pack(fill=tk.X)
        self._threshold_vars = [
            tk.StringVar(value=value)
            for value in ("1950", "2400", "2300", "2300")
        ]
        for index, var in enumerate(self._threshold_vars):
            ttk.Entry(threshold_row, textvariable=var, width=6).pack(
                side=tk.LEFT, padx=(0, 6)
            )

        self._timestamp_clean_var = tk.BooleanVar(value=False)
        self._ext_trigger_var = tk.BooleanVar(value=False)
        flag_row = ttk.Frame(group)
        flag_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Checkbutton(
            flag_row, text="时间戳清零", variable=self._timestamp_clean_var
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(
            flag_row, text="外部触发", variable=self._ext_trigger_var
        ).pack(side=tk.LEFT)

        send_mode_row = ttk.Frame(group)
        send_mode_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(send_mode_row, text="send-mode (留空不改):").pack(side=tk.LEFT)
        self._send_mode_var = tk.StringVar(value="")
        ttk.Entry(send_mode_row, textvariable=self._send_mode_var, width=6).pack(
            side=tk.LEFT, padx=(4, 0)
        )

        ttk.Button(group, text="配置板卡", command=self._run_board_config).pack(
            anchor="w", pady=(8, 0)
        )

    def _build_tcm_link_form(self, parent) -> None:
        group = ttk.LabelFrame(parent, text="TCM 触发链路 (0x45..0x6C)", padding=(8, 4))
        group.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        fields = (
            ("mask (必填)", "mask_var", "0x0003"),
            ("polarity", "polarity_var", "0x0000"),
            ("thr (1 或 16 值)", "thr_var", "2700"),
            ("debounce (5ns)", "debounce_var", "200"),
            ("width (5ns)", "width_var", "20"),
        )
        self._tcm_vars: dict[str, tk.StringVar] = {}
        for index, (label, key, default) in enumerate(fields):
            row = ttk.Frame(group)
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=label, width=16).pack(side=tk.LEFT)
            var = tk.StringVar(value=default)
            self._tcm_vars[key] = var
            ttk.Entry(row, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._tcm_enable_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(group, text="使能", variable=self._tcm_enable_var).pack(
            anchor="w", pady=(4, 0)
        )
        ttk.Button(group, text="配置 TCM 链路", command=self._run_tcm_link_config).pack(
            anchor="w", pady=(6, 0)
        )

    def _build_reg_read_row(self, parent) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(row, text="reg-read:").pack(side=tk.LEFT)
        self._reg_address_var = tk.StringVar(value="0x10")
        ttk.Entry(row, textvariable=self._reg_address_var, width=8).pack(
            side=tk.LEFT, padx=(4, 4)
        )
        self._reg_length_var = tk.StringVar(value="1")
        ttk.Entry(row, textvariable=self._reg_length_var, width=4).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(row, text="读取寄存器", command=self._run_reg_read).pack(
            side=tk.LEFT
        )

    # ---------------------------------------------------------------- actions

    def _selected_device(self) -> str:
        if self.app.profile is None:
            raise ValueError("请先加载 profile")
        device = self._device_var.get()
        if not device:
            raise ValueError("请选择设备")
        return device

    def _run_task(self, fn, on_result) -> None:
        if self._busy:
            self.app.log("板卡 tab 有操作进行中，请等待完成")
            return
        self._busy = True
        for button in self._action_buttons:
            button.configure(state=tk.DISABLED)
        self.result.show("运行中...")

        def on_error(exc: BaseException) -> None:
            self._finish_task(False, exc)

        threads.run_in_background(
            fn=fn,
            on_done=lambda result: self._finish_task(True, result, on_result),
            on_error=on_error,
            schedule=self.app.schedule,
        )

    def _finish_task(self, ok: bool, payload, on_result=None) -> None:
        self._busy = False
        for button in self._action_buttons:
            button.configure(state=tk.NORMAL)
        if ok:
            on_result(payload)
        else:
            self.result.show(f"错误: {payload}")
            self.app.log(f"操作失败: {payload}")

    def _run_info(self) -> None:
        def task():
            return self.board_service.get_board_info(
                device_name=self._selected_device(), profile_path=self.app.profile_path
            )

        self._run_task(task, lambda result: self.result.show(formatting.format_board_info(result)))

    def _run_sysmon(self) -> None:
        def task():
            return self.telemetry_service.get_board_sysmon(
                device_name=self._selected_device(), profile_path=self.app.profile_path
            )

        self._run_task(task, lambda result: self.result.show(formatting.format_sysmon(result)))

    def _run_trigger_show(self) -> None:
        def task():
            return self.board_service.read_trigger_config(
                device_name=self._selected_device(), profile_path=self.app.profile_path
            )

        self._run_task(
            task, lambda result: self.result.show(formatting.format_trigger_config(result))
        )

    def _run_tcp_mode2_show(self) -> None:
        def task():
            return self.board_service.read_tcp_mode2_config(
                device_name=self._selected_device(), profile_path=self.app.profile_path
            )

        self._run_task(
            task, lambda result: self.result.show(formatting.format_tcp_mode2_config(result))
        )

    def _run_config_show(self) -> None:
        def task():
            return self.board_service.read_board_config_summary(
                device_name=self._selected_device(), profile_path=self.app.profile_path
            )

        def render(result) -> None:
            text = (
                formatting.format_trigger_config(result.trigger)
                + "\n\n"
                + formatting.format_tcp_mode2_config(result.tcp_mode2)
            )
            self.result.show(text)

        self._run_task(task, render)

    def _run_tcm_link_show(self) -> None:
        def task():
            return self.board_service.read_tcm_link_config(
                device_name=self._selected_device(), profile_path=self.app.profile_path
            )

        self._run_task(
            task, lambda result: self.result.show(formatting.format_tcm_link_read(result))
        )

    def _run_board_config(self) -> None:
        def task():
            options = formatting.board_config_options_from_form(
                adc_enabled=self._adc_enabled.get(),
                clock_enabled=self._clock_enabled.get(),
                trigger_enabled=self._trigger_enabled.get(),
                tcp_mode2_enabled=self._tcp_mode2_enabled.get(),
                trigger_mode=int(self._trigger_mode_var.get(), 0),
                trigger_position=int(self._trigger_position_var.get(), 0),
                threshold_1=int(self._threshold_vars[0].get(), 0),
                threshold_2=int(self._threshold_vars[1].get(), 0),
                threshold_3=int(self._threshold_vars[2].get(), 0),
                threshold_4=int(self._threshold_vars[3].get(), 0),
                timestamp_clean_enabled=self._timestamp_clean_var.get(),
                ext_trigger_enabled=self._ext_trigger_var.get(),
                send_mode=(
                    int(self._send_mode_var.get(), 0)
                    if self._send_mode_var.get().strip()
                    else None
                ),
            )
            return self.board_service.configure_board(
                device_name=self._selected_device(),
                profile_path=self.app.profile_path,
                options=options,
            )

        def render(result) -> None:
            self.result.show(
                f"配置完成: success={result.success}\n"
                f"trigger_mode={result.trigger_mode} "
                f"trigger_position={result.trigger_position} "
                f"send_mode={result.effective_send_mode}"
            )
            self.app.log(result.log_output)

        self._run_task(task, render)

    def _run_tcm_link_config(self) -> None:
        def task():
            thr = formatting.parse_int_list(self._tcm_vars["thr_var"].get(), 16, "thr")
            return self.board_service.configure_tcm_link(
                device_name=self._selected_device(),
                profile_path=self.app.profile_path,
                thresholds=thr,
                mask=int(self._tcm_vars["mask_var"].get(), 0),
                polarity=int(self._tcm_vars["polarity_var"].get(), 0),
                debounce=int(self._tcm_vars["debounce_var"].get(), 0),
                pulse_width=int(self._tcm_vars["width_var"].get(), 0),
                enable=self._tcm_enable_var.get(),
            )

        self._run_task(
            task, lambda result: self.result.show(formatting.format_tcm_link_write(result))
        )

    def _run_reg_read(self) -> None:
        def task():
            address = int(self._reg_address_var.get(), 0)
            length = int(self._reg_length_var.get(), 0)
            if length < 1 or length > 255:
                raise ValueError("长度需在 1..255")
            return self.board_service.read_registers(
                device_name=self._selected_device(),
                profile_path=self.app.profile_path,
                address=address,
                length=length,
            )

        self._run_task(
            task, lambda result: self.result.show(formatting.format_register_read(result))
        )

    # ---------------------------------------------------------------- lifecycle

    def refresh(self, profile) -> None:
        devices = sorted(profile.devices)
        self._device_combo.configure(values=devices)
        if devices and self._device_var.get() not in devices:
            self._device_var.set(devices[0])

    def shutdown(self) -> None:
        pass
