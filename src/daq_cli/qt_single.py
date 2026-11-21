"""Independent single-board captures sharing the workstation waveform scope."""

import os
import threading
from dataclasses import dataclass
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


@dataclass
class BoardCapture:
    events: int
    storage_mode: str
    stride: int
    output: str
    session: CaptureSession | None = None
    latest: tuple | None = None
    displayed: tuple | None = None
    paused: bool = False
    count: int = 0
    requested: int = 0
    state: str = "就绪"
    message: str = "等待开始采样"


class SingleCapturePane(W.QFrame):
    updated = QtCore.Signal(bool)
    active_changed = QtCore.Signal(bool)
    profile_changed = QtCore.Signal(object)

    def __init__(self, profile_path=None):
        super().__init__(objectName="panel")
        self.profile = None
        self.config_write_ip = None
        self.config_busy = False
        self.boards = {}
        self.buttons = {}
        self.selected = ""
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
        self.cards = W.QVBoxLayout()
        side.addLayout(self.cards)
        self.form = W.QWidget()
        fields = W.QFormLayout(self.form)
        fields.setContentsMargins(0, 8, 0, 8)
        self.events = W.QSpinBox()
        self.events.setRange(1, 2_147_483_647)
        self.storage = W.QComboBox()
        for name, value in (("聚合文件", "aggregate"), ("仅事例率", "rate"), ("逐事件", "legacy")):
            self.storage.addItem(name, value)
        self.stride = W.QSpinBox()
        self.stride.setRange(1, 2_147_483_647)
        for title, widget in (("事件数", self.events),
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
        return any(board.session is not None for board in self.boards.values())

    @property
    def reserved_ips(self):
        return {self.profile.devices[name].ip for name, board in self.boards.items() if board.session}

    @property
    def displayed(self):
        board = self.boards.get(self.selected)
        return board.displayed if board else None

    @property
    def latest(self):
        board = self.boards.get(self.selected)
        return board.latest if board else None

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
        for button in self.buttons.values():
            self.cards.removeWidget(button)
            button.hide()
            button.deleteLater()
        self.boards.clear()
        self.buttons.clear()
        self.selected = ""
        output = str(options["output_dir"] or default_output_base_dir(profile) / "single")
        for name in sorted(profile.devices):
            self.boards[name] = BoardCapture(options["events"], options["storage_mode"],
                                             options["watch_every"] or 1, output)
            button = W.QPushButton(objectName="board", checkable=True)
            button.setToolTip(profile.devices[name].ip)
            button.clicked.connect(lambda checked, n=name: self.select_board(n))
            self.buttons[name] = button
            self.cards.addWidget(button)
            self.update_card(name)
        self.select_board(next(iter(self.boards)))
        self.profile_changed.emit(profile)

    def choose_output(self):
        path = W.QFileDialog.getExistingDirectory(self, "选择采样输出目录", self.output.text())
        if path:
            self.output.setText(path)

    def save_settings(self):
        board = self.boards[self.selected]
        board.events = self.events.value()
        board.storage_mode = self.storage.currentData()
        board.stride = self.stride.value()
        board.output = self.output.text()

    def select_board(self, name):
        if self.selected:
            self.save_settings()
            self.buttons[self.selected].setChecked(False)
        self.selected = name
        self.buttons[name].setChecked(True)
        board = self.boards[name]
        self.events.setValue(board.events)
        self.storage.setCurrentIndex(self.storage.findData(board.storage_mode))
        self.stride.setValue(board.stride)
        self.output.setText(board.output)
        with QtCore.QSignalBlocker(self.pause):
            self.pause.setChecked(board.paused)
        self.pause.setText("恢复波形" if board.paused else "暂停波形")
        self.refresh_interlock()
        self.show_selected(True)

    def update_card(self, name):
        board = self.boards[name]
        text = f"{name}    {board.state}\n{board.count} 事件"
        if board.paused:
            text += "   ·   波形已暂停"
        button = self.buttons[name]
        if button.text() != text:
            button.setText(text)

    def show_selected(self, redraw):
        board = self.boards[self.selected]
        self.state.setText(board.state)
        self.count.setText(f"{board.count} / {board.requested}" if board.requested else "0")
        self.message = board.message
        self.updated.emit(redraw)

    def refresh_interlock(self):
        board = self.boards.get(self.selected)
        ip = self.profile.devices[self.selected].ip if board else None
        blocked = bool(ip and (ip == self.config_write_ip or ip in self.reserved_ips))
        busy = bool(board and board.session)
        self.start.setEnabled(bool(board) and not blocked)
        self.start.setToolTip("该板正在采样、配置或标定" if blocked else "")
        self.stop_button.setEnabled(busy and not board.session.cancel.is_set())
        self.pause.setEnabled(busy or bool(board and board.paused))
        for widget in (self.form, self.output, self.browse):
            widget.setDisabled(busy)
        self.load.setEnabled(not self.active and not self.config_busy)

    def begin(self):
        if not self.selected:
            return
        ip = self.profile.devices[self.selected].ip
        if ip in self.reserved_ips or ip == self.config_write_ip:
            return
        self.save_settings()
        board = self.boards[self.selected]
        board.session = CaptureSession(dict(
            device_name=self.selected, profile_path=self.profile.path,
            events=board.events, timeout_s=self.options["timeout_s"],
            outputs=self.options["outputs"], storage_mode=board.storage_mode,
            rate_interval_s=self.options["rate_interval_s"], watch_every=board.stride,
            output_base_dir=Path(board.output.strip()) if board.output.strip() else self.options["output_dir"],
        ), self.profile)
        board.latest = board.displayed = None
        board.paused = False
        board.count = 0
        board.requested = board.events
        board.message = "正在启动采样"
        board.state = "正在连接"
        self.update_card(self.selected)
        with QtCore.QSignalBlocker(self.pause):
            self.pause.setChecked(False)
        self.pause.setText("暂停波形")
        self.refresh_interlock()
        self.show_selected(True)
        self.active_changed.emit(True)
        board.session.start()
        self.timer.start()

    def stop(self):
        if self.selected:
            self.stop_board(self.selected)

    def stop_board(self, name):
        board = self.boards[name]
        if board.session:
            board.session.cancel.set()
            board.state = "正在停止并收尾"
            self.update_card(name)
            if name == self.selected:
                self.refresh_interlock()
                self.show_selected(False)

    def stop_all(self):
        for name in self.boards:
            self.stop_board(name)

    def pause_changed(self, paused):
        board = self.boards[self.selected]
        board.paused = paused
        self.pause.setText("恢复波形" if paused else "暂停波形")
        if not paused:
            board.displayed = board.latest
        self.update_card(self.selected)
        self.refresh_interlock()
        self.updated.emit(True)

    def poll(self):
        redraw = False
        released = False
        for name, board in self.boards.items():
            session = board.session
            if session is None:
                continue
            finished = not session.is_alive()
            with session.lock:
                progress, board.latest, error = session.progress, session.frame, session.preview_error
            if not board.paused and board.latest is not board.displayed:
                board.displayed = board.latest
                if name == self.selected:
                    redraw = True
            if progress:
                board.count = progress.captured_events
                board.message = str(progress.output_dir or "")
                if not session.cancel.is_set():
                    board.state = "采样中"
                if error:
                    board.message += f"   ·   预览解码：{error}"
            if finished:
                session.join()
                board.session = None
                released = True
                if session.result:
                    result = session.result
                    board.count = result.captured_events
                    board.state = "已完成" if result.captured_events == result.requested_events else "已停止"
                    board.message = str(result.run_output_dir or "")
                else:
                    board.state = "采样失败"
                    board.message = f"{session.error}   {board.message if progress else ''}".strip()
            self.update_card(name)
        if released:
            if not self.active:
                self.timer.stop()
            self.refresh_interlock()
            self.active_changed.emit(self.active)
        self.show_selected(redraw)

    def draw(self, scope):
        frame = self.displayed
        count, mask, channels = frame if frame else (None, 0, [None] * 16)
        heading = self.selected or "单板采样"
        if count is not None:
            heading += f"   /   事件 {count}"
        if self.pause.isChecked():
            heading += "   ·   波形已暂停"
        scope.display(heading, [(f"CH {i:02d}", y, bool(mask & (1 << i)))
                                for i, y in enumerate(channels)])
