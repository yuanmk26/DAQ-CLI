"""Group capture and per-board waveform previews for the Qt workstation."""

import threading
from pathlib import Path

from PySide6 import QtCore, QtWidgets as W

from daq_cli.application.acquire_options import default_output_base_dir, resolve_multi_acquire_options
from daq_cli.application.acquire_service import AcquireService
from daq_cli.application.profile_service import ProfileService
from daq_cli.infrastructure.tcp_sent_decode import decode_tcp_sent_packet
from daq_cli.qt_scope import label


class MultiSession(threading.Thread):
    def __init__(self, profile, params):
        super().__init__(name="qt-multi-capture")
        self.service = AcquireService(ProfileService(profile))
        self.params = params
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.packets = {}
        self.progress = {}
        self.directory = None
        self.result = None
        self.error = ""

    def accept_packet(self, packet):
        with self.lock:
            self.packets[packet.board_name] = packet

    def accept_progress(self, directory, progress):
        with self.lock:
            self.directory, self.progress = directory, progress

    def run(self):
        try:
            self.result = self.service.capture_multi(
                **self.params, cancel_event=self.cancel, watch_update_callback=self.accept_packet,
                progress_callback=self.accept_progress,
            )
        except Exception as exc:
            self.error = str(exc) or type(exc).__name__


class MultiCapturePane(W.QFrame):
    updated = QtCore.Signal(bool)
    active_changed = QtCore.Signal(bool)

    def __init__(self, single):
        super().__init__(objectName="panel")
        self.single = single
        self.session = None
        self.buttons = {}
        self.latest = {}
        self.displayed = {}
        self.selected = ""
        self.options = {}
        self.reserved_ips = set()
        self.decoded_packet = None
        self.traces = []
        self.timer = QtCore.QTimer(self, interval=100)
        self.timer.timeout.connect(self.poll)
        layout = W.QVBoxLayout(self)
        layout.addWidget(label("多板采样", "section"))
        self.load = W.QPushButton("选择配置…")
        self.load.clicked.connect(single.choose_profile)
        layout.addWidget(self.load)
        self.group = W.QComboBox()
        layout.addWidget(label("采样组"))
        layout.addWidget(self.group)
        self.cards = W.QVBoxLayout()
        layout.addLayout(self.cards)
        self.stride = W.QSpinBox()
        self.stride.setRange(1, 2147483647)
        layout.addWidget(label("每 N 帧预览"))
        layout.addWidget(self.stride)
        self.output = W.QLineEdit()
        layout.addWidget(label("输出目录"))
        layout.addWidget(self.output)
        layout.addStretch()
        self.count = label("", "muted")
        layout.addWidget(self.count)
        self.state = label("就绪", "section")
        layout.addWidget(self.state)
        self.controls = W.QFrame(objectName="panel")
        bar = W.QHBoxLayout(self.controls)
        self.start = W.QPushButton("开始采样", objectName="primary")
        self.stop_button = W.QPushButton("停止采样", enabled=False)
        self.pause = W.QPushButton("暂停波形", checkable=True, enabled=False)
        self.pause.setToolTip("冻结各板波形，继续接收和写盘")
        for button in (self.start, self.stop_button, self.pause):
            bar.addWidget(button)
        bar.addStretch()
        self.start.clicked.connect(self.begin)
        self.stop_button.clicked.connect(self.stop)
        self.pause.toggled.connect(self.pause_changed)
        self.group.currentIndexChanged.connect(self.group_changed)
        single.profile_changed.connect(self.set_profile)
        self.set_profile(single.profile)

    @property
    def active(self):
        return self.session is not None

    def set_profile(self, profile):
        self.profile = profile
        with QtCore.QSignalBlocker(self.group):
            self.group.clear()
            if profile:
                self.group.addItems(profile.groups)
                if profile.groups:
                    largest = max(profile.groups, key=lambda name: len(profile.groups[name].devices))
                    self.group.setCurrentText(largest)
        self.options = {}
        self.options_error = ""
        if profile:
            try:
                self.options = resolve_multi_acquire_options(defaults=profile.defaults)
                self.output.setText(str(self.options["output_dir"] or default_output_base_dir(profile) / "multi"))
                self.stride.setValue(self.options["watch_every"] or 1)
            except ValueError as exc:
                self.options_error = str(exc)
        self.group_changed()

    def group_changed(self):
        for button in self.buttons.values():
            self.cards.removeWidget(button)
            button.hide()
            button.deleteLater()
        self.buttons.clear()
        self.group_ips = set()
        self.valid = False
        group = self.profile.groups.get(self.group.currentText()) if self.profile else None
        if group:
            self.valid = bool(group.devices and group.tcm in self.profile.tcm and self.options)
            if group.tcm in self.profile.tcm:
                self.group_ips.add(self.profile.tcm[group.tcm].ip)
            for name in group.devices:
                device = self.profile.devices.get(name)
                if device:
                    self.group_ips.add(device.ip)
                else:
                    self.valid = False
                button = W.QPushButton(objectName="board", checkable=True)
                self.cards.addWidget(button)
                self.buttons[name] = button
                button.clicked.connect(lambda checked, n=name: self.select(n))
        self.selected = next(iter(self.buttons), "")
        self.latest = self.displayed = {}
        self.decoded_packet = None
        self.pause.setChecked(False)
        self.pause.setEnabled(False)
        self.message = self.options_error or ("等待开始采样" if self.valid else "请选择含有效 ADC 和 TCM 采样组的配置")
        self.state.setText("就绪")
        self.set_cards({})
        self.count.setText("完整 0    缺板 0")
        self.select(self.selected)
        self.refresh_interlock()

    def set_cards(self, stats):
        for name, button in self.buttons.items():
            stat = stats.get(name, {})
            device = self.profile.devices.get(name)
            state = "就绪"
            if self.active:
                state = ("已连接" if stat.get("connected") else "未连接") if stat else "正在连接"
            elif stat:
                state = "已结束"
            button.setText(f"{name}   ·   {state}\n{device.ip if device else '未知板卡'}   /   {stat.get('frames_total', 0)} 帧")

    def select(self, name):
        self.selected = name
        for key, button in self.buttons.items():
            button.setChecked(key == name)
        self.updated.emit(True)

    def refresh_interlock(self):
        blocked = self.single.config_write_ip in self.group_ips
        self.start.setEnabled(self.valid and not self.active and not blocked)
        self.start.setToolTip("组内设备正在配置或标定" if blocked else "")
        self.load.setDisabled(self.active or self.single.config_busy)

    def begin(self):
        if self.active or not self.valid or self.single.config_write_ip in self.group_ips:
            return
        self.latest = self.displayed = {}
        self.decoded_packet = None
        self.pause.setChecked(False)
        params = {k: self.options[k] for k in ("outputs", "aggregation_key", "timestamp_match_window_ticks",
                                                "event_timeout_ms", "tcp_timeout_s", "allow_start_without_ack")}
        self.session = MultiSession(self.profile, dict(
            **params, group_name=self.group.currentText(), profile_path=self.profile.path,
            output_base_dir=Path(self.output.text().strip()) if self.output.text().strip() else self.options["output_dir"],
            watch_waveforms=True, watch_every=self.stride.value(), stop_capture_on_watch_close=False,
        ))
        self.reserved_ips = set(self.group_ips)
        self.state.setText("正在连接")
        self.message = "正在启动采样组"
        self.count.setText("完整 0    缺板 0")
        self.set_cards({})
        self.set_busy(True)
        self.session.start()
        self.timer.start()
        self.updated.emit(True)

    def set_busy(self, busy):
        for widget in (self.group, self.output, self.stride):
            widget.setDisabled(busy)
        self.refresh_interlock()
        self.stop_button.setEnabled(busy)
        self.pause.setEnabled(busy or self.pause.isChecked())
        self.active_changed.emit(busy)

    def stop(self):
        if self.active:
            self.session.cancel.set()
            self.stop_button.setEnabled(False)
            self.state.setText("正在停止并收尾")
            self.updated.emit(False)

    def pause_changed(self, paused):
        self.pause.setText("恢复波形" if paused else "暂停波形")
        if not paused:
            self.displayed = self.latest
            self.pause.setEnabled(self.active)
        self.updated.emit(True)

    def poll(self):
        session = self.session
        finished = not session.is_alive()
        with session.lock:
            self.latest = dict(session.packets)
            progress, directory = session.progress, session.directory
        old = self.displayed.get(self.selected)
        if not self.pause.isChecked():
            self.displayed = self.latest
        if directory:
            self.message = str(directory)
            if self.stop_button.isEnabled():
                self.state.setText("采样中")
        if finished:
            session.join()
            self.timer.stop()
            self.session = None
            self.reserved_ips.clear()
            self.state.setText("采样失败" if session.error else "已结束")
            if session.error:
                self.message = session.error
            elif session.result:
                self.message = str(session.result.run_output_dir)
            self.set_busy(False)
        self.set_cards({s["name"]: s for s in progress.get("board_stats", {}).values()})
        self.count.setText(f"完整 {progress.get('complete_events', 0)}    缺板 {progress.get('partial_events', 0)}")
        self.updated.emit(old is not self.displayed.get(self.selected))

    def draw(self, scope):
        packet = self.displayed.get(self.selected)
        heading = self.selected or "多板采样"
        if packet is not None and packet is not self.decoded_packet:
            self.decoded_packet = packet
            try:
                frame = decode_tcp_sent_packet(packet.packet, source_file=Path("live.bin"),
                                               adc_length=int(self.profile.defaults.get("adc_length", 256)))
                self.traces = [(f"CH {i:02d}", y, bool(frame.hit_mask & (1 << i)))
                               for i, y in enumerate(frame.channels)]
                self.preview_error = ""
            except (RuntimeError, ValueError) as exc:
                self.traces = []
                self.preview_error = str(exc)
        traces = self.traces if packet else []
        if packet:
            heading += f"   /   事件 {packet.board_event_count}"
            if self.preview_error:
                heading += f"   ·   预览解码失败：{self.preview_error}"
        if self.pause.isChecked():
            heading += "   ·   波形已暂停"
        scope.display(heading, traces or [(f"CH {i:02d}", None, False) for i in range(16)])
