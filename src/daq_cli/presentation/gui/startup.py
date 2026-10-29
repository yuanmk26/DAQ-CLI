"""Startup helpers for the GUI entry point.

Kept free of tkinter and matplotlib so it can be unit-tested without a
display and imported before the TkAgg backend is locked.
"""

from __future__ import annotations

import os
from pathlib import Path

# Explicit names checked next to the executable, in priority order.  A
# dedicated ``daq-profile.yaml`` lets a deployment override any template
# without relying on a ``profiles/`` directory.
_PROFILE_NAMES = (
    "daq-profile.yaml",
    "daq-profile.yml",
    "profile.yaml",
    "profile.yml",
)


def discover_profile(base: Path) -> Path | None:
    """Find a profile for a double-clicked executable.

    Search order:

    1. ``DAQ_PROFILE`` environment variable (absolute or CWD-relative);
    2. one of the explicit file names in *base*;
    3. exactly one ``*.yaml`` / ``*.yml`` under ``base/profiles/``.

    Returns ``None`` when nothing matches or the layout is ambiguous, so the
    GUI opens with the manual "加载 Profile" button instead of guessing.
    """
    env_path = os.environ.get("DAQ_PROFILE")
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.is_file():
            return candidate

    for name in _PROFILE_NAMES:
        candidate = base / name
        if candidate.is_file():
            return candidate

    profiles_dir = base / "profiles"
    if profiles_dir.is_dir():
        matches = sorted(profiles_dir.glob("*.yaml")) + sorted(
            profiles_dir.glob("*.yml")
        )
        if len(matches) == 1:
            return matches[0]
    return None
