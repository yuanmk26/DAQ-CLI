from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from daq_cli.domain.device import DeviceConfig


@contextmanager
def temporary_sys_path(path: Path) -> Iterator[None]:
    path_str = str(path)
    original = list(sys.path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
    try:
        yield
    finally:
        sys.path[:] = original


@contextmanager
def device_environment(
    device: DeviceConfig, send_start_delay_us: float = 0.0
) -> Iterator[None]:
    keys = [
        "SITCP_DEVICE_NAME",
        "SITCP_DEVICE_IP",
        "SITCP_UDP_PORT",
        "SITCP_SEND_START_DELAY_US",
    ]
    saved = {key: os.environ.get(key) for key in keys}
    os.environ["SITCP_DEVICE_NAME"] = device.name
    os.environ["SITCP_DEVICE_IP"] = device.ip
    os.environ["SITCP_UDP_PORT"] = str(device.rbcp_port)
    os.environ["SITCP_SEND_START_DELAY_US"] = str(send_start_delay_us)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def clear_legacy_modules() -> None:
    module_names = [
        "start_16CH_two_board",
        "capture_tcp_sent_mode2",
        "FPGA_CTRL",
        "HMCAD1511",
        "mux",
        "si5345_16ch",
        "lib",
        "lib.rbcp",
        "lib.sysmon",
        "lib.i2c",
        "lib.spi_3wire",
    ]
    for module_name in module_names:
        sys.modules.pop(module_name, None)
