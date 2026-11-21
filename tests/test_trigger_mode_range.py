from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from daq_cli.application.config_models import BoardConfigOptions

_VENDOR_DIR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "daq_cli"
    / "_vendor"
    / "fdu_legacy"
)


def _load_fpga_ctrl():
    path = str(_VENDOR_DIR)
    inserted = path not in sys.path
    if inserted:
        sys.path.insert(0, path)
    try:
        return importlib.import_module("FPGA_CTRL")
    finally:
        if inserted:
            sys.path.remove(path)


class _FakeRbcp:
    def __init__(self) -> None:
        self.writes: list[tuple[int, bytes]] = []

    def write(self, address: int, data: bytes) -> None:
        self.writes.append((address, bytes(data)))


def test_trigger_mode_full_byte_accepted():
    for mode in (0, 9, 10, 11, 12, 255):
        assert BoardConfigOptions(trigger_mode=mode).trigger_mode == mode


@pytest.mark.parametrize("mode", [-1, 256, 1000])
def test_trigger_mode_out_of_byte_rejected(mode):
    with pytest.raises(ValueError):
        BoardConfigOptions(trigger_mode=mode)


def test_vendored_trigger_model_writes_full_byte():
    module = _load_fpga_ctrl()
    controller = module.FPGAControl.__new__(module.FPGAControl)
    controller.rbcp = _FakeRbcp()
    controller.trigger_model(11)
    controller.trigger_model(255)
    assert controller.rbcp.writes == [(0x10, b"\x0b"), (0x10, b"\xff")]


def test_vendored_trigger_model_rejects_above_byte():
    module = _load_fpga_ctrl()
    controller = module.FPGAControl.__new__(module.FPGAControl)
    controller.rbcp = _FakeRbcp()
    controller.trigger_model(256)
    assert controller.rbcp.writes == []
