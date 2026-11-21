"""Exercise the workstation with the real stream reader and aggregate writer."""

import json
import os
from pathlib import Path
import queue
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
from PySide6.QtWidgets import QApplication

from daq_cli.infrastructure.adapters.legacy_board_adapter import LegacyBoardAdapter
from daq_cli.infrastructure.adapters.legacy_capture_runner import LegacySingleCaptureRunner
from daq_cli.infrastructure.multi_board_decode import MultiBoardAggregatedEventReader
from daq_cli.qt_replay import Replay, Workstation
from test_acquire_single_monitoring import FakeSocket, _build_tcp_sent_packet


class ControlledStream(FakeSocket):
    def __init__(self):
        super().__init__([])
        self.packets = queue.Queue()
        self.timeout = 1.0

    def settimeout(self, timeout):
        self.timeout = timeout

    def recv(self, _size):
        try:
            return self.packets.get(timeout=self.timeout)
        except queue.Empty:
            raise TimeoutError from None


def wait_for(app, check):
    deadline = time.monotonic() + 5
    while not check():
        app.processEvents()
        time.sleep(0.005)
        assert time.monotonic() < deadline, "Qt session timed out"


def test_pause_storage_stop_restart_and_replay(tmp_path):
    app = QApplication.instance() or QApplication([])
    profile = tmp_path / "profile.yaml"
    profile.write_text("devices:\n  board: {ip: 127.0.0.1}\n"
                       "defaults:\n  acquire_single: {events: 20, timeout_s: 10}\n")
    window = Workstation(profile_path=profile)
    pane = window.single
    pane.output.setText(str(tmp_path / "runs"))
    first, second = ControlledStream(), ControlledStream()
    packet = _build_tcp_sent_packet(send_mode=1, hit_mask=1, event_count=1)
    try:
        with patch.object(LegacyBoardAdapter, "read_tcp_mode2_config",
                          return_value=SimpleNamespace(send_mode=1)), patch.object(
            LegacySingleCaptureRunner, "_open_socket", side_effect=[first, second],
        ):
            pane.start.click()
            assert not window.mode.isEnabled() and not pane.start.isEnabled()
            first.packets.put(packet)
            wait_for(app, lambda: pane.displayed is not None)
            first_dir = Path(pane.message)
            data = first_dir / "complete_events.dat"
            size = data.stat().st_size
            pane.pause.click()
            frozen = pane.displayed
            for event in range(2, 6):
                first.packets.put(_build_tcp_sent_packet(1, 1, event))
            wait_for(app, lambda: pane.count.text().startswith("5 /") and pane.latest[0] == 5)
            assert pane.displayed is frozen
            assert data.stat().st_size > size
            pane.pause.click()
            assert pane.displayed[0] == 5
            # The stream is idle, with a ten-second timeout. Stop should still finish promptly.
            pane.stop_button.click()
            assert not pane.start.isEnabled()
            wait_for(app, lambda: not pane.active)
            assert pane.state.text() == "已停止"
            assert json.loads((first_dir / "run_meta.json").read_text())["status"] == "stopped"
            assert len(list(MultiBoardAggregatedEventReader(data, event_kind="complete").iter_events())) == 5
            pane.events.setValue(2)
            pane.start.click()
            second.packets.put(packet * 2)
            wait_for(app, lambda: not pane.active)
            assert pane.state.text() == "已完成"
            second_dir = Path(pane.message)
            assert second_dir != first_dir
            replay = Replay(second_dir, 20)
            assert len(replay.events) == 2
            assert (replay.channels(1, 0)[0] == pane.displayed[2][0]).all()
            assert pane.start.isEnabled() and window.mode.isEnabled()
            viewer = Workstation(replay, profile)
            try:
                curve = viewer.scope.curves[0]
                assert (curve.getData()[1] == pane.displayed[2][0]).all()
                viewer.mode.setCurrentIndex(1)
                assert curve.getData()[1] is None or not curve.getData()[1].size
                viewer.mode.setCurrentIndex(0)
                assert (curve.getData()[1] == pane.displayed[2][0]).all()
            finally:
                viewer.close()
    finally:
        if pane.active:
            pane.stop()
            wait_for(app, lambda: not pane.active)
        window.close()


@pytest.mark.parametrize("storage", ["legacy", "rate"])
def test_retry_after_connect_failure_and_close_during_capture(tmp_path, storage):
    app = QApplication.instance() or QApplication([])
    profile = tmp_path / "profile.yaml"
    profile.write_text("devices:\n  board: {ip: 127.0.0.1}\n")
    window = Workstation(profile_path=profile)
    pane = window.single
    pane.storage.setCurrentIndex(pane.storage.findData(storage))
    pane.output.setText(str(tmp_path / "runs"))
    stream = ControlledStream()
    with patch.object(LegacyBoardAdapter, "read_tcp_mode2_config", side_effect=[
        OSError("test connection failure"), SimpleNamespace(send_mode=1)
    ]), patch.object(LegacySingleCaptureRunner, "_open_socket", return_value=stream):
        pane.start.click()
        wait_for(app, lambda: not pane.active)
        assert "test connection failure" in pane.message and pane.start.isEnabled()
        pane.start.click()
        stream.packets.put(_build_tcp_sent_packet(1, 1, 7))
        wait_for(app, lambda: pane.displayed is not None)
        directory = Path(pane.message)
        window.close()
        assert window.closing and not pane.start.isEnabled()
        wait_for(app, lambda: not pane.active)
        assert pane.state.text() == "已停止" and stream.closed
        if storage == "rate":
            assert (directory / "rate.csv").is_file()
            assert not (directory / "complete_events.dat").exists()
        else:
            assert len(list((directory / "raw").glob("*.bin"))) == 1


def test_concurrent_boards_pause_stop_restart_and_close(tmp_path):
    app = QApplication.instance() or QApplication([])
    profile = tmp_path / "profile.yaml"
    profile.write_text("devices:\n  a: {ip: 127.0.0.1}\n  alias: {ip: 127.0.0.1}\n"
                       "  b: {ip: 127.0.0.2}\n")
    window = Workstation(profile_path=profile)
    pane = window.single
    panel = window.config
    a, b, restarted = ControlledStream(), ControlledStream(), ControlledStream()
    runs = iter([a, restarted])
    def open_stream(device, timeout_s):
        return next(runs) if device.name == "a" else b

    def send(stream, event):
        stream.packets.put(_build_tcp_sent_packet(1, 1, event))

    def check_file(directory, expected_events):
        reader = MultiBoardAggregatedEventReader(directory / "complete_events.dat", event_kind="complete")
        assert [event.boards[0].event_count for event in reader.iter_events()] == expected_events

    with patch.object(LegacyBoardAdapter, "read_tcp_mode2_config", return_value=SimpleNamespace(send_mode=1)), \
         patch.object(LegacySingleCaptureRunner, "_open_socket", side_effect=open_stream):
        try:
            pane.events.setValue(20)
            pane.output.setText(str(tmp_path / "a"))
            pane.start.click()
            send(a, 10)
            wait_for(app, lambda: pane.displayed is not None)
            a_dir = Path(pane.message)
            pane.pause.click()
            size = (a_dir / "complete_events.dat").stat().st_size
            pane.buttons["alias"].click()
            assert not pane.start.isEnabled()
            pane.buttons["b"].click()
            assert pane.start.isEnabled() and not pane.pause.isChecked()
            pane.events.setValue(15)
            pane.output.setText(str(tmp_path / "b"))
            pane.start.click()
            send(b, 40)
            send(a, 11)
            wait_for(app, lambda: pane.boards["a"].count == 2 and pane.displayed is not None)
            assert pane.displayed[0] == 40 and "b" in window.scope.scope_title.text()
            assert "2 事件" in pane.buttons["a"].text()
            assert (a_dir / "complete_events.dat").stat().st_size > size
            b_dir = Path(pane.message)
            assert b_dir.parent != a_dir.parent
            for i in range(3):
                panel.target.setCurrentIndex(i)
                panel.tabs.setCurrentIndex(1)
                assert panel.read.isEnabled() and not panel.write.isEnabled() and not panel.calibrate.isEnabled()
            pane.buttons["a"].click()
            assert pane.pause.isChecked() and pane.displayed[0] == 10
            assert pane.events.value() == 20 and pane.output.text() == str(a_dir.parent)
            pane.pause.click()
            assert pane.displayed[0] == 11
            pane.stop_button.click()
            wait_for(app, lambda: pane.start.isEnabled())
            assert pane.active and not window.mode.isEnabled()
            panel.target.setCurrentIndex(0)
            assert panel.write.isEnabled()
            send(b, 41)
            wait_for(app, lambda: pane.boards["b"].count == 2)
            check_file(a_dir, [10, 11])
            pane.start.click()
            send(restarted, 19)
            wait_for(app, lambda: pane.displayed is not None)
            restarted_dir = Path(pane.message)
            assert restarted_dir != a_dir
            window.close()
            wait_for(app, lambda: not pane.active)
            assert restarted.closed and b.closed
            check_file(restarted_dir, [19])
            check_file(b_dir, [40, 41])
        finally:
            pane.stop_all()
            wait_for(app, lambda: not pane.active)
            window.close()


@pytest.mark.parametrize("restore_failure", [False, True])
def test_monitor_alongside_capture_and_restore(tmp_path, restore_failure):
    from PySide6.QtWidgets import QMessageBox
    from daq_cli.infrastructure.wave_monitor import LiveWaveMonitorSource, WaveMonitorFrame
    import threading

    app = QApplication.instance() or QApplication([])
    profile = tmp_path / "profile.yaml"
    profile.write_text("devices:\n  a: {ip: 127.0.0.1}\n  alias: {ip: 127.0.0.1}\n"
                       "  b: {ip: 127.0.0.2}\n")
    window = Workstation(profile_path=profile)
    window.show()
    pane, panel = window.single, window.config
    monitor_dir = tmp_path / "monitor"
    pane.output.setText(str(monitor_dir))
    frames = queue.Queue()
    restoring, release = threading.Event(), threading.Event()
    modes = {"a": 3, "b": 1}
    stream = ControlledStream()

    def write_mode(device, mode):
        if mode == 3:
            restoring.set()
            release.wait(4)
            if restore_failure:
                return  # Simulate a write acknowledged with the wrong readback.
        modes[device.name] = mode

    def receive(source, stop_event):
        while not stop_event.is_set():
            try:
                event = frames.get(timeout=0.02)
            except queue.Empty:
                continue
            yield WaveMonitorFrame("a", event, 100, 1, 1, [[event, 5]] * 16)

    with patch.object(LegacyBoardAdapter, "read_tcp_mode2_config",
                      side_effect=lambda d: SimpleNamespace(send_mode=modes[d.name])), \
         patch.object(LegacyBoardAdapter, "write_send_mode", side_effect=write_mode), \
         patch.object(LiveWaveMonitorSource, "frames", receive), \
         patch.object(LegacySingleCaptureRunner, "_open_socket", return_value=stream):
        try:
            pane.monitor.click()
            frames.put(7)
            wait_for(app, lambda: pane.displayed is not None)
            assert modes["a"] == 1 and pane.state.text() == "监视中"
            panel.tabs.setCurrentIndex(1)
            assert not panel.write.isEnabled() and not panel.calibrate.isEnabled()
            assert panel.read.isEnabled()
            pane.pause.click()
            frames.put(8)
            wait_for(app, lambda: pane.latest[0] == 8)
            assert pane.displayed[0] == 7
            pane.buttons["alias"].click()
            assert not pane.monitor.isEnabled() and not pane.start.isEnabled()
            pane.buttons["b"].click()
            pane.output.setText(str(tmp_path / "runs"))
            pane.start.click()
            stream.packets.put(_build_tcp_sent_packet(1, 1, 42))
            wait_for(app, lambda: pane.displayed is not None)
            recorded = Path(pane.message) / "complete_events.dat"
            pane.buttons["a"].click()
            pane.pause.click()
            assert pane.displayed[0] == 8
            if restore_failure:
                window.close()
            else:
                pane.stop_button.click()
            wait_for(app, restoring.is_set)
            assert "127.0.0.1" in pane.reserved_ips and not panel.write.isEnabled()
            release.set()
            wait_for(app, lambda: pane.boards["a"].session is None)
            assert not monitor_dir.exists() and panel.write.isEnabled()
            if restore_failure:
                notices = window.findChildren(QMessageBox)
                assert any(n.isVisible() and "a：恢复原发送模式 3 失败" in n.text() for n in notices)
                assert window.isVisible() and not window.closing
            else:
                assert modes["a"] == 3 and pane.start.isEnabled()
                assert pane.boards["b"].session is not None
            window.close()
            wait_for(app, lambda: not pane.active)
            assert len(list(MultiBoardAggregatedEventReader(recorded, event_kind="complete").iter_events())) == 1
        finally:
            release.set()
            pane.stop_all()
            wait_for(app, lambda: not pane.active)
            window.close()
