"""Live hardware configuration for the Qt workstation."""

from datetime import datetime
from functools import partial

from PySide6 import QtCore, QtWidgets as W

from daq_cli.application.board_service import BoardService
from daq_cli.application.config_models import BoardConfigOptions, board_profile_options
from daq_cli.application.profile_service import ProfileService
from daq_cli.application.tcm_service import TcmService
from daq_cli.infrastructure.tcm_link_calibration import suggested_thresholds
from daq_cli.qt_scope import label


def spin(maximum, value, *, hex_value=False, minimum=0):
    widget = W.QSpinBox()
    widget.setRange(minimum, maximum)
    if hex_value:
        widget.setDisplayIntegerBase(16)
        widget.setPrefix("0x")
    widget.setValue(value)
    return widget


class SettingsForm(W.QWidget):
    """Mutable draft and a separate snapshot from the most recent read."""

    def __init__(self):
        super().__init__()
        self.fields = {}
        self.snapshot = {}
        self.readback_text = ""
        self.form = W.QFormLayout(self)
        self.form.setContentsMargins(4, 8, 4, 4)
        self.form.setFieldGrowthPolicy(W.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

    def number(self, key, caption, maximum, value, **kwargs):
        widget = spin(maximum, value, **kwargs)
        self.fields[key] = widget
        self.form.addRow(caption, widget)
        return widget

    def flag(self, key, caption, value=False):
        widget = W.QCheckBox(caption)
        widget.setChecked(value)
        self.fields[key] = widget
        self.form.addRow(widget)

    def numbers(self, key, caption, values, maximum, columns=4, hex_value=False):
        box = W.QGroupBox(caption)
        grid = W.QGridLayout(box)
        widgets = []
        for i, value in enumerate(values):
            row, col = divmod(i, columns)
            widget = spin(maximum, value, hex_value=hex_value)
            grid.addWidget(label(str(i), "muted"), row, col * 2)
            grid.addWidget(widget, row, col * 2 + 1)
            widgets.append(widget)
        self.fields[key] = widgets
        self.form.addRow(box)

    def values(self):
        values = {}
        for key, widget in self.fields.items():
            if isinstance(widget, list):
                values[key] = [item.value() for item in widget]
            elif isinstance(widget, W.QCheckBox):
                values[key] = widget.isChecked()
            else:
                values[key] = widget.value()
        return values

    def fill(self, values):
        for key, value in values.items():
            widget = self.fields[key]
            if isinstance(widget, list):
                for item, number in zip(widget, value, strict=True):
                    item.setValue(number)
            elif isinstance(widget, W.QCheckBox):
                widget.setChecked(value)
            else:
                widget.setValue(value)


def trigger_values(trigger, tcp):
    return dict(trigger_mode=trigger.trigger_mode, trigger_position=trigger.trigger_position,
                send_start_delay_ticks=trigger.send_start_delay, send_mode=tcp.send_mode,
                timestamp_clean=trigger.timestamp_clean_enabled, ext_trigger=trigger.ext_trigger_enabled)


class AdcForm(SettingsForm):
    def __init__(self, defaults, mode9=False):
        super().__init__()
        self.mode9 = mode9
        if not mode9:
            self.flag("adc_enabled", "初始化 ADC")
            self.flag("clock_enabled", "初始化时钟")
            self.flag("trigger_enabled", "写入触发配置", True)
            self.flag("tcp_mode2_enabled", "写入 TCP Mode 2 配置", True)
            self.number("trigger_mode", "触发模式", 255, defaults.trigger_mode)
            self.numbers("trigger_thresholds", "常规触发阈值", defaults.trigger_thresholds, 65535, 2)
        self.number("trigger_position", "触发位置", 255, defaults.trigger_position)
        self.number("send_start_delay_ticks", "发送延迟（5 ns）", 0xFFFFFF, 0)
        send = self.number("send_mode", "发送模式", 3, 1 if mode9 else -1, minimum=-1)
        send.setSpecialValueText("保持当前值")
        self.flag("timestamp_clean", "清时间戳")
        self.flag("ext_trigger", "外部触发")
        if mode9:
            self.flag("enable", "启用 ADC → TCM 脉冲", True)
            self.number("mask", "通道掩码", 65535, 0x0fff, hex_value=True)
            self.number("polarity", "负极性掩码", 65535, 0x0fff, hex_value=True)
            self.number("debounce", "去抖（5 ns）", 65535, 200)
            self.number("pulse_width", "脉宽（5 ns）", 255, 20)
            self.number("integration_pre", "前积分点", 255, 0)
            self.number("integration_post", "后积分点", 255, 0)
            self.seconds = spin(3600, 5, minimum=1)
            self.offset = spin(65535, 100, minimum=1)
            self.form.addRow("标定时长（秒）", self.seconds)
            self.form.addRow("基线偏移（ADC）", self.offset)
            self.numbers("thresholds", "16 路过阈值", [0] * 16, 65535, columns=2)

    def operation(self, action, target, profile):
        path = profile.path
        service = BoardService(ProfileService(profile))
        if action == "read":
            read = service.read_mode9 if self.mode9 else service.read_board_config_summary
            return partial(read, target, path)
        if action == "calibrate":
            return partial(service.measure_tcm_link, target, path, seconds=self.seconds.value())
        values = self.values()
        if values["send_mode"] == -1:
            values["send_mode"] = None
        if self.mode9:
            return lambda: service.configure_mode9(target, path, trigger_mode=9, **values)[1]
        delay_us = values.pop("send_start_delay_ticks") / 200
        options = BoardConfigOptions(
            timestamp_clean_enabled=values.pop("timestamp_clean"),
            ext_trigger_enabled=values.pop("ext_trigger"),
            trigger_thresholds=tuple(values.pop("trigger_thresholds")), **values,
        )

        def apply():
            result = service.configure_board(target, path, delay_us, options)
            if not result.success:
                raise RuntimeError(result.log_output)
            return service.read_board_config_summary(target, path)
        return apply

    def receive(self, action, result):
        if action == "calibrate":
            calibration = result.calibration
            values = suggested_thresholds(calibration, self.offset.value(), self.fields["polarity"].value())
            if len(values) != 16 or any(not 0 <= v <= 65535 for v in values):
                raise ValueError("标定阈值超出范围，未更新草稿")
            self.fill({"thresholds": values})
            return f"标定 {calibration.frames} 帧，建议阈值已载入草稿。\n基线：" + ", ".join(
                str(channel.baseline) for channel in calibration.channels)
        if self.mode9:
            values = trigger_values(result.trigger, result.tcp)
            mode = values.pop("trigger_mode")
            values.update({key: getattr(result.link, key) for key in
                           ("enable", "mask", "polarity", "debounce", "pulse_width", "thresholds")})
            values.update(integration_pre=result.tcp.integration_pre_samples,
                          integration_post=result.tcp.integration_post_samples)
            heading = f"硬件触发模式 {mode}（本页应用模式 9）"
        else:
            values = trigger_values(result.trigger, result.tcp_mode2)
            values["trigger_thresholds"] = result.trigger.thresholds
            heading = "ADC 配置回读"
        self.snapshot = values
        return heading + "\n" + format_values(values)


def format_values(values):
    return "\n".join(f"{key}   {value}" for key, value in values.items())


class TcmForm(SettingsForm):
    def __init__(self):
        super().__init__()
        self.flag("enable", "启用触发", True)
        self.number("mask", "输入掩码", 255, 1, hex_value=True)
        self.number("pulse_width", "脉宽（20 MHz 周期）", 255, 32)
        self.number("debounce", "去抖（20 MHz 周期）", 65535, 20)
        self.flag("coincidence_enabled", "启用符合触发")
        self.number("grp_count", "组数（0 为默认）", 4, 0)
        self.number("coinc_window", "符合窗口（20 MHz 周期）", 255, 0)
        self.numbers("group_masks", "分组掩码", [0]*4, 255, 2, True)
        self.numbers("group_n", "每组最少命中数", [0]*4, 8, 2)

    def operation(self, action, target, profile):
        path = profile.path
        service = TcmService(ProfileService(profile))
        if action == "read":
            return partial(service.read_trigger_config, target, path)
        values = self.values()
        for key in ("group_masks", "group_n"):
            values[key] = tuple(values[key])

        def apply():
            service.configure_trigger(target, path, **values)
            return service.read_trigger_config(target, path)
        return apply

    def receive(self, action, result):
        self.snapshot = {key: getattr(result, key) for key in self.fields}
        return (f"最近触发通道 0x{result.last_trigger_channels:02X}   "
                f"sticky {int(result.trig_sticky)}   超时 {int(result.coinc_timeout_sticky)}\n"
                f"等待 {int(result.pending)}   脉冲 {int(result.wide_pulse_active)}   "
                f"已收集 {result.collected_count}   符合组 0x{result.grp_ok:X}\n"
                + format_values(self.snapshot))


class HardwareTask(QtCore.QThread):
    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.operation()
        except Exception as exc:
            self.error = str(exc) or type(exc).__name__


class ConfigPanel(W.QFrame):
    busy_changed = QtCore.Signal()

    def __init__(self, single, multi=None):
        super().__init__(objectName="panel")
        self.single = single
        self.multi = multi
        self.profile = None
        self.task = None
        self.write_ip = None
        self.pages = {}
        self.reports = {}
        layout = W.QVBoxLayout(self)
        layout.addWidget(label("硬件配置", "section"))
        self.profile_label = label("", "muted")
        layout.addWidget(self.profile_label)
        self.target = W.QComboBox()
        layout.addWidget(self.target)
        self.tabs = W.QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.note = label("", "muted")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        buttons = W.QGridLayout()
        self.read = W.QPushButton("读取当前值")
        self.copy = W.QPushButton("回读载入草稿")
        self.write = W.QPushButton("应用并回读", objectName="primary")
        self.calibrate = W.QPushButton("标定基线")
        for i, button in enumerate((self.read, self.copy, self.write, self.calibrate)):
            buttons.addWidget(button, i//2, i%2)
        self.read.clicked.connect(lambda: self.submit("read"))
        self.write.clicked.connect(lambda: self.submit("write"))
        self.calibrate.clicked.connect(lambda: self.submit("calibrate"))
        self.copy.clicked.connect(self.copy_snapshot)
        layout.addLayout(buttons)
        self.report = W.QPlainTextEdit(readOnly=True)
        self.report.setMaximumHeight(110)
        layout.addWidget(self.report)
        self.target.currentIndexChanged.connect(self.select_target)
        self.tabs.currentChanged.connect(self.refresh)
        single.profile_changed.connect(self.set_profile)
        single.active_changed.connect(self.refresh)
        if multi is not None:
            multi.active_changed.connect(self.refresh)
        self.set_profile(single.profile)

    def set_profile(self, profile):
        self.profile = profile
        self.tabs.clear()
        for pages in self.pages.values():
            for page in pages:
                page.deleteLater()
        self.pages.clear()
        self.reports.clear()
        self.profile_label.setText(profile.path.name if profile else "请选择采样配置")
        with QtCore.QSignalBlocker(self.target):
            self.target.clear()
            if profile:
                for kind, devices in (("ADC", profile.devices), ("TCM", profile.tcm)):
                    for name, device in devices.items():
                        self.target.addItem(f"{kind}  {name}   ·   {device.ip}", (kind, name))
        self.select_target()

    def select_target(self):
        self.tabs.clear()
        key = self.target.currentData()
        if key:
            kind, _ = key
            if self.target.currentIndex() not in self.pages:
                if kind == "ADC":
                    defaults = board_profile_options(self.profile.defaults)
                    forms = [("板卡", AdcForm(defaults)), ("模式 9", AdcForm(defaults, True))]
                else:
                    forms = [("TCM 触发", TcmForm())]
                pages = []
                for title, form in forms:
                    scroll = W.QScrollArea()
                    scroll.setWindowTitle(title)
                    scroll.setWidgetResizable(True)
                    scroll.setWidget(form)
                    pages.append(scroll)
                self.pages[self.target.currentIndex()] = pages
            for page in self.pages[self.target.currentIndex()]:
                self.tabs.addTab(page, page.windowTitle())
        self.refresh()

    def current_form(self):
        page = self.tabs.currentWidget()
        return page.widget() if page else None

    def target_ip(self):
        key = self.target.currentData()
        if not key:
            return None
        devices = self.profile.devices if key[0] == "ADC" else self.profile.tcm
        return devices[key[1]].ip

    def locked(self):
        ip = self.target_ip()
        return ((self.single.active and self.single.target_ip() == ip)
                or (self.multi is not None and ip in self.multi.reserved_ips))

    def refresh(self):
        form = self.current_form()
        ready = form is not None and self.task is None
        writable = ready and not self.locked()
        self.target.setDisabled(self.task is not None)
        self.tabs.setDisabled(self.task is not None)
        self.read.setEnabled(ready)
        self.write.setEnabled(writable)
        mode9 = isinstance(form, AdcForm) and form.mode9
        self.calibrate.setVisible(mode9)
        self.calibrate.setEnabled(writable and mode9)
        self.copy.setEnabled(ready and bool(form.snapshot))
        self.note.setText("操作进行中…" if self.task else
                          "该板正在采样，仅允许回读和编辑草稿。" if self.locked() else
                          "表单为草稿。应用时写入所选硬件。")
        message = self.reports.get(form, "")
        last_read = form.readback_text if form else ""
        self.report.setPlainText("\n".join(filter(None, (message, last_read))) or "尚无回读记录")

    def copy_snapshot(self):
        form = self.current_form()
        if form and form.snapshot and not self.task:
            form.fill(form.snapshot)

    def submit(self, action):
        form = self.current_form()
        if not form or self.task or (action != "read" and self.locked()):
            return
        if action == "calibrate" and not (isinstance(form, AdcForm) and form.mode9):
            return
        _, name = self.target.currentData()
        operation = form.operation(action, name, self.profile)
        self.write_ip = self.target_ip() if action != "read" else None
        self.task = HardwareTask(operation, self)
        self.pending = (form, name, action)
        self.task.finished.connect(self.finish)
        self.busy_changed.emit()
        self.refresh()
        self.task.start()

    @QtCore.Slot()
    def finish(self):
        task = self.task
        form, name, action = self.pending
        try:
            if task.error:
                raise RuntimeError(task.error)
            text = form.receive(action, task.result)
            if action == "calibrate":
                self.reports[form] = f"{name}  ·  {text}"
            else:
                when = datetime.now().strftime("%H:%M:%S")
                form.readback_text = f"{name}   回读 {when}\n{text}"
                self.reports.pop(form, None)
        except Exception as exc:
            self.reports[form] = f"{name} 操作失败：{exc}"
        self.task = None
        self.write_ip = None
        task.deleteLater()
        self.refresh()
        self.busy_changed.emit()
