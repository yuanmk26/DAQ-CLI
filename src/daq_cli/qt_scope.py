from PySide6 import QtCore, QtGui, QtWidgets as W
import pyqtgraph as pg


def label(text, style=None):
    item = W.QLabel(text)
    item.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    if style:
        item.setObjectName(style)
    return item


class WaveformScope(W.QFrame):
    view_changed = QtCore.Signal()

    def __init__(self):
        super().__init__(objectName="scope")
        scope_layout = W.QVBoxLayout(self)
        title_row = W.QHBoxLayout()
        self.scope_title = label("", "scopeTitle")
        title_row.addWidget(self.scope_title)
        title_row.addStretch()
        title_row.addWidget(label("纵轴 ADC  ·  横轴 采样点", "scopeNote"))
        self.channel = W.QComboBox()
        self.channel.addItems(["16 路总览"] + [f"放大 CH {i:02d}" for i in range(16)])
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
        self.channel.currentIndexChanged.connect(self._change_channel)

    def allow_comparison(self, enabled):
        with QtCore.QSignalBlocker(self.channel):
            self.channel.setCurrentIndex(0)
            while self.channel.count() > 17:
                self.channel.removeItem(17)
            if enabled:
                for first in range(0, 16, 4):
                    self.channel.addItem(f"四板对照 · CH {first:02d}–{first+3:02d}")
        self.chart_pages.setCurrentIndex(0)

    def _change_channel(self, selected):
        self.chart_pages.setCurrentIndex(int(1 <= selected <= 16))
        self.focus.enableAutoRange()
        self.view_changed.emit()

    def display(self, heading, traces):
        """Each trace is (label, channel samples or None, hit)."""
        self.scope_title.setText(heading)
        view = self.channel.currentIndex()
        for i, (title, y, hit) in enumerate(traces):
            if 1 <= view <= 16 and view != i+1:
                continue
            plot, curve = self.plots[i], self.curves[i]
            color = "#ffbf72" if hit else "#5cdbcb"
            if y is None:
                title += "   ·   无波形"
            if 1 <= view <= 16:
                plot, curve = self.focus, self.focus_curve
                plot.setTitle(title, color=color, size="9pt")
            elif self.plot_labels[i] != (hit, title):
                plot.setTitle(title, color=color, size="9pt")
                self.plot_labels[i] = (hit, title)
            curve.setData([] if y is None else y, pen=self.pens[hit])
