import io
import unittest
from unittest.mock import patch

import matplotlib
import matplotlib.pyplot as plt

matplotlib.use("Agg")

from daq_cli.infrastructure.wave_monitor import (  # noqa: E402
    WaveMonitorError,
    load_demo_frames,
    load_repo_replay_sample,
    parse_replay_dump,
)
from daq_cli.presentation.wave_monitor_viewer import (  # noqa: E402
    DEFAULT_FIGSIZE,
    _format_multi_board_title,
    WaveMonitorFigure,
    WaveMonitorLoopState,
    WaveMonitorRunState,
    _compute_default_figsize,
    _disconnect_default_key_handler,
    _advance_loop_state,
    render_preview_image,
)


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

    def test_figure_title_includes_run_state(self) -> None:
        frame = load_demo_frames()[0]
        figure = WaveMonitorFigure(source_label="demo")
        try:
            figure.update(frame, run_state=WaveMonitorRunState.RUN)
            title = figure.figure._suptitle.get_text()
            self.assertIn("state=RUN", title)
            self.assertIn("source=demo", title)
        finally:
            plt.close(figure.figure)

    def test_figure_title_includes_single_armed_state_without_frame(self) -> None:
        figure = WaveMonitorFigure(source_label="demo")
        try:
            figure.set_state(WaveMonitorRunState.SINGLE_ARMED)
            title = figure.figure._suptitle.get_text()
            self.assertIn("state=SINGLE-ARMED", title)
            self.assertIn("no frame yet", title)
        finally:
            plt.close(figure.figure)

    def test_run_state_updates_last_frame_and_requests_render(self) -> None:
        frame = load_demo_frames()[0]
        result = _advance_loop_state(
            WaveMonitorLoopState(run_state=WaveMonitorRunState.RUN),
            latest_frame=frame,
        )
        self.assertTrue(result.should_render)
        self.assertEqual(result.loop_state.run_state, WaveMonitorRunState.RUN)
        self.assertIs(result.loop_state.last_frame, frame)

    def test_stop_state_discards_new_frame_for_display(self) -> None:
        first_frame, next_frame = load_demo_frames()[:2]
        result = _advance_loop_state(
            WaveMonitorLoopState(
                run_state=WaveMonitorRunState.STOP,
                last_frame=first_frame,
            ),
            latest_frame=next_frame,
        )
        self.assertFalse(result.should_render)
        self.assertEqual(result.loop_state.run_state, WaveMonitorRunState.STOP)
        self.assertIs(result.loop_state.last_frame, first_frame)

    def test_single_armed_renders_next_frame_and_returns_to_stop(self) -> None:
        first_frame, next_frame = load_demo_frames()[:2]
        result = _advance_loop_state(
            WaveMonitorLoopState(
                run_state=WaveMonitorRunState.SINGLE_ARMED,
                last_frame=first_frame,
            ),
            latest_frame=next_frame,
        )
        self.assertTrue(result.should_render)
        self.assertEqual(result.loop_state.run_state, WaveMonitorRunState.STOP)
        self.assertIs(result.loop_state.last_frame, next_frame)

    def test_disconnect_default_key_handler_disconnects_known_handler(self) -> None:
        disconnected = []

        class DummyCanvas:
            def __init__(self) -> None:
                self.manager = type("Manager", (), {"key_press_handler_id": 42})()

            def mpl_disconnect(self, handler_id) -> None:
                disconnected.append(handler_id)

        dummy_figure = type("Figure", (), {"canvas": DummyCanvas()})()
        _disconnect_default_key_handler(dummy_figure)
        self.assertEqual(disconnected, [42])

    def test_compute_default_figsize_scales_down_to_fit_screen(self) -> None:
        with patch(
            "daq_cli.presentation.wave_monitor_viewer._get_screen_size_px",
            return_value=(1280, 720),
        ):
            width_in, height_in = _compute_default_figsize()
        self.assertLess(width_in, DEFAULT_FIGSIZE[0])
        self.assertLess(height_in, DEFAULT_FIGSIZE[1])

    def test_compute_default_figsize_falls_back_without_screen_size(self) -> None:
        with patch(
            "daq_cli.presentation.wave_monitor_viewer._get_screen_size_px",
            return_value=None,
        ):
            self.assertEqual(_compute_default_figsize(), DEFAULT_FIGSIZE)

    def test_format_multi_board_title_includes_board_context(self) -> None:
        frame = load_demo_frames()[0]
        title = _format_multi_board_title(
            group_label="two_board",
            board_name="dev2",
            board_index=1,
            board_count=2,
            run_state=WaveMonitorRunState.RUN,
            frame=frame,
        )
        self.assertIn("group=two_board", title)
        self.assertIn("board=dev2 (2/2)", title)
        self.assertIn("state=RUN", title)
        self.assertIn("event=", title)


if __name__ == "__main__":
    unittest.main()
