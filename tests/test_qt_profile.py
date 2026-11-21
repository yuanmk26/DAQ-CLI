import os
from pathlib import Path
from shutil import copyfile

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
pytest.importorskip("ruamel.yaml")
from PySide6 import QtCore, QtWidgets as W

from daq_cli.qt_profile import ProfileEditor
from daq_cli.qt_replay import Workstation


def test_edit_profile_from_workbench(tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    path = tmp_path / "setup.yaml"
    copyfile(Path(__file__).resolve().parents[1] / "profiles/muon-imaging.yaml", path)
    original = path.read_text(encoding="utf8")
    before = yaml.safe_load(original)
    window = Workstation(profile_path=path)
    window.show()
    def edit():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, ProfileEditor)
        dialog.boards.item(0, 2).setText("192.168.10.110")
        dialog.boards.item(len(before["devices"]), 2).setText("192.168.10.116")
        dialog.groups.removeRow(0)
        dialog.add_group("pair", {"devices": ["dev2", "dev4"], "tcm": "main"})
        dialog.save()
        if not dialog.changed:
            dialog.reject()

    try:
        QtCore.QTimer.singleShot(0, edit)
        window.profile_edit.click()
        assert window.single.profile.devices["dev1"].ip == "192.168.10.110"
        assert window.config.profile.tcm["main"].ip == "192.168.10.116"
        window.mode.setCurrentIndex(2)
        window.multi.group.setCurrentText("pair")
        assert list(window.multi.buttons) == ["dev2", "dev4"]
        assert window.multi.group.findText("two_board") == -1
        saved = path.read_text(encoding="utf8")
        after = yaml.safe_load(saved)
        assert before["defaults"] == after["defaults"]
        assert before["devices"]["dev1"]["tcp_port"] == after["devices"]["dev1"]["tcp_port"]
        for line in original.splitlines():
            if "#" in line:
                assert line[line.index("#"):] in saved
    finally:
        window.close()


def test_invalid_group_cancel_and_external_edit(tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    path = tmp_path / "setup.yaml"
    original = "devices: {a: {ip: 127.0.0.1}}\ntcm: {main: {ip: 127.0.0.2}}\n"
    path.write_text(original, encoding="utf8")
    dialog = ProfileEditor(path)
    dialog.add_board("ADC", "b")
    dialog.boards.item(2, 2).setText("invalid")
    dialog.save()
    assert "IPv4" in dialog.error.text()
    assert path.read_text(encoding="utf8") == original
    dialog.boards.item(2, 2).setText("127.0.0.3")
    dialog.add_group("both", {"devices": ["a", "b"], "tcm": "main"})
    dialog.boards.cellWidget(2, 3).setValue(0)
    dialog.save()
    assert "ID 重复" in dialog.error.text()
    dialog.boards.cellWidget(2, 3).setValue(1)
    dialog.save()
    assert yaml.safe_load(path.read_text())["groups"]["both"]["devices"] == ["a", "b"]
    dialog = ProfileEditor(path)
    disk = path.read_bytes()
    dialog.boards.selectRow(1)
    dialog.remove_board()
    dialog.reject()
    assert path.read_bytes() == disk
    dialog = ProfileEditor(path)
    path.write_bytes(disk + b"# updated\n")
    dialog.save()
    assert "其他程序" in dialog.error.text()
    assert path.read_bytes() == disk + b"# updated\n"
