from pathlib import Path

from daq_cli.application.models import ProfileData
from daq_cli.infrastructure.config_loader import load_profile


class ProfileService:
    """Load and validate DAQ profile data."""

    def __init__(self, loaded: ProfileData | None = None) -> None:
        self._loaded = loaded

    def load_profile(self, profile_path: Path | str) -> ProfileData:
        # A workstation operation uses the displayed device mapping until a
        # profile is explicitly reloaded, including every read in a write sequence.
        if self._loaded is not None and Path(profile_path) == self._loaded.path:
            return self._loaded
        return load_profile(Path(profile_path))
