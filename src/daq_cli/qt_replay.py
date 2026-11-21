"""Offline Qt workstation for event-by-event inspection of an aggregated run."""

import argparse
from functools import lru_cache
from heapq import merge
from itertools import islice
from pathlib import Path
from time import monotonic

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets as W
import pyqtgraph as pg

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


def label(text, style=None):
    item = W.QLabel(text)
    item.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    if style:
        item.setObjectName(style)
    return item


class Workstation(W.QMainWindow):
    def __init__(self, replay):
        super().__init__()
        self.run = replay
        self.index = 0
        self.board = min(replay.boards)
        self.timer = QtCore.QTimer(self)
        self.timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.advance)
        self.playing = False
        self.setWindowTitle("DAQ · 四板波形回放")
        shell = W.QWidget(objectName="shell")
        self.setCentralWidget(shell)
        layout = W.QVBoxLayout(shell)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        header = W.QHBoxLayout()
        header.addWidget(label("DAQ  /  波形工作台", "title"))
        header.addSpacing(10)
        header.addWidget(label("离线回放", "tag"))
        header.addStretch()
        header.addWidget(label(replay.directory.name, "section"))
        header.addSpacing(8)
        header.addWidget(label(str(replay.meta.get("start_time", "")), "muted"))
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
        for board_id in sorted(replay.boards):
            button = W.QPushButton(objectName="board", checkable=True)
            self.group.addButton(button, board_id)
            self.board_buttons[board_id] = button
            side_layout.addWidget(button)
        self.board_buttons[self.board].setChecked(True)
        self.group.idClicked.connect(self.select_board)
        side_layout.addSpacing(12)
        side_layout.addWidget(label("TCM 对齐快照", "section"))
        snapshot = replay.meta.get("align_snapshot") or {}
        ack = snapshot.get("ack_mask")
        side_layout.addWidget(label(str(replay.meta.get("tcm_ip", "—")), "muted"))
        side_layout.addWidget(label(f"ACK     {ack:#06x}" if ack is not None else "ACK     —"))
        side_layout.addSpacing(10)
        side_layout.addWidget(label("当前板帧", "section"))
        self.board_detail = label("", "muted")
        side_layout.addWidget(self.board_detail)
        side_layout.addStretch()
        side_layout.addWidget(label("回放事件", "section"))
        complete = sum(e.event_kind == "complete" for e in replay.events)
        side_layout.addWidget(label(f"完整    {complete}      缺板    {len(replay.events)-complete}", "muted"))
        splitter.addWidget(side)

        scope = W.QFrame(objectName="scope")
        scope_layout = W.QVBoxLayout(scope)
        title_row = W.QHBoxLayout()
        self.scope_title = label("", "scopeTitle")
        title_row.addWidget(self.scope_title)
        title_row.addStretch()
        title_row.addWidget(label("纵轴 ADC  ·  横轴 采样点", "scopeNote"))
        self.channel = W.QComboBox()
        self.channel.addItems(["16 路总览"] + [f"放大 CH {i:02d}" for i in range(16)])
        if len(replay.boards) == 4:
            for first in range(0, 16, 4):
                self.channel.addItem(f"四板对照 · CH {first:02d}–{first+3:02d}")
        title_row.addWidget(self.channel)
        scope_layout.addLayout(title_row)
        self.canvas = pg.GraphicsLayoutWidget()
        self.canvas.setBackground("#12212c")
        self.chart_pages = W.QStackedWidget()
        scope_layout.addWidget(self.chart_pages, 1)
        self.chart_pages.addWidget(self.canvas)
        self.focus = pg.PlotWidget(background="#12212c")
        self.focus.setLabel("bottom", "采样点")
        self.focus.setLabel("left", "ADC")
        self.focus.showGrid(x=True, y=True, alpha=0.2)
        self.focus_curve = self.focus.plot()
        self.chart_pages.addWidget(self.focus)
        self.canvas.ci.layout.setContentsMargins(0, 0, 0, 0)
        self.canvas.ci.layout.setSpacing(4)
        self.plots = []
        self.curves = []
        self.plot_labels = [None] * 16
        self.pens = {False: pg.mkPen("#5cdbcb"), True: pg.mkPen("#ffbf72")}
        for i in range(16):
            plot = self.canvas.addPlot(row=i//4, col=i%4)
            plot.setMenuEnabled(False)
            plot.hideButtons()
            plot.showGrid(x=True, y=True, alpha=0.18)
            plot.setMouseEnabled(x=False, y=False)
            for axis_name in ("left", "bottom"):
                axis = plot.getAxis(axis_name)
                axis.setTextPen("#a0b7c4")
                axis.setPen("#38505c")
                axis.setStyle(tickFont=QtGui.QFont("Consolas", 8))
            plot.getAxis("left").setWidth(37)
            self.plots.append(plot)
            self.curves.append(plot.plot())
        self.channel.currentIndexChanged.connect(self.change_channel)
        splitter.addWidget(scope)
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
        self.slider.setRange(0, len(replay.events)-1)
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
        layout.addWidget(controls)
        self.status = label("", "muted")
        layout.addWidget(self.status)
        for key, action in (("Space", self.toggle), ("Left", lambda: self.seek(self.index-1)),
                            ("Right", lambda: self.seek(self.index+1))):
            QtGui.QShortcut(QtGui.QKeySequence(key), self, activated=action)
        for n, button in enumerate(self.board_buttons.values(), start=1):
            if n <= 9:
                QtGui.QShortcut(QtGui.QKeySequence(str(n)), self, activated=button.click)
                button.setToolTip(f"切换板卡 ({n})")
        self.play.setToolTip("播放 / 暂停 (空格)")
        self.setStyleSheet(STYLE)
        available = self.screen().availableGeometry()
        self.resize(min(1320, available.width()-32), min(820, available.height()-56))
        self.render()

    def select_board(self, board_id):
        self.board = board_id
        self.render()

    def change_channel(self, selected):
        self.chart_pages.setCurrentIndex(int(1 <= selected <= 16))
        self.focus.enableAutoRange()
        self.render()

    def seek(self, index):
        self.set_playing(False)
        self.index = max(0, min(index, len(self.run.events)-1))
        self.render()

    def toggle(self):
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
        view = self.channel.currentIndex()
        compare = view >= 17
        self.scope_title.setText("四板同步对照" if compare else
                                 f"{self.run.boards[self.board]['board_name']}   /   通道波形")
        board_ids = sorted(self.run.boards)
        for i, (plot, curve) in enumerate(zip(self.plots, self.curves)):
            if 1 <= view <= 16 and view != i+1:
                continue
            board_id = board_ids[i//4] if compare else self.board
            channel_id = (view-17)*4 + i%4 if compare else i
            y = self.run.channels(self.index, board_id)[channel_id]
            source = present.get(board_id)
            hit = bool(source and source.hit_mask & (1 << channel_id))
            color = "#ffbf72" if hit else "#5cdbcb"
            prefix = self.run.boards[board_id]["board_name"] + "   /   " if compare else ""
            title = f"{prefix}CH {channel_id:02d}" + ("   ·   无波形" if y is None else "")
            if 1 <= view <= 16:
                plot, curve = self.focus, self.focus_curve
                plot.setTitle(title, color=color, size="9pt")
            elif self.plot_labels[i] != (hit, title):
                plot.setTitle(title, color=color, size="9pt")
                self.plot_labels[i] = (hit, title)
            curve.setData([] if y is None else y, pen=self.pens[hit])
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
    parser = argparse.ArgumentParser(description="Qt 四板波形回放工作台")
    parser.add_argument("run_dir", nargs="?", type=Path, default=Path("samples/four_board_00001"))
    parser.add_argument("--limit", type=int, default=256, help="最多载入的事件数（默认 256）")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    try:
        replay = Replay(args.run_dir, args.limit)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"无法加载回放目录 {args.run_dir}: {exc}\n")
    app = W.QApplication([])
    app.setStyle("Fusion")
    window = Workstation(replay)
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
