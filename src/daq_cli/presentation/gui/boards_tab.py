"""板卡 tab：info / sysmon / config / 各 show / tcm-link / reg-read。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from daq_cli.application.board_service import BoardService
from daq_cli.application.telemetry_service import TelemetryService
from daq_cli.presentation.gui import formatting, threads
from daq_cli.presentation.gui.widgets import ResultArea, ScrollableFrame


class BoardTab:
    def __init__(self, app, notebook) -> None:
        self.app = app
        # The whole tab is scrollable: the mode 9 panel plus forms exceed
        # typical window heights; children go into frame.inner.
        self.frame = ScrollableFrame(notebook, padding=8)
        self.board_service = BoardService()
        self.telemetry_service = TelemetryService()
        self._busy = False
        self._task_buttons: list = []

        row = ttk.Frame(self.frame.inner)
        row.pack(fill=tk.X)
        ttk.Label(row, text="设备:").pack(side=tk.LEFT)
        self._device_var = tk.StringVar()
        self._device_combo = ttk.Combobox(
            row, textvariable=self._device_var, state="readonly", width=24
        )
        self._device_combo.pack(side=tk.LEFT, padx=(4, 0))

        action_row = ttk.Frame(self.frame.inner)
        action_row.pack(fill=tk.X, pady=(8, 4))
        for label, callback in (
            ("info", self._run_info),
            ("sysmon", self._run_sysmon),
            ("trigger-show", self._run_trigger_show),
            ("tcp-mode2-show", self._run_tcp_mode2_show),
            ("config-show", self._run_config_show),
            ("tcm-link-show", self._run_tcm_link_show),
        ):
            button = ttk.Button(action_row, text=label, command=callback)
            button.pack(side=tk.LEFT, padx=(0, 6))
            self._task_buttons.append(button)

        body = ttk.Frame(self.frame.inner)
        body.pack(fill=tk.BOTH, expand=True, pady=(4, 4))
        forms_row = ttk.Frame(body)
        forms_row.pack(fill=tk.X)
        self._build_config_form(forms_row)
        self._build_mode9_panel(body)
        self._build_reg_read_row(body)

        self.result = ResultArea(self.frame.inner, text="结果")
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

        button = ttk.Button(group, text="配置板卡", command=self._run_board_config)
        button.pack(anchor="w", pady=(8, 0))
        self._task_buttons.append(button)

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
        button = ttk.Button(row, text="读取寄存器", command=self._run_reg_read)
        button.pack(side=tk.LEFT)
        self._task_buttons.append(button)

    def _build_mode9_panel(self, parent) -> None:
        """mode 9 寄存器全量面板：三组寄存器逐项可设。"""
        panel = ttk.LabelFrame(parent, text="TCM 触发 (mode 9) 寄存器", padding=(8, 4))
        panel.pack(fill=tk.X, pady=(6, 0))

        top_row = ttk.Frame(panel)
        top_row.pack(fill=tk.X)
        self._build_mode9_trigger_group(top_row)
        self._build_mode9_data_group(top_row)
        self._build_mode9_link_group(panel)

        action_row = ttk.Frame(panel)
        action_row.pack(fill=tk.X, pady=(6, 0))
        apply_button = ttk.Button(
            action_row, text="应用全部并回读验证", command=self._run_mode9_apply
        )
        apply_button.pack(side=tk.LEFT)
        self._task_buttons.append(apply_button)
        refresh_button = ttk.Button(
            action_row, text="回读刷新", command=self._run_mode9_refresh
        )
        refresh_button.pack(side=tk.LEFT, padx=(6, 0))
        self._task_buttons.append(refresh_button)
        ttk.Label(
            action_row,
            text="注：mode 9 下主触发阈值 (0x11~0x18) 不使用；EXT_Trigger_en 开启会覆盖触发源，mode 9 应保持关闭。",
            foreground="#666666",
        ).pack(side=tk.LEFT, padx=(12, 0))

    def _build_mode9_trigger_group(self, parent) -> None:
        group = ttk.LabelFrame(parent, text="A. 触发源", padding=(8, 4))
        group.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        grid = ttk.Frame(group)
        grid.pack(fill=tk.X)
        self._m9_model_var = tk.StringVar(value="9")
        self._m9_position_var = tk.StringVar(value="5")
        self._m9_start_delay_var = tk.StringVar(value="0")
        ttk.Label(grid, text="0x10 Trigger_model").grid(row=0, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self._m9_model_var, width=6).grid(
            row=0, column=1, sticky="w", padx=(4, 12)
        )
        ttk.Label(grid, text="0x19 Trigger_position").grid(row=0, column=2, sticky="w")
        ttk.Entry(grid, textvariable=self._m9_position_var, width=6).grid(
            row=0, column=3, sticky="w", padx=(4, 0)
        )
        ttk.Label(grid, text="0x1B~1D SEND_START_DELAY").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        ttk.Entry(grid, textvariable=self._m9_start_delay_var, width=8).grid(
            row=1, column=1, sticky="w", padx=(4, 0), pady=(4, 0)
        )

        flag_row = ttk.Frame(group)
        flag_row.pack(fill=tk.X, pady=(6, 0))
        self._m9_time_clean_var = tk.BooleanVar(value=False)
        self._m9_ext_trigger_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            flag_row, text="0x06 bit1 Time_clean", variable=self._m9_time_clean_var
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(
            flag_row, text="0x06 bit2 EXT_Trigger_en", variable=self._m9_ext_trigger_var
        ).pack(side=tk.LEFT)

    def _build_mode9_data_group(self, parent) -> None:
        group = ttk.LabelFrame(parent, text="C. 数据格式", padding=(8, 4))
        group.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        grid = ttk.Frame(group)
        grid.pack(fill=tk.X)
        self._m9_send_mode_var = tk.StringVar(value="1")
        self._m9_integ_pre_var = tk.StringVar(value="0")
        self._m9_integ_post_var = tk.StringVar(value="0")
        ttk.Label(grid, text="0x42 Send_mode").grid(row=0, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self._m9_send_mode_var, width=6).grid(
            row=0, column=1, sticky="w", padx=(4, 12)
        )
        ttk.Label(grid, text="0x43 Integ_pre").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(grid, textvariable=self._m9_integ_pre_var, width=6).grid(
            row=1, column=1, sticky="w", padx=(4, 0), pady=(4, 0)
        )
        ttk.Label(grid, text="0x44 Integ_post").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(grid, textvariable=self._m9_integ_post_var, width=6).grid(
            row=2, column=1, sticky="w", padx=(4, 0), pady=(4, 0)
        )

    def _build_mode9_link_group(self, parent) -> None:
        group = ttk.LabelFrame(parent, text="B. 过阈链路 (TCM, 0x45..0x6C)", padding=(8, 4))
        group.pack(fill=tk.X, pady=(6, 0))

        # 16 per-channel threshold fields (4 columns x 4 rows; registers
        # 0x45..0x64, high byte first). Each channel has its own register,
        # because baselines/gains differ per channel.
        ttk.Label(
            group, text="0x45..0x64 阈值（每通道独立，参考各自基线）:"
        ).pack(anchor="w")
        thr_frame = ttk.Frame(group)
        thr_frame.pack(fill=tk.X, pady=(2, 0))
        self._m9_thr_vars: list[tk.StringVar] = []
        for row_index in range(4):
            for col_index in range(4):
                channel = col_index * 4 + row_index
                cell = ttk.Frame(thr_frame)
                cell.grid(row=row_index, column=col_index, sticky="w", padx=(0, 12))
                ttk.Label(cell, text=f"ch{channel:02d}").pack(side=tk.LEFT)
                var = tk.StringVar(value="0")
                self._m9_thr_vars.append(var)
                ttk.Entry(cell, textvariable=var, width=6).pack(side=tk.LEFT, padx=(4, 0))

        # control + broadcast-fill helpers on one row (convenience only;
        # thresholds stay per-channel)
        control_row = ttk.Frame(group)
        control_row.pack(fill=tk.X, pady=(6, 0))
        self._m9_mask_var = tk.StringVar(value="0x0003")
        self._m9_polarity_var = tk.StringVar(value="0x0000")
        self._m9_debounce_var = tk.StringVar(value="200")
        self._m9_width_var = tk.StringVar(value="20")
        self._m9_enable_var = tk.BooleanVar(value=True)
        ttk.Label(control_row, text="0x65~66 mask").pack(side=tk.LEFT)
        ttk.Entry(control_row, textvariable=self._m9_mask_var, width=7).pack(
            side=tk.LEFT, padx=(4, 10)
        )
        ttk.Label(control_row, text="0x67~68 polarity").pack(side=tk.LEFT)
        ttk.Entry(control_row, textvariable=self._m9_polarity_var, width=7).pack(
            side=tk.LEFT, padx=(4, 10)
        )
        ttk.Label(control_row, text="0x69~6A debounce(5ns)").pack(side=tk.LEFT)
        ttk.Entry(control_row, textvariable=self._m9_debounce_var, width=6).pack(
            side=tk.LEFT, padx=(4, 10)
        )
        ttk.Label(control_row, text="0x6C width(5ns)").pack(side=tk.LEFT)
        ttk.Entry(control_row, textvariable=self._m9_width_var, width=6).pack(
            side=tk.LEFT, padx=(4, 10)
        )
        ttk.Checkbutton(control_row, text="0x6B enable", variable=self._m9_enable_var).pack(
            side=tk.LEFT
        )
        ttk.Label(control_row, text="广播填值:").pack(side=tk.LEFT, padx=(12, 0))
        self._m9_broadcast_var = tk.StringVar(value="")
        ttk.Entry(control_row, textvariable=self._m9_broadcast_var, width=8).pack(
            side=tk.LEFT, padx=(4, 4)
        )
        ttk.Button(
            control_row, text="填到16通道", command=self._fill_thr_broadcast
        ).pack(side=tk.LEFT)

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
        for button in self._task_buttons:
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
        for button in self._task_buttons:
            button.configure(state=tk.NORMAL)
        if ok:
            on_result(payload)
        else:
            self.result.show(f"错误: {payload}")
            self.app.log(f"操作失败: {payload}")

    def _run_info(self) -> None:
        device = self._selected_device()  # read on the GUI thread

        def task():
            return self.board_service.get_board_info(
                device_name=device, profile_path=self.app.profile_path
            )

        self._run_task(task, lambda result: self.result.show(formatting.format_board_info(result)))

    def _run_sysmon(self) -> None:
        device = self._selected_device()

        def task():
            return self.telemetry_service.get_board_sysmon(
                device_name=device, profile_path=self.app.profile_path
            )

        self._run_task(task, lambda result: self.result.show(formatting.format_sysmon(result)))

    def _run_trigger_show(self) -> None:
        device = self._selected_device()

        def task():
            return self.board_service.read_trigger_config(
                device_name=device, profile_path=self.app.profile_path
            )

        self._run_task(
            task, lambda result: self.result.show(formatting.format_trigger_config(result))
        )

    def _run_tcp_mode2_show(self) -> None:
        device = self._selected_device()

        def task():
            return self.board_service.read_tcp_mode2_config(
                device_name=device, profile_path=self.app.profile_path
            )

        self._run_task(
            task, lambda result: self.result.show(formatting.format_tcp_mode2_config(result))
        )

    def _run_config_show(self) -> None:
        device = self._selected_device()

        def task():
            return self.board_service.read_board_config_summary(
                device_name=device, profile_path=self.app.profile_path
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
        device = self._selected_device()

        def task():
            return self.board_service.read_tcm_link_config(
                device_name=device, profile_path=self.app.profile_path
            )

        self._run_task(
            task, lambda result: self.result.show(formatting.format_tcm_link_read(result))
        )

    def _run_board_config(self) -> None:
        device = self._selected_device()
        options = formatting.board_config_options_from_form(
            adc_enabled=self._adc_enabled.get(),
            clock_enabled=self._clock_enabled.get(),
            trigger_enabled=self._trigger_enabled.get(),
            tcp_mode2_enabled=self._tcp_mode2_enabled.get(),
            trigger_mode=formatting.parse_int_field(self._trigger_mode_var.get(), "trigger-mode"),
            trigger_position=formatting.parse_int_field(
                self._trigger_position_var.get(), "trigger-position"
            ),
            threshold_1=formatting.parse_int_field(self._threshold_vars[0].get(), "阈值1"),
            threshold_2=formatting.parse_int_field(self._threshold_vars[1].get(), "阈值2"),
            threshold_3=formatting.parse_int_field(self._threshold_vars[2].get(), "阈值3"),
            threshold_4=formatting.parse_int_field(self._threshold_vars[3].get(), "阈值4"),
            timestamp_clean_enabled=self._timestamp_clean_var.get(),
            ext_trigger_enabled=self._ext_trigger_var.get(),
            send_mode=(
                formatting.parse_int_field(self._send_mode_var.get(), "send-mode")
                if self._send_mode_var.get().strip()
                else None
            ),
        )

        def task():
            return self.board_service.configure_board(
                device_name=device,
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

    def _run_mode9_apply(self) -> None:
        """应用全部：读面板全部字段 → 三组分别写 → 回读验证。"""
        # All form values are read on the GUI thread (tkinter variables are
        # not thread-safe) and captured into the task closure.
        from daq_cli.application.config_models import BoardConfigOptions

        device = self._selected_device()
        model = formatting.parse_int_field(self._m9_model_var.get(), "Trigger_model")
        position = formatting.parse_int_field(self._m9_position_var.get(), "Trigger_position")
        start_delay = formatting.parse_int_field(
            self._m9_start_delay_var.get(), "SEND_START_DELAY"
        )
        send_mode = (
            formatting.parse_int_field(self._m9_send_mode_var.get(), "send_mode")
            if self._m9_send_mode_var.get().strip()
            else None
        )
        integ_pre = formatting.parse_int_field(self._m9_integ_pre_var.get(), "Integ_pre")
        integ_post = formatting.parse_int_field(self._m9_integ_post_var.get(), "Integ_post")
        thr = formatting.mode9_thresholds_from_fields(
            [var.get() for var in self._m9_thr_vars]
        )
        mask = formatting.parse_int_field(self._m9_mask_var.get(), "mask")
        polarity = formatting.parse_int_field(self._m9_polarity_var.get(), "polarity")
        debounce = formatting.parse_int_field(self._m9_debounce_var.get(), "debounce")
        width = formatting.parse_int_field(self._m9_width_var.get(), "width")
        time_clean = self._m9_time_clean_var.get()
        ext_trigger = self._m9_ext_trigger_var.get()
        enable = self._m9_enable_var.get()

        def task():
            # A. 触发源
            board_result = self.board_service.configure_board(
                device_name=device,
                profile_path=self.app.profile_path,
                send_start_delay_us=start_delay,
                options=BoardConfigOptions(
                    adc_enabled=False,
                    clock_enabled=False,
                    trigger_enabled=True,
                    tcp_mode2_enabled=False,
                    trigger_thresholds=(0, 0, 0, 0),  # unused in mode 9
                    trigger_mode=model,
                    trigger_position=position,
                    timestamp_clean_enabled=time_clean,
                    ext_trigger_enabled=ext_trigger,
                    send_mode=send_mode,
                ),
            )
            # B. 过阈链路
            tcm_result = self.board_service.configure_tcm_link(
                device_name=device,
                profile_path=self.app.profile_path,
                thresholds=thr,
                mask=mask,
                polarity=polarity,
                debounce=debounce,
                pulse_width=width,
                enable=enable,
            )
            # C. 数据格式（0x43/0x44 无 service 方法，直写寄存器）
            self.board_service.write_registers(
                device_name=device,
                profile_path=self.app.profile_path,
                address=0x43,
                data=bytes([integ_pre & 0xFF]),
            )
            self.board_service.write_registers(
                device_name=device,
                profile_path=self.app.profile_path,
                address=0x44,
                data=bytes([integ_post & 0xFF]),
            )
            # 回读验证
            trigger = self.board_service.read_trigger_config(
                device_name=device, profile_path=self.app.profile_path
            )
            tcm_read = self.board_service.read_tcm_link_config(
                device_name=device, profile_path=self.app.profile_path
            )
            tcp_read = self.board_service.read_tcp_mode2_config(
                device_name=device, profile_path=self.app.profile_path
            )
            return board_result, trigger, tcm_read, tcp_read

        def render(results) -> None:
            board_result, trigger, tcm_read, tcp_read = results
            self.result.show(
                "mode 9 配置完成（回读验证通过）\n"
                + formatting.format_trigger_config(trigger)
                + "\n\n"
                + formatting.format_tcm_link_read(tcm_read)
                + "\n\n"
                + formatting.format_fields(
                    "数据格式",
                    [
                        ("send_mode", tcp_read.send_mode),
                        ("integ_pre", tcp_read.integration_pre_samples),
                        ("integ_post", tcp_read.integration_post_samples),
                    ],
                )
            )
            self.app.log(board_result.log_output)

        self._run_task(task, render)

    def _run_mode9_refresh(self) -> None:
        """回读刷新：读取三组寄存器当前值，填回面板表单。"""
        device = self._selected_device()  # read on the GUI thread

        def task():
            trigger = self.board_service.read_trigger_config(
                device_name=device, profile_path=self.app.profile_path
            )
            tcm = self.board_service.read_tcm_link_config(
                device_name=device, profile_path=self.app.profile_path
            )
            tcp = self.board_service.read_tcp_mode2_config(
                device_name=device, profile_path=self.app.profile_path
            )
            return formatting.mode9_readback_to_values(trigger, tcm, tcp)

        def render(values) -> None:
            def apply_var(var, value) -> None:
                if isinstance(value, bool):
                    var.set(value)
                else:
                    var.set(str(value))

            apply_var(self._m9_model_var, values["model"])
            apply_var(self._m9_position_var, values["position"])
            apply_var(self._m9_time_clean_var, values["time_clean"])
            apply_var(self._m9_ext_trigger_var, values["ext_trigger"])
            apply_var(self._m9_start_delay_var, values["start_delay"])
            for var, value in zip(self._m9_thr_vars, values["thr"]):
                var.set(str(value))
            apply_var(self._m9_mask_var, values["mask"])
            apply_var(self._m9_polarity_var, values["polarity"])
            apply_var(self._m9_debounce_var, values["debounce"])
            apply_var(self._m9_enable_var, values["enable"])
            apply_var(self._m9_width_var, values["pulse_width"])
            apply_var(self._m9_send_mode_var, values["send_mode"])
            apply_var(self._m9_integ_pre_var, values["integ_pre"])
            apply_var(self._m9_integ_post_var, values["integ_post"])
            self.result.show("已从寄存器回读刷新面板")

        self._run_task(task, render)

    def _fill_thr_broadcast(self) -> None:
        """广播填值：把一个值填进全部 16 个通道阈值框。"""
        try:
            value = formatting.parse_int_field(self._m9_broadcast_var.get(), "广播阈值")
            if value < 0 or value > 0xFFFF:
                raise ValueError(f"广播阈值超出范围 0..0xFFFF: {value}")
        except ValueError as exc:
            self.result.show(f"广播填值失败: {exc}")
            return
        for var in self._m9_thr_vars:
            var.set(str(value))
        self.app.log(f"已广播阈值 {value} 到 16 通道")

    def _run_reg_read(self) -> None:
        device = self._selected_device()
        address = formatting.parse_int_field(self._reg_address_var.get(), "寄存器地址")
        length = formatting.parse_int_field(self._reg_length_var.get(), "长度")
        if length < 1 or length > 255:
            self.result.show("长度需在 1..255")
            return

        def task():
            return self.board_service.read_registers(
                device_name=device,
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
