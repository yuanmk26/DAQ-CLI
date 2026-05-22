from pathlib import Path

import yaml

from daq_cli.application.models import LegacyConfig, ProfileData
from daq_cli.domain.device import DeviceConfig
from daq_cli.domain.group import GroupConfig


def load_profile(profile_path: Path | str) -> ProfileData:
    profile_path = Path(profile_path)
    with profile_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    devices = {}
    for name, item in (raw.get("devices") or {}).items():
        devices[name] = DeviceConfig(
            name=name,
            ip=str(item["ip"]),
            rbcp_port=int(item.get("rbcp_port", 4660)),
            tcp_port=int(item.get("tcp_port", 24)),
            board_id=int(item.get("board_id", 0)),
            role=str(item["role"]) if item.get("role") is not None else None,
        )

    groups = {}
    for name, item in (raw.get("groups") or {}).items():
        groups[name] = GroupConfig(
            name=name,
            devices=[str(device) for device in item.get("devices", [])],
            tcm=str(item["tcm"]) if item.get("tcm") is not None else None,
        )

    legacy = LegacyConfig()
    legacy_raw = raw.get("legacy") or {}
    if legacy_raw.get("project_root"):
        legacy.project_root = Path(str(legacy_raw["project_root"]))

    return ProfileData(
        path=profile_path,
        devices=devices,
        groups=groups,
        tcm=dict(raw.get("tcm") or {}),
        defaults=dict(raw.get("defaults") or {}),
        legacy=legacy,
    )
