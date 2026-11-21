"""Qt configuration workflows with fake hardware and real session interlocks."""

import os
import threading
from types import SimpleNamespace as Record
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
from PySide6.QtWidgets import QApplication

from daq_cli.application.acquire_service import AcquireService
from daq_cli.application.board_service import BoardService
from daq_cli.application.tcm_service import TcmService
from daq_cli.qt_replay import Workstation
from test_qt_single_capture import wait_for


@pytest.fixture
def station(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "live.yaml"
    path.write_text("devices:\n  a: {ip: 127.0.0.1}\n  alias: {ip: 127.0.0.1}\n"
                    "  b: {ip: 127.0.0.2}\ntcm:\n  main: {ip: 127.0.0.3}\n"
                    "defaults: {trigger_mode: 9, trigger_position: 74}\n")
    w = Workstation(profile_path=path)
    w.show()
    w.config_toggle.click()
    yield w, app
    w.close()
    wait_for(app, lambda: w.config.task is None and not w.single.active)
    app.processEvents()


def board_readback():
    trigger = Record(trigger_mode=9, trigger_position=81, send_start_delay=30,
                     timestamp_clean_enabled=False, ext_trigger_enabled=True,
                     thresholds=(10, 20, 30, 40))
    tcp = Record(send_mode=1, integration_pre_samples=3, integration_post_samples=7)
    link = Record(enable=True, mask=15, polarity=15, debounce=200, pulse_width=20,
                  thresholds=[1234]*16)
    return Record(trigger=trigger, tcp_mode2=tcp, tcp=tcp, link=link)


def test_forms_apply_readback_and_draft_isolation(station):
    w, app = station
    panel = w.config
    form = panel.current_form()
    response = board_readback()
    assert form.values()["trigger_position"] == 74
    with patch.object(BoardService, "configure_board", return_value=Record(success=True)) as configure, \
         patch.object(BoardService, "read_board_config_summary", return_value=response):
        panel.write.click()
        wait_for(app, lambda: not panel.task)
    assert configure.call_args.args[0] == "a"
    assert configure.call_args.args[-1].trigger_position == 74
    assert form.snapshot["trigger_position"] == 81
    assert form.values()["trigger_position"] == 74
    panel.copy.click()
    assert form.values()["trigger_position"] == 81
    panel.target.setCurrentIndex(2)
    assert panel.current_form().values()["trigger_position"] == 74
    assert not panel.copy.isEnabled()
    panel.target.setCurrentIndex(0)
    assert panel.current_form() is form

    panel.tabs.setCurrentIndex(1)
    m9 = panel.current_form()
    calibration = Record(frames=9, channels=[Record(channel=i, baseline=2000+i) for i in range(16)])
    with patch.object(BoardService, "measure_tcm_link", return_value=Record(calibration=calibration)), \
         patch.object(BoardService, "configure_mode9", return_value=(None, response)) as write9:
        panel.calibrate.click()
        wait_for(app, lambda: not panel.task)
        write9.assert_not_called()
        assert m9.values()["thresholds"] == [1900+i for i in range(12)] + [2112,2113,2114,2115]
        panel.write.click()
        wait_for(app, lambda: not panel.task)
        assert write9.call_args.kwargs["thresholds"] == m9.values()["thresholds"]
        assert write9.call_args.kwargs["trigger_mode"] == 9
        assert m9.snapshot["thresholds"] == [1234]*16

    panel.target.setCurrentIndex(3)
    tcm = panel.current_form()
    tcm.fill({"coincidence_enabled": True, "group_masks": [3, 12, 0, 0]})
    status = Record(**tcm.values(), last_trigger_channels=3, trig_sticky=True,
                    coinc_timeout_sticky=False, pending=False, wide_pulse_active=False,
                    collected_count=2, grp_ok=3)
    with patch.object(TcmService, "configure_trigger") as write_tcm, \
         patch.object(TcmService, "read_trigger_config", return_value=status):
        panel.write.click()
        wait_for(app, lambda: not panel.task)
    assert write_tcm.call_args.args == ("main", w.single.profile.path)
    assert write_tcm.call_args.kwargs["group_masks"] == (3, 12, 0, 0)
    assert "0x03" in panel.report.toPlainText()


def test_bidirectional_lock_and_stop_cleanup(station):
    w, app = station
    panel, single = w.config, w.single
    release_config, release_capture = threading.Event(), threading.Event()
    def calibrate(*args, **kwargs):
        release_config.wait(5)
        raise ValueError("test calibration failure")

    def capture(**kwargs):
        release_capture.wait(5)
        return Record(captured_events=0, requested_events=1000, run_output_dir=None)

    with patch.object(BoardService, "measure_tcm_link", side_effect=calibrate) as measure, \
         patch.object(BoardService, "read_mode9", return_value=board_readback()) as read, \
         patch.object(BoardService, "configure_mode9") as write, \
         patch.object(AcquireService, "capture_single", side_effect=capture):
        panel.tabs.setCurrentIndex(1)
        panel.calibrate.click()
        try:
            assert not single.start.isEnabled()
            single.begin()
            assert not single.active
            single.target.setCurrentText("alias")
            assert not single.start.isEnabled()
            single.target.setCurrentText("b")
            assert single.start.isEnabled()
            single.begin()
        finally:
            release_config.set()
        wait_for(app, lambda: not panel.task)
        assert "test calibration failure" in panel.report.toPlainText()
        assert panel.write.isEnabled()
        panel.target.setCurrentIndex(2)
        panel.tabs.setCurrentIndex(1)
        assert not panel.calibrate.isEnabled() and not panel.write.isEnabled()
        panel.submit("write")
        panel.submit("calibrate")
        write.assert_not_called()
        assert measure.call_count == 1
        panel.read.click()
        wait_for(app, lambda: not panel.task)
        read.assert_called_once_with("b", single.profile.path)
        panel.target.setCurrentIndex(3)
        assert panel.write.isEnabled()
        panel.target.setCurrentIndex(2)
        single.stop()
        assert not panel.write.isEnabled()
        release_capture.set()
        wait_for(app, lambda: not single.active)
        assert panel.write.isEnabled() and single.start.isEnabled()
