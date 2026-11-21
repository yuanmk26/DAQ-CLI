"""Single-board controls and the lifetime of one Qt workstation capture."""

import os
import threading
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtWidgets as W

from daq_cli.application.acquire_options import default_output_base_dir, resolve_single_acquire_options
from daq_cli.application.acquire_service import AcquireService
from daq_cli.application.config_models import board_profile_options
from daq_cli.application.profile_service import ProfileService
from daq_cli.infrastructure.tcp_sent_decode import decode_tcp_sent_packet
from daq_cli.qt_scope import label


class CaptureSession(threading.Thread):
    """The writer only publishes references; the preview consumes the latest packet."""

    def __init__(self, params, profile):
        super().__init__(name="qt-single-capture")
        self.params = params
        self.service = AcquireService(ProfileService(profile))
        self.cancel = threading.Event()
        self.writer_done = threading.Event()
        self.lock = threading.Lock()
        self.packet = None
        self.frame = None
        self.progress = None
        self.result = None
        self.error = ""
        self.preview_error = ""

    def accept_packet(self, packet):
        with self.lock:
            self.packet = packet

    def accept_progress(self, progress):
        with self.lock:
            self.progress = progress

    def decode_preview(self):
        while True:
            finished = self.writer_done.wait(0.05)
            with self.lock:
                packet, self.packet = self.packet, None
            if packet is not None:
                try:
                    frame = decode_tcp_sent_packet(packet, source_file=Path("live.bin"))
                    channels = [np.asarray(y, dtype=np.float32) if y is not None else None
                                for y in frame.channels]
                    with self.lock:
                        self.frame = (frame.event_count, frame.hit_mask, channels)
                        self.preview_error = ""
                except (ValueError, RuntimeError) as exc:
                    with self.lock:
                        self.preview_error = str(exc)
            if finished:
                return

    def run(self):
        decoder = threading.Thread(target=self.decode_preview, name="qt-single-preview")
        decoder.start()
        try:
            self.result = self.service.capture_single(
                **self.params, cancel_event=self.cancel,
                progress_callback=self.accept_progress, watch_frame_callback=self.accept_packet,
            )
        except Exception as exc:
            self.error = str(exc) or type(exc).__name__
        finally:
            self.writer_done.set()
            decoder.join()


class SingleCapturePane(W.QFrame):
    updated = QtCore.Signal(bool)
    active_changed = QtCore.Signal(bool)
    profile_changed = QtCore.Signal(object)

    def __init__(self, profile_path=None):
        super().__init__(objectName="panel")
        self.profile = None
        self.config_write_ip = None
        self.config_busy = False
        self.session = None
        self.displayed = None
        self.latest = None
        self.message = "请选择采样配置"
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.poll)
        side = W.QVBoxLayout(self)
        side.addWidget(label("单板采样", "section"))
        self.load = W.QPushButton("选择配置…")
        self.load.clicked.connect(self.choose_profile)
        side.addWidget(self.load)
        self.profile_label = label("尚未加载", "muted")
        side.addWidget(self.profile_label)
        self.form = W.QWidget()
        fields = W.QFormLayout(self.form)
        fields.setContentsMargins(0, 8, 0, 8)
        self.target = W.QComboBox()
        self.target.currentIndexChanged.connect(self.reset_display)
        self.events = W.QSpinBox()
        self.events.setRange(1, 2_147_483_647)
        self.storage = W.QComboBox()
        for name, value in (("聚合文件", "aggregate"), ("仅事例率", "rate"), ("逐事件", "legacy")):
            self.storage.addItem(name, value)
        self.stride = W.QSpinBox()
        self.stride.setRange(1, 2_147_483_647)
        for title, widget in (("目标板", self.target), ("事件数", self.events),
                              ("存储", self.storage), ("每 N 帧预览", self.stride)):
            fields.addRow(title, widget)
        side.addWidget(self.form)
        self.output = W.QLineEdit()
        self.output.setClearButtonEnabled(True)
        side.addWidget(label("输出目录"))
        side.addWidget(self.output)
        self.browse = W.QPushButton("选择目录…")
        self.browse.clicked.connect(self.choose_output)
        side.addWidget(self.browse)
        side.addStretch()
        side.addWidget(label("已采事件", "muted"))
        self.count = label("0", "title")
        side.addWidget(self.count)
        self.state = label("就绪", "section")
        side.addWidget(self.state)
        self.controls = W.QFrame(objectName="panel")
        bar = W.QHBoxLayout(self.controls)
        self.start = W.QPushButton("开始采样", objectName="primary")
        self.stop_button = W.QPushButton("停止采样")
        self.pause = W.QPushButton("暂停波形", checkable=True)
        self.pause.setToolTip("冻结当前波形，继续采样和写盘")
        self.start.clicked.connect(self.begin)
        self.stop_button.clicked.connect(self.stop)
        self.pause.toggled.connect(self.pause_changed)
        for button in (self.start, self.stop_button, self.pause):
            bar.addWidget(button)
        bar.addStretch()
        self.start.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.pause.setEnabled(False)
        path = profile_path or os.getenv("DAQ_PROFILE")
        if not path and Path("profiles/muon-imaging.yaml").is_file():
            path = Path("profiles/muon-imaging.yaml")
        if path:
            self.load_profile(path)

    @property
    def active(self):
        return self.session is not None

    def choose_profile(self):
        path, _ = W.QFileDialog.getOpenFileName(self, "选择采样配置", "", "YAML (*.yaml *.yml)")
        if path:
            self.load_profile(path)

    def load_profile(self, path):
        if self.active or self.config_busy:
            return
        try:
            profile = ProfileService().load_profile(path)
            options = resolve_single_acquire_options(defaults=profile.defaults)
            board_profile_options(profile.defaults)
            if not profile.devices:
                raise ValueError("配置中没有可用板卡")
        except Exception as exc:
            self.message = f"配置加载失败：{exc}"
            self.updated.emit(False)
            return
        self.profile, self.options = profile, options
        self.profile_label.setText(profile.path.name)
        self.profile_label.setToolTip(str(profile.path))
        self.target.clear()
        self.target.addItems(sorted(profile.devices))
        self.events.setValue(options["events"])
        self.stride.setValue(options["watch_every"] or 1)
        self.storage.setCurrentIndex(self.storage.findData(options["storage_mode"]))
        self.output.setText(str(options["output_dir"] or default_output_base_dir(profile) / "single"))
        self.profile_changed.emit(profile)
        self.reset_display()

    def choose_output(self):
        path = W.QFileDialog.getExistingDirectory(self, "选择采样输出目录", self.output.text())
        if path:
            self.output.setText(path)

    def reset_display(self):
        self.latest = self.displayed = None
        self.pause.setChecked(False)
        self.pause.setEnabled(False)
        self.message = "等待开始采样"
        self.state.setText("就绪")
        self.count.setText("0")
        self.refresh_interlock()
        self.updated.emit(True)

    def target_ip(self):
        device = self.profile.devices.get(self.target.currentText()) if self.profile else None
        return device.ip if device else None

    def refresh_interlock(self):
        ip = self.target_ip()
        blocked = bool(ip and ip == self.config_write_ip)
        self.start.setEnabled(bool(ip) and not self.active and not blocked)
        self.start.setToolTip("该板正在配置或标定" if blocked else "")
        self.load.setEnabled(not self.active and not self.config_busy)

    def begin(self):
        if self.active or not self.target_ip() or self.target_ip() == self.config_write_ip:
            return
        self.reset_display()
        path = self.output.text().strip()
        self.session = CaptureSession(dict(
            device_name=self.target.currentText(), profile_path=self.profile.path,
            events=self.events.value(), timeout_s=self.options["timeout_s"],
            outputs=self.options["outputs"], storage_mode=self.storage.currentData(),
            rate_interval_s=self.options["rate_interval_s"], watch_every=self.stride.value(),
            output_base_dir=Path(path) if path else self.options["output_dir"],
        ), self.profile)
        self.set_busy(True)
        self.state.setText("正在连接")
        self.session.start()
        self.timer.start()
        self.updated.emit(False)

    def set_busy(self, busy):
        for widget in (self.load, self.form, self.output, self.browse, self.start):
            widget.setDisabled(busy)
        self.stop_button.setEnabled(busy)
        self.pause.setEnabled(busy)
        self.refresh_interlock()
        self.active_changed.emit(busy)

    def stop(self):
        if self.session:
            self.session.cancel.set()
            self.stop_button.setEnabled(False)
            self.state.setText("正在停止并收尾")
            self.updated.emit(False)

    def pause_changed(self, paused):
        self.pause.setText("恢复波形" if paused else "暂停波形")
        if not paused:
            self.displayed = self.latest
            if not self.active:
                self.pause.setEnabled(False)
        self.updated.emit(True)

    def poll(self):
        session = self.session
        finished = not session.is_alive()
        with session.lock:
            progress, self.latest, preview_error = session.progress, session.frame, session.preview_error
        redraw = not self.pause.isChecked() and self.latest is not self.displayed
        if redraw:
            self.displayed = self.latest
        if progress:
            self.count.setText(f"{progress.captured_events} / {progress.requested_events}")
            self.message = str(progress.output_dir or "")
            if self.stop_button.isEnabled():
                self.state.setText("采样中")
        if preview_error:
            self.message += f"   ·   预览解码：{preview_error}"
        if finished:
            session.join()
            self.timer.stop()
            self.session = None
            if session.result:
                result = session.result
                self.state.setText("已完成" if result.captured_events == result.requested_events else "已停止")
                self.message = str(result.run_output_dir or "")
            else:
                self.state.setText("采样失败")
                self.message = f"{session.error}   {self.message if progress else ''}"
            self.set_busy(False)
            self.pause.setEnabled(self.pause.isChecked() and self.latest is not None)
        self.updated.emit(redraw)

    def draw(self, scope):
        frame = self.displayed
        count, mask, channels = frame if frame else (None, 0, [None] * 16)
        heading = self.target.currentText() or "单板采样"
        if count is not None:
            heading += f"   /   事件 {count}"
        if self.pause.isChecked():
            heading += "   ·   波形已暂停"
        scope.display(heading, [(f"CH {i:02d}", y, bool(mask & (1 << i)))
                                for i, y in enumerate(channels)])
