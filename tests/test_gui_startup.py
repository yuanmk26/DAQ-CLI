from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daq_cli.presentation.gui.startup import discover_profile


class DiscoverProfileTests(unittest.TestCase):
    def test_explicit_name_wins_over_profiles_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "daq-profile.yaml").write_text("devices: {}\n", encoding="utf-8")
            profiles = base / "profiles"
            profiles.mkdir()
            (profiles / "other.yaml").write_text("devices: {}\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(discover_profile(base), base / "daq-profile.yaml")

    def test_single_profile_under_profiles_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            profiles = base / "profiles"
            profiles.mkdir()
            expected = profiles / "lab.yaml"
            expected.write_text("devices: {}\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(discover_profile(base), expected)

    def test_multiple_profiles_are_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            profiles = base / "profiles"
            profiles.mkdir()
            (profiles / "a.yaml").write_text("devices: {}\n", encoding="utf-8")
            (profiles / "b.yaml").write_text("devices: {}\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                self.assertIsNone(discover_profile(base))

    def test_env_var_overrides_directory_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "daq-profile.yaml").write_text("devices: {}\n", encoding="utf-8")
            chosen = base / "chosen.yaml"
            chosen.write_text("devices: {}\n", encoding="utf-8")
            with patch.dict(os.environ, {"DAQ_PROFILE": str(chosen)}, clear=True):
                self.assertEqual(discover_profile(base), chosen)

    def test_missing_env_path_falls_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            expected = base / "profile.yaml"
            expected.write_text("devices: {}\n", encoding="utf-8")
            with patch.dict(
                os.environ, {"DAQ_PROFILE": str(base / "missing.yaml")}, clear=True
            ):
                self.assertEqual(discover_profile(base), expected)

    def test_empty_directory_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {}, clear=True):
                self.assertIsNone(discover_profile(Path(tmp)))


if __name__ == "__main__":
    unittest.main()
