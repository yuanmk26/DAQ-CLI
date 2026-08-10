from dataclasses import dataclass, field
from pathlib import Path

from daq_cli.domain.device import DeviceConfig
from daq_cli.domain.group import GroupConfig
from daq_cli.domain.tcm import TcmConfig


@dataclass(slots=True)
class ProfileData:
    path: Path
    devices: dict[str, DeviceConfig] = field(default_factory=dict)
    groups: dict[str, GroupConfig] = field(default_factory=dict)
    tcm: dict[str, TcmConfig] = field(default_factory=dict)
    defaults: dict[str, object] = field(default_factory=dict)
