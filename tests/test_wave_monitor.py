import io
import unittest

import matplotlib

matplotlib.use("Agg")

from daq_cli.infrastructure.wave_monitor import (  # noqa: E402
    WaveMonitorError,
    load_demo_frames,
    load_repo_replay_sample,
    parse_replay_dump,
)
from daq_cli.presentation.wave_monitor_viewer import render_preview_image  # noqa: E402


class WaveMonitorTests(unittest.TestCase):
    def test_demo_frames_are_valid(self) -> None:
        frames = load_demo_frames()
        self.assertGreaterEqual(len(frames), 2)
        for frame in frames:
            self.assertEqual(len(frame.channels), 16)
            for channel in frame.channels:
                self.assertEqual(len(channel), 16)

    def test_repo_replay_sample_is_valid(self) -> None:
        frames = load_repo_replay_sample(device_name="sample")
        self.assertGreaterEqual(len(frames), 2)
        for frame in frames:
            self.assertEqual(len(frame.channels), 16)
            for channel in frame.channels:
                self.assertEqual(len(channel), 8)

    def test_parse_replay_dump_rejects_empty(self) -> None:
        from pathlib import Path

        empty_path = Path("README.md")
        with self.assertRaises(WaveMonitorError):
            parse_replay_dump(empty_path, device_name="empty")

    def test_preview_renderer_creates_image(self) -> None:
        frame = load_demo_frames()[0]
        output = io.BytesIO()
        render_preview_image(
            frame=frame,
            source_label="demo",
            output_path=output,
        )
        self.assertGreater(len(output.getvalue()), 0)


if __name__ == "__main__":
    unittest.main()
