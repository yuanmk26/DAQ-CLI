from dataclasses import dataclass, field
from pathlib import Path

from daq_cli.domain.device import DeviceConfig
from daq_cli.domain.group import GroupConfig


@dataclass(slots=True)
class LegacyConfig:
    project_root: Path | None = None


@dataclass(slots=True)
class ProfileData:
    path: Path
    devices: dict[str, DeviceConfig] = field(default_factory=dict)
    groups: dict[str, GroupConfig] = field(default_factory=dict)
    tcm: dict[str, dict[str, object]] = field(default_factory=dict)
    defaults: dict[str, object] = field(default_factory=dict)
    legacy: LegacyConfig = field(default_factory=LegacyConfig)
