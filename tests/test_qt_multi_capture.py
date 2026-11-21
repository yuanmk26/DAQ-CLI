"""Four simulated ADC streams exercise the native writer through the Qt controls."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_qt_single_capture import QApplication, ControlledStream, Workstation, wait_for
from test_acquire_single_monitoring import _build_tcp_sent_packet
from daq_cli.infrastructure.adapters.legacy_board_adapter import LegacyBoardAdapter
from daq_cli.infrastructure.multi_board_acquire.alignment import AlignSnapshot, TcmAlignController
from daq_cli.infrastructure.multi_board_decode import MultiBoardAggregatedEventReader


def test_four_board_pause_switch_store_and_unlock(tmp_path):
    app = QApplication.instance() or QApplication([])
    profile = tmp_path / "profile.yaml"
    profile.write_text("devices:\n" + "".join(
        f"  adc{i}: {{ip: 127.0.0.{i+1}, board_id: {i}}}\n" for i in range(5)
    ) + "tcm: {main: {ip: 127.0.0.6}}\ngroups:\n"
        "  four: {devices: [adc0, adc1, adc2, adc3], tcm: main}\n"
        "defaults:\n  acquire_multi: {aggregation_key: event_count, watch_every: 1, "
        "tcp_timeout_s: 0.1, event_timeout_ms: 2000}\n")
    w = Workstation(profile_path=profile)
    pane = w.multi
    w.mode.setCurrentIndex(2)
    pane.output.setText(str(tmp_path))
    streams = [ControlledStream() for _ in range(4)]

    def feed(event):
        packet = _build_tcp_sent_packet(1, 1, event)
        for stream in streams:
            stream.packets.put(packet)

    with patch.object(LegacyBoardAdapter, "read_tcp_mode2_config", return_value=SimpleNamespace(send_mode=1)), \
         patch.object(TcmAlignController, "align", return_value=(True, AlignSnapshot(2, 15, 15, 0))), \
         patch("daq_cli.infrastructure.multi_board_acquire.receiver._default_socket_factory", side_effect=streams):
        try:
            pane.start.click()
            for i in range(w.config.target.count()):
                w.config.target.setCurrentIndex(i)
                assert w.config.read.isEnabled()
                assert w.config.write.isEnabled() == (w.config.target.currentData()[1] == "adc4")
                if w.config.target.currentData()[0] == "ADC":
                    w.config.tabs.setCurrentIndex(1)
                    assert w.config.calibrate.isEnabled() == (w.config.target.currentData()[1] == "adc4")
            feed(1)
            wait_for(app, lambda: len(pane.displayed) == 4 and pane.count.text().startswith("完整 1 "))
            data = Path(pane.message) / "complete_events.dat"
            size = data.stat().st_size
            pane.pause.click()
            feed(2)
            wait_for(app, lambda: pane.count.text().startswith("完整 2 "))
            assert data.stat().st_size > size
            for name, button in pane.buttons.items():
                button.click()
                assert w.scope.scope_title.text().startswith(name)
                assert pane.displayed[name].board_event_count == 1
                assert len(w.scope.curves[15].getData()[1]) == 512
                assert "2 帧" in button.text()
            pane.pause.click()
            assert pane.displayed[pane.selected].board_event_count == 2
            pane.stop_button.click()
            assert not w.config.write.isEnabled()
            wait_for(app, lambda: not pane.active)
            assert w.config.write.isEnabled() and pane.start.isEnabled()
            events = list(MultiBoardAggregatedEventReader(data, event_kind="complete").iter_events())
            assert [len(event.boards) for event in events] == [4, 4]
        finally:
            pane.stop()
            wait_for(app, lambda: not pane.active)
            w.close()
