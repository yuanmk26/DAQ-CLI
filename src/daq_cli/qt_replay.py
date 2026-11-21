"""Qt workstation for single-board capture and offline waveform replay."""

import argparse
from functools import lru_cache
from heapq import merge
from itertools import islice
from pathlib import Path
from time import monotonic

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets as W
from daq_cli.qt_scope import WaveformScope, label
from daq_cli.qt_single import SingleCapturePane

from daq_cli.infrastructure.multi_board_decode import (
    MultiBoardAggregatedEventReader, build_board_context, build_board_packet,
    load_multi_run_metadata,
)
from daq_cli.infrastructure.tcp_sent_decode import decode_tcp_sent_packet


class Replay:
    def __init__(self, directory: Path, limit: int):
        self.directory = directory
        self.meta = load_multi_run_metadata(directory)
        self.boards = build_board_context(self.meta)
        if not self.boards:
            raise ValueError("运行目录没有板卡信息")
        streams = []
        for kind in ("complete", "partial"):
            path = directory / f"{kind}_events.dat"
            if path.exists():
                streams.append(MultiBoardAggregatedEventReader(path, event_kind=kind).iter_events())
        ordered = merge(*streams, key=lambda event: event.flush_unix_ns)
        try:
            self.events = list(islice(ordered, limit))
        finally:
            for stream in streams:
                stream.close()
        if not self.events:
            raise ValueError("运行目录里没有可回放的事件")
        self.channels = lru_cache(maxsize=128)(self._decode)

    def _decode(self, index, board_id):
        event = self.events[index]
        chunk = next((b for b in event.boards if b.board_id == board_id), None)
        if chunk is None:
            return [None] * 16
        decoded = decode_tcp_sent_packet(build_board_packet(chunk), source_file=event.source_file,
                                         adc_length=int(self.meta["adc_length"]))
        return [np.asarray(y, dtype=np.float32) if y is not None else None
                for y in decoded.channels]


STYLE = """
QWidget { font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; color: #203445; }
QWidget#shell { background: #edf2f4; }
QFrame#panel { background: #ffffff; border: 1px solid #d2dee3; border-radius: 8px; }
QFrame#scope { background: #12212c; border-radius: 8px; }
QLabel#title { font-size: 22px; font-weight: 700; }
QLabel#section { font-size: 15px; font-weight: 700; }
QLabel#muted { color: #526c79; }
QLabel#scopeTitle { color: #eef6f7; font-size: 17px; font-weight: 700; }
QLabel#scopeNote { color: #adc7cf; }
QLabel#tag { background: #d7eeeb; color: #00685e; border-radius: 4px; padding: 3px 8px; }
QPushButton,QComboBox { background: #ffffff; border: 1px solid #bdcfd5; border-radius: 5px; padding: 5px 10px; }
QPushButton:hover,QComboBox:hover { border-color: #369488; background: #eff8f6; }
QPushButton:disabled { color: #9cadb4; background: #edf2f3; }
QPushButton#primary { background: #127a71; color: white; border-color: #127a71; font-weight: 600; }
QPushButton#board { text-align: left; padding: 8px; }
QPushButton#board:checked { background: #e4f4f1; border: 2px solid #268b7b; color: #095e55; }
QSlider::groove:horizontal { height: 4px; background: #d8e4e6; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #258879; }
QSlider::handle:horizontal { background: #11786e; width: 12px; margin: -5px 0; border-radius: 6px; }
"""


class Workstation(W.QMainWindow):
    def __init__(self, replay=None, profile_path=None):
        super().__init__()
        self.run = replay
        self.index = 0
        self.board = min(replay.boards) if replay else None
        self.timer = QtCore.QTimer(self)
        self.timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.advance)
        self.playing = False
        self.setWindowTitle("DAQ · 采样与回放工作台")
        shell = W.QWidget(objectName="shell")
        self.setCentralWidget(shell)
        layout = W.QVBoxLayout(shell)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        header = W.QHBoxLayout()
        header.addWidget(label("DAQ  /  波形工作台", "title"))
        header.addSpacing(10)
        self.mode = W.QComboBox()
        self.mode.addItems(["离线回放", "单板采样"])
        self.mode.model().item(0).setEnabled(replay is not None)
        header.addWidget(self.mode)
        header.addStretch()
        self.run_name = label("", "section")
        header.addWidget(self.run_name)
        header.addSpacing(8)
        self.run_time = label("", "muted")
        header.addWidget(self.run_time)
        layout.addLayout(header)

        splitter = W.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        side = W.QFrame(objectName="panel")
        side.setMinimumWidth(175)
        side_layout = W.QVBoxLayout(side)
        side_layout.setContentsMargins(12, 12, 12, 12)
        side_layout.addWidget(label("板卡总览", "section"))
        self.group = W.QButtonGroup(self)
        self.board_buttons = {}
        for board_id in sorted(replay.boards) if replay else []:
            button = W.QPushButton(objectName="board", checkable=True)
            self.group.addButton(button, board_id)
            self.board_buttons[board_id] = button
            side_layout.addWidget(button)
        if replay:
            self.board_buttons[self.board].setChecked(True)
        self.group.idClicked.connect(self.select_board)
        side_layout.addSpacing(12)
        side_layout.addWidget(label("TCM 对齐快照", "section"))
        meta = replay.meta if replay else {}
        snapshot = meta.get("align_snapshot") or {}
        ack = snapshot.get("ack_mask")
        side_layout.addWidget(label(str(meta.get("tcm_ip", "—")), "muted"))
        side_layout.addWidget(label(f"ACK     {ack:#06x}" if ack is not None else "ACK     —"))
        side_layout.addSpacing(10)
        side_layout.addWidget(label("当前板帧", "section"))
        self.board_detail = label("", "muted")
        side_layout.addWidget(self.board_detail)
        side_layout.addStretch()
        side_layout.addWidget(label("回放事件", "section"))
        complete = sum(e.event_kind == "complete" for e in replay.events) if replay else 0
        side_layout.addWidget(label(f"完整    {complete}      缺板    {len(replay.events)-complete if replay else 0}", "muted"))
        self.single = SingleCapturePane(profile_path)
        self.sides = W.QStackedWidget()
        self.sides.addWidget(side)
        self.sides.addWidget(self.single)
        splitter.addWidget(self.sides)

        self.scope = WaveformScope()
        self.scope.view_changed.connect(self.render)
        splitter.addWidget(self.scope)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([200, 1050])

        controls = W.QFrame(objectName="panel")
        bar = W.QHBoxLayout(controls)
        self.play = W.QPushButton("播放", objectName="primary")
        self.play.clicked.connect(self.toggle)
        self.back = W.QPushButton("上一帧")
        self.forward = W.QPushButton("下一帧")
        self.back.clicked.connect(lambda: self.seek(self.index-1))
        self.forward.clicked.connect(lambda: self.seek(self.index+1))
        for button in (self.play, self.back, self.forward):
            bar.addWidget(button)
        self.slider = W.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setRange(0, len(replay.events)-1 if replay else 0)
        self.slider.valueChanged.connect(self.seek)
        bar.addWidget(self.slider, 1)
        self.position = label("")
        bar.addWidget(self.position)
        self.speed = W.QComboBox()
        for speed in (0.25, 0.5, 1, 2, 4):
            self.speed.addItem(f"{speed:g}×", speed)
        self.speed.setCurrentIndex(2)
        self.speed.currentIndexChanged.connect(self.restart_clock)
        bar.addWidget(self.speed)
        self.loop = W.QCheckBox("循环")
        self.loop.setChecked(True)
        bar.addWidget(self.loop)
        self.bars = W.QStackedWidget()
        self.bars.addWidget(controls)
        self.bars.addWidget(self.single.controls)
        self.bars.setSizePolicy(W.QSizePolicy.Policy.Preferred, W.QSizePolicy.Policy.Maximum)
        layout.addWidget(self.bars)
        self.status = label("", "muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.replay_shortcuts = []
        for key, action in (("Space", self.toggle), ("Left", lambda: self.seek(self.index-1)),
                            ("Right", lambda: self.seek(self.index+1))):
            self.replay_shortcuts.append(QtGui.QShortcut(QtGui.QKeySequence(key), self, activated=action))
        for n, button in enumerate(self.board_buttons.values(), start=1):
            if n <= 9:
                self.replay_shortcuts.append(QtGui.QShortcut(QtGui.QKeySequence(str(n)), self, activated=button.click))
                button.setToolTip(f"切换板卡 ({n})")
        self.play.setToolTip("播放 / 暂停 (空格)")
        self.single.updated.connect(self.live_updated)
        self.single.active_changed.connect(self.capture_active_changed)
        self.closing = False
        self.mode.setCurrentIndex(0 if replay else 1)
        self.mode.currentIndexChanged.connect(self.switch_mode)
        self.setStyleSheet(STYLE)
        available = self.screen().availableGeometry()
        self.resize(min(1320, available.width()-32), min(820, available.height()-56))
        self.switch_mode(self.mode.currentIndex())

    def switch_mode(self, mode):
        self.set_playing(False)
        self.sides.setCurrentIndex(mode)
        self.bars.setCurrentIndex(mode)
        for shortcut in self.replay_shortcuts:
            shortcut.setEnabled(mode == 0)
        self.scope.allow_comparison(mode == 0 and len(self.run.boards) == 4)
        self.render()

    def live_updated(self, redraw):
        if self.mode.currentIndex() == 1:
            self.run_name.setText(self.single.target.currentText())
            self.run_time.setText(self.single.state.text())
            self.status.setText(self.single.message)
            if redraw:
                self.single.draw(self.scope)

    def capture_active_changed(self, active):
        self.mode.setDisabled(active)
        if self.closing and not active:
            QtCore.QTimer.singleShot(0, self.close)

    def closeEvent(self, event):
        if self.single.active:
            self.closing = True
            self.single.stop()
            event.ignore()
        else:
            event.accept()

    def select_board(self, board_id):
        self.board = board_id
        self.render()

    def seek(self, index):
        if self.mode.currentIndex():
            return
        self.set_playing(False)
        self.index = max(0, min(index, len(self.run.events)-1))
        self.render()

    def toggle(self):
        if self.mode.currentIndex():
            self.single.pause.click()
            return
        if not self.playing and self.index == len(self.run.events)-1:
            self.index = 0
            self.render()
        self.set_playing(not self.playing)

    def set_playing(self, playing):
        self.playing = playing
        self.play.setText("暂停" if playing else "播放")
        self.timer.stop()
        self.restart_clock()

    def restart_clock(self):
        self.deadline = monotonic()
        self.schedule()

    def schedule(self):
        if self.playing:
            events = self.run.events
            gap = 0.15 if self.index+1 == len(events) else (
                events[self.index+1].flush_unix_ns - events[self.index].flush_unix_ns
            ) / 1e9
            self.deadline += max(0, gap) / self.speed.currentData()
            delay_ms = round((self.deadline - monotonic()) * 1000)
            self.timer.start(max(1, min(2147483647, delay_ms)))

    def advance(self):
        if self.index+1 == len(self.run.events) and not self.loop.isChecked():
            self.set_playing(False)
            return
        self.index = (self.index+1) % len(self.run.events)
        self.render()
        self.schedule()

    def render(self):
        if self.mode.currentIndex() == 1:
            self.live_updated(True)
            return
        self.run_name.setText(self.run.directory.name)
        self.run_time.setText(str(self.run.meta.get("start_time", "")))
        event = self.run.events[self.index]
        present = {b.board_id: b for b in event.boards}
        for board_id, button in self.board_buttons.items():
            info = self.run.boards[board_id]
            chunk = present.get(board_id)
            state = f"命中 {chunk.hit_mask.bit_count():02d} 路" if chunk else "本帧缺板"
            board_text = f"{info['board_name']}     {state}\n{info['board_ip']}"
            if button.text() != board_text:
                button.setText(board_text)
        chunk = present.get(self.board)
        mask = chunk.hit_mask if chunk else 0
        self.board_detail.setText(
            f"发送模式    {chunk.mode}\n时间戳        {chunk.timestamp}\n事件计数    {chunk.event_count}"
            if chunk else "本事件无板帧"
        )
        view = self.scope.channel.currentIndex()
        compare = view >= 17
        heading = "四板同步对照" if compare else f"{self.run.boards[self.board]['board_name']}   /   通道波形"
        board_ids = sorted(self.run.boards)
        traces = []
        for i in range(16):
            board_id = board_ids[i//4] if compare else self.board
            channel_id = (view-17)*4 + i%4 if compare else i
            y = self.run.channels(self.index, board_id)[channel_id]
            source = present.get(board_id)
            hit = bool(source and source.hit_mask & (1 << channel_id))
            prefix = self.run.boards[board_id]["board_name"] + "   /   " if compare else ""
            traces.append((f"{prefix}CH {channel_id:02d}", y, hit))
        self.scope.display(heading, traces)
        with QtCore.QSignalBlocker(self.slider):
            self.slider.setValue(self.index)
        self.position.setText(f"{self.index+1} / {len(self.run.events)}")
        self.back.setEnabled(self.index > 0)
        self.forward.setEnabled(self.index+1 < len(self.run.events))
        kind = "完整" if event.event_kind == "complete" else "缺板"
        elapsed = (event.flush_unix_ns - self.run.events[0].flush_unix_ns) / 1e9
        self.status.setText(f"事件 {event.aggregate_seq}   ·   {kind}     |     "
                            f"板卡 {len(present)}/{len(self.run.boards)}     |     "
                            f"{self.run.boards[self.board]['board_name']} 掩码 "
                            f"{f'0x{mask:04X}' if chunk else '—'}     |     记录时间 +{elapsed:.3f} s")


def main():
    parser = argparse.ArgumentParser(description="Qt 单板采样与波形回放工作台")
    parser.add_argument("run_dir", nargs="?", type=Path, default=None)
    parser.add_argument("-p", "--profile", type=Path, help="单板采样配置文件")
    parser.add_argument("--limit", type=int, default=256, help="最多载入的事件数（默认 256）")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    try:
        default_run = Path("samples/four_board_00001")
        directory = args.run_dir or (default_run if default_run.is_dir() else None)
        replay = Replay(directory, args.limit) if directory else None
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"无法加载回放目录 {args.run_dir}: {exc}\n")
    app = W.QApplication([])
    app.setStyle("Fusion")
    window = Workstation(replay, args.profile)
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
