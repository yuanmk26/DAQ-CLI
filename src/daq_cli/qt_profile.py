"""Edit the network addresses and acquisition groups of the loaded YAML profile."""

from copy import deepcopy
from io import StringIO
from ipaddress import IPv4Address
import ntpath
from pathlib import Path, PureWindowsPath

import yaml
from PySide6 import QtCore, QtWidgets as W
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap


def valid_name(name):
    reserved = ntpath.isreserved(name) if hasattr(ntpath, "isreserved") else PureWindowsPath(name).is_reserved()
    return (bool(name) and not reserved and not name.endswith(".")
            and not any(c in '<>:"/\\|?*' or ord(c) < 32 for c in name))


def new_table(headers):
    table = W.QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().hide()
    table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows)
    table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.ResizeToContents)
    return table


def locked_item(text):
    item = W.QTableWidgetItem(text)
    item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
    return item


class ProfileEditor(W.QDialog):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = Path(path).resolve()
        self.original = self.path.read_bytes()
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.document = self.yaml.load(self.original.decode("utf-8-sig"))
        self.changed = False
        self.setWindowTitle("板卡与采样组")
        self.resize(680, 490)
        layout = W.QVBoxLayout(self)
        filename = W.QLabel(str(self.path))
        filename.setWordWrap(True)
        layout.addWidget(filename)
        tabs = W.QTabWidget()
        layout.addWidget(tabs)
        self.boards = new_table(["类型", "名称", "IP 地址", "板卡 ID"])
        self.boards.horizontalHeader().setSectionResizeMode(2, W.QHeaderView.ResizeMode.Stretch)
        board_page = W.QWidget()
        board_layout = W.QVBoxLayout(board_page)
        board_layout.addWidget(self.boards)
        board_actions = W.QHBoxLayout()
        for kind in ("ADC", "TCM"):
            add_board = W.QPushButton(f"新增 {kind}")
            add_board.clicked.connect(lambda checked, k=kind: self.prompt_board(k))
            board_actions.addWidget(add_board)
        remove_board = W.QPushButton("移除选中板卡")
        remove_board.clicked.connect(self.remove_board)
        board_actions.addWidget(remove_board)
        board_actions.addStretch()
        board_layout.addLayout(board_actions)
        tabs.addTab(board_page, "板卡地址")
        for section, kind in (("devices", "ADC"), ("tcm", "TCM")):
            for name, board in (self.document.get(section) or {}).items():
                row = self.boards.rowCount()
                self.boards.insertRow(row)
                self.boards.setItem(row, 0, locked_item(kind))
                self.boards.setItem(row, 1, locked_item(name))
                self.boards.setItem(row, 2, W.QTableWidgetItem(str(board["ip"])))
                if kind == "ADC":
                    ident = W.QSpinBox()
                    ident.setRange(0, 31)
                    ident.setValue(int(board.get("board_id", 0)))
                    self.boards.setCellWidget(row, 3, ident)
                else:
                    self.boards.setItem(row, 3, locked_item("—"))

        groups_page = W.QWidget()
        group_layout = W.QVBoxLayout(groups_page)
        self.adcs = list(self.document["devices"])
        self.tcms = list(self.document.get("tcm") or {})
        self.groups = new_table(["组名", "TCM", *self.adcs])
        self.groups.horizontalHeader().setSectionResizeMode(0, W.QHeaderView.ResizeMode.Stretch)
        group_layout.addWidget(self.groups)
        for name, group in (self.document.get("groups") or {}).items():
            self.add_group(name, group)
        actions = W.QHBoxLayout()
        add = W.QPushButton("新增采样组")
        add.clicked.connect(lambda: self.add_group("", {}))
        remove = W.QPushButton("移除选中组")
        remove.clicked.connect(lambda: self.groups.removeRow(self.groups.currentRow()))
        actions.addWidget(add)
        actions.addWidget(remove)
        actions.addStretch()
        group_layout.addLayout(actions)
        tabs.addTab(groups_page, "多板采样组")

        self.error = W.QLabel()
        self.error.setStyleSheet("color: #a63828")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = W.QDialogButtonBox()
        buttons.addButton("保存并应用", W.QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("取消", W.QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def prompt_board(self, kind):
        name, ok = W.QInputDialog.getText(self, f"新增 {kind}", "板卡名称")
        if ok:
            self.add_board(kind, name.strip())

    def add_board(self, kind, name):
        names = self.adcs if kind == "ADC" else self.tcms
        if not valid_name(name) or name in names:
            self.error.setText("请输入唯一且可用作目录名的板卡名称")
            return
        self.error.clear()
        names.append(name)
        row = self.boards.rowCount()
        self.boards.insertRow(row)
        self.boards.setItem(row, 0, locked_item(kind))
        self.boards.setItem(row, 1, locked_item(name))
        ip = W.QTableWidgetItem("")
        self.boards.setItem(row, 2, ip)
        if kind == "ADC":
            used = {widget.value() for r in range(row) if (widget := self.boards.cellWidget(r, 3))}
            ident = W.QSpinBox()
            ident.setRange(0, 31)
            ident.setValue(next((i for i in range(32) if i not in used), 0))
            self.boards.setCellWidget(row, 3, ident)
            col = self.groups.columnCount()
            self.groups.insertColumn(col)
            self.groups.setHorizontalHeaderItem(col, W.QTableWidgetItem(name))
            for r in range(self.groups.rowCount()):
                self.set_member(r, col, False)
        else:
            self.boards.setItem(row, 3, locked_item("—"))
            for r in range(self.groups.rowCount()):
                self.groups.cellWidget(r, 1).addItem(name)
        self.boards.setCurrentItem(ip)
        self.boards.editItem(ip)

    def remove_board(self):
        row = self.boards.currentRow()
        if row < 0:
            return
        name = self.boards.item(row, 1).text()
        if self.boards.item(row, 0).text() == "ADC":
            self.groups.removeColumn(2 + self.adcs.index(name))
            self.adcs.remove(name)
        else:
            self.tcms.remove(name)
            for r in range(self.groups.rowCount()):
                combo = self.groups.cellWidget(r, 1)
                selected = combo.currentText() == name
                combo.removeItem(combo.findText(name))
                if selected:
                    combo.setCurrentIndex(-1)
        self.boards.removeRow(row)

    def set_member(self, row, col, checked):
        member = locked_item("")
        member.setFlags(member.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        member.setCheckState(QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked)
        self.groups.setItem(row, col, member)

    def add_group(self, name, group):
        row = self.groups.rowCount()
        self.groups.insertRow(row)
        item = W.QTableWidgetItem(name)
        item.setData(QtCore.Qt.ItemDataRole.UserRole, name)
        self.groups.setItem(row, 0, item)
        tcm = W.QComboBox()
        tcm.addItems(self.tcms)
        if group:
            tcm.setCurrentIndex(tcm.findText(str(group.get("tcm") or "")))
        self.groups.setCellWidget(row, 1, tcm)
        for col, board in enumerate(self.adcs, 2):
            self.set_member(row, col, board in group.get("devices", []))
        if not name:
            self.groups.setCurrentItem(item)
            self.groups.editItem(item)

    def edited_document(self):
        doc = deepcopy(self.document)
        if not self.adcs:
            raise ValueError("配置中至少需要一块 ADC")
        for key, names in (("devices", self.adcs), ("tcm", self.tcms)):
            for name in list(doc.get(key) or {}):
                if name not in names:
                    del doc[key][name]
        for row in range(self.boards.rowCount()):
            adc = self.boards.item(row, 0).text() == "ADC"
            name = self.boards.item(row, 1).text()
            # An alias in YAML can share an object with another board.
            key = "devices" if adc else "tcm"
            if doc.get(key) is None:
                doc[key] = CommentedMap()
            section = doc[key]
            entry = deepcopy(section.get(name, {}))
            try:
                entry["ip"] = str(IPv4Address(self.boards.item(row, 2).text().strip()))
            except ValueError as exc:
                raise ValueError(f"{name} 的 IPv4 地址无效") from exc
            if adc:
                ident = self.boards.cellWidget(row, 3).value()
                if ident != int(entry.get("board_id", 0)):
                    entry["board_id"] = ident
            if entry != section.get(name):
                section[name] = entry

        original = self.document.get("groups") or {}
        groups = CommentedMap()
        for row in range(self.groups.rowCount()):
            item = self.groups.item(row, 0)
            name = item.text().strip()
            if not valid_name(name) or name in groups:
                raise ValueError(f"第 {row + 1} 行需要唯一且可用作目录名的组名")
            old_name = item.data(QtCore.Qt.ItemDataRole.UserRole)
            group = deepcopy(original.get(old_name, {}))
            selected = [adc for col, adc in enumerate(self.adcs, 2)
                        if self.groups.item(row, col).checkState() == QtCore.Qt.CheckState.Checked]
            tcm = self.groups.cellWidget(row, 1).currentText()
            if not selected or not tcm:
                raise ValueError(f"{name} 需要至少一块 ADC 和一块 TCM")
            members = [adc for adc in group.get("devices", []) if adc in selected]
            members.extend(adc for adc in selected if adc not in members)
            boards = [doc["devices"][adc] for adc in members]
            if len({int(board.get("board_id", 0)) for board in boards}) != len(boards):
                raise ValueError(f"{name} 中的 ADC 板卡 ID 重复")
            if len({board["ip"] for board in boards}) != len(boards):
                raise ValueError(f"{name} 中的 ADC 地址重复")
            if group.get("devices") != members:
                if isinstance(group.get("devices"), list):
                    group["devices"][:] = members
                else:
                    group["devices"] = members
            group["tcm"] = tcm
            groups[name] = group
        if groups != original:
            if not isinstance(doc.get("groups"), dict):
                doc["groups"] = CommentedMap()
            for name in list(doc["groups"]):
                if name not in groups:
                    del doc["groups"][name]
            doc["groups"].update(groups)
        return doc

    def save(self):
        try:
            updated = self.edited_document()
            if self.path.read_bytes() != self.original:
                raise ValueError("配置文件已被其他程序修改，请取消并重新打开后再编辑")
            if updated != self.document:
                buffer = StringIO()
                self.yaml.dump(updated, buffer)
                data = buffer.getvalue()
                # Existing CLI/Tk readers use PyYAML's YAML 1.1 semantics.
                # Keep unrelated settings identical for those readers as well.
                old = yaml.safe_load(self.original)
                new = yaml.safe_load(data)
                for section in ("devices", "tcm", "groups"):
                    expected = updated.get(section) or {}
                    actual = new.get(section) or {}
                    if (actual.keys() != expected.keys() or
                            (section == "groups" and any(
                                actual[k]["devices"] != v["devices"] or actual[k]["tcm"] != v["tcm"]
                                for k, v in expected.items()))):
                        raise ValueError("名称被 YAML 识别为特殊值，请更换板卡或采样组名称")
                    old.pop(section, None)
                    new.pop(section, None)
                if old != new:
                    raise ValueError("此配置的其他字段在 YAML 转换时发生变化，已取消保存")
                if b"\r\n" in self.original:
                    data = data.replace("\n", "\r\n")
                payload = data.encode("utf-8-sig" if self.original.startswith(b"\xef\xbb\xbf") else "utf-8")
                target = QtCore.QSaveFile(str(self.path))
                if not target.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
                    raise OSError(target.errorString())
                if target.write(payload) != len(payload) or not target.commit():
                    raise OSError(target.errorString())
                self.changed = True
        except (ValueError, OSError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()
