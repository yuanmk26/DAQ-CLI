from pathlib import Path

from daq_cli.application.models import ProfileData
from daq_cli.infrastructure.config_loader import load_profile


class ProfileService:
    """Load and validate DAQ profile data."""

    def load_profile(self, profile_path: Path | str) -> ProfileData:
        return load_profile(Path(profile_path))
