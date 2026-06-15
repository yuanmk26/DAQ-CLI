import io
import unittest
from unittest.mock import patch
from typer.testing import CliRunner

import matplotlib
import matplotlib.pyplot as plt

matplotlib.use("Agg")

from daq_cli.cli.app import app  # noqa: E402
from daq_cli.infrastructure.wave_monitor import (  # noqa: E402
    DemoMultiBoardWaveMonitorSource,
    MultiBoardWaveUpdate,
    WaveMonitorFrame,
    WaveMonitorError,
    load_demo_frames,
    load_repo_replay_sample,
    parse_replay_dump,
)
from daq_cli.presentation.wave_monitor_viewer import (  # noqa: E402
    DEFAULT_MULTI_BOARD_HISTORY_LIMIT,
    DEFAULT_FIGSIZE,
    MultiBoardViewerState,
    _format_multi_board_title,
    WaveMonitorFigure,
    WaveMonitorLoopState,
    WaveMonitorRunState,
    _advance_multi_board_viewer_state,
    _compute_channel_ylim,
    _compute_default_figsize,
    _can_navigate_multi_board_history,
    _disconnect_default_key_handler,
    _get_selected_multi_board_frame,
    _get_latest_multi_board_event_count,
    _jump_to_latest_multi_board_event,
    _select_next_multi_board_event,
    _select_previous_multi_board_event,
    _advance_loop_state,
    render_preview_image,
)


class WaveMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._cli_runner = CliRunner()

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

    def test_multi_board_demo_source_emits_about_100_events_by_default(self) -> None:
        import threading

        source = DemoMultiBoardWaveMonitorSource()
        updates = list(source.updates(threading.Event()))
        self.assertEqual(source.board_names, ["dev1", "dev2"])
        self.assertGreaterEqual(len(updates), 180)
        self.assertLess(len(updates), 200)
        board0_events = [
            update.frame.event_count for update in updates if update.board_index == 0
        ]
        board1_events = [
            update.frame.event_count for update in updates if update.board_index == 1
        ]
        self.assertEqual(len(board0_events), 100)
        self.assertEqual(board0_events[0], 1)
        self.assertEqual(board0_events[-1], 100)
        self.assertNotIn(7, board1_events)

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

    def test_channel_ylim_uses_data_range_with_padding(self) -> None:
        ymin, ymax = _compute_channel_ylim([1000, 1001, 1002, 1015, 1001])
        self.assertLess(ymin, 1000)
        self.assertGreater(ymax, 1015)
        self.assertAlmostEqual(ymin, 998.8)
        self.assertAlmostEqual(ymax, 1016.2)

    def test_channel_ylim_handles_flat_signal(self) -> None:
        ymin, ymax = _compute_channel_ylim([2048, 2048, 2048])
        self.assertNotEqual(ymin, ymax)
        self.assertLess(ymin, 2048)
        self.assertGreater(ymax, 2048)
        self.assertAlmostEqual(ymin, 2007.04)
        self.assertAlmostEqual(ymax, 2088.96)

    def test_figure_update_applies_per_axis_ylim(self) -> None:
        frame = WaveMonitorFrame(
            device_name="demo",
            event_count=1,
            timestamp=2,
            hit_mask=0,
            send_mode=1,
            channels=[
                [1000, 1001, 1002, 1015, 1001],
                [2048, 2048, 2048, 2048, 2048],
            ]
            + [[100, 100, 100, 100, 100] for _ in range(14)],
        )
        figure = WaveMonitorFigure(source_label="demo")
        try:
            figure.update(frame, run_state=WaveMonitorRunState.RUN)
            self.assertEqual(figure.figure.axes[0].get_ylim(), (998.8, 1016.2))
            self.assertEqual(figure.figure.axes[1].get_ylim(), (2007.04, 2088.96))
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
            selected_event_count=frame.event_count,
            frame=frame,
        )
        self.assertIn("group=two_board", title)
        self.assertIn("board=dev2 (2/2)", title)
        self.assertIn("state=RUN", title)
        self.assertIn("event=", title)

    def test_format_multi_board_title_reports_missing_selected_event(self) -> None:
        title = _format_multi_board_title(
            group_label="two_board",
            board_name="dev2",
            board_index=1,
            board_count=2,
            run_state=WaveMonitorRunState.STOP,
            selected_event_count=42,
            frame=None,
        )
        self.assertIn("state=STOP", title)
        self.assertIn("event=42", title)
        self.assertIn("missing on this board", title)

    def test_multi_board_run_updates_selected_event_for_selected_board(self) -> None:
        viewer_state = MultiBoardViewerState(selected_board_index=0)
        frame = load_demo_frames()[0]
        step_result = _advance_multi_board_viewer_state(
            viewer_state,
            MultiBoardWaveUpdate(board_name="dev1", board_index=0, frame=frame),
        )
        self.assertTrue(step_result.should_render)
        self.assertEqual(step_result.viewer_state.selected_event_count, frame.event_count)
        self.assertIs(_get_selected_multi_board_frame(step_result.viewer_state), frame)

    def test_multi_board_switches_board_without_changing_selected_event(self) -> None:
        first_frame, next_frame = load_demo_frames()[:2]
        viewer_state = MultiBoardViewerState(selected_board_index=0)
        _advance_multi_board_viewer_state(
            viewer_state,
            MultiBoardWaveUpdate(board_name="dev1", board_index=0, frame=first_frame),
        )
        _advance_multi_board_viewer_state(
            viewer_state,
            MultiBoardWaveUpdate(
                board_name="dev2",
                board_index=1,
                frame=WaveMonitorFrame(
                    device_name="dev2",
                    event_count=first_frame.event_count,
                    timestamp=next_frame.timestamp,
                    hit_mask=next_frame.hit_mask,
                    send_mode=next_frame.send_mode,
                    channels=next_frame.channels,
                ),
            ),
        )
        viewer_state.selected_board_index = 1
        self.assertEqual(viewer_state.selected_event_count, first_frame.event_count)
        self.assertEqual(
            _get_selected_multi_board_frame(viewer_state).event_count,  # type: ignore[union-attr]
            first_frame.event_count,
        )

    def test_multi_board_missing_event_keeps_selected_event_locked(self) -> None:
        viewer_state = MultiBoardViewerState(selected_board_index=0)
        first_frame, next_frame = load_demo_frames()[:2]
        _advance_multi_board_viewer_state(
            viewer_state,
            MultiBoardWaveUpdate(board_name="dev1", board_index=0, frame=first_frame),
        )
        _advance_multi_board_viewer_state(
            viewer_state,
            MultiBoardWaveUpdate(board_name="dev2", board_index=1, frame=next_frame),
        )
        viewer_state.selected_board_index = 1
        self.assertEqual(viewer_state.selected_event_count, first_frame.event_count)
        self.assertIsNone(_get_selected_multi_board_frame(viewer_state))

    def test_multi_board_history_drops_oldest_events_past_limit(self) -> None:
        viewer_state = MultiBoardViewerState(selected_board_index=0)
        for event_count in range(DEFAULT_MULTI_BOARD_HISTORY_LIMIT + 1):
            frame = WaveMonitorFrame(
                device_name="dev1",
                event_count=event_count,
                timestamp=event_count,
                hit_mask=0,
                send_mode=1,
                channels=[[event_count] * 4 for _ in range(16)],
            )
            _advance_multi_board_viewer_state(
                viewer_state,
                MultiBoardWaveUpdate(board_name="dev1", board_index=0, frame=frame),
            )
        history = viewer_state.board_histories[0]
        order = viewer_state.board_event_order[0]
        self.assertEqual(len(history), DEFAULT_MULTI_BOARD_HISTORY_LIMIT)
        self.assertEqual(len(order), DEFAULT_MULTI_BOARD_HISTORY_LIMIT)
        self.assertNotIn(0, history)
        self.assertEqual(order[0], 1)

    def test_multi_board_history_navigation_moves_selected_event(self) -> None:
        viewer_state = MultiBoardViewerState(selected_board_index=0)
        for event_count in (10, 11, 12):
            frame = WaveMonitorFrame(
                device_name="dev1",
                event_count=event_count,
                timestamp=event_count,
                hit_mask=0,
                send_mode=1,
                channels=[[event_count] * 4 for _ in range(16)],
            )
            _advance_multi_board_viewer_state(
                viewer_state,
                MultiBoardWaveUpdate(board_name="dev1", board_index=0, frame=frame),
            )
        self.assertEqual(viewer_state.selected_event_count, 12)
        self.assertTrue(_select_previous_multi_board_event(viewer_state))
        self.assertEqual(viewer_state.selected_event_count, 11)
        self.assertTrue(_select_previous_multi_board_event(viewer_state))
        self.assertEqual(viewer_state.selected_event_count, 10)
        self.assertFalse(_select_previous_multi_board_event(viewer_state))
        self.assertTrue(_select_next_multi_board_event(viewer_state))
        self.assertEqual(viewer_state.selected_event_count, 11)

    def test_multi_board_history_navigation_only_allowed_in_stop(self) -> None:
        viewer_state = MultiBoardViewerState(
            run_state=WaveMonitorRunState.RUN,
            selected_board_index=0,
        )
        self.assertFalse(_can_navigate_multi_board_history(viewer_state))
        viewer_state.run_state = WaveMonitorRunState.STOP
        self.assertTrue(_can_navigate_multi_board_history(viewer_state))
        viewer_state.run_state = WaveMonitorRunState.SINGLE_ARMED
        self.assertFalse(_can_navigate_multi_board_history(viewer_state))

    def test_multi_board_can_jump_back_to_latest_event(self) -> None:
        viewer_state = MultiBoardViewerState(selected_board_index=0)
        for event_count in (10, 11, 12):
            frame = WaveMonitorFrame(
                device_name="dev1",
                event_count=event_count,
                timestamp=event_count,
                hit_mask=0,
                send_mode=1,
                channels=[[event_count] * 4 for _ in range(16)],
            )
            _advance_multi_board_viewer_state(
                viewer_state,
                MultiBoardWaveUpdate(board_name="dev1", board_index=0, frame=frame),
            )
        viewer_state.run_state = WaveMonitorRunState.STOP
        viewer_state.selected_event_count = 10
        self.assertEqual(_get_latest_multi_board_event_count(viewer_state), 12)
        self.assertTrue(_jump_to_latest_multi_board_event(viewer_state))
        self.assertEqual(viewer_state.selected_event_count, 12)

    def test_multi_board_jump_to_latest_returns_false_without_history(self) -> None:
        viewer_state = MultiBoardViewerState(selected_board_index=0)
        self.assertIsNone(_get_latest_multi_board_event_count(viewer_state))
        self.assertFalse(_jump_to_latest_multi_board_event(viewer_state))
        self.assertIsNone(viewer_state.selected_event_count)

    def test_multi_board_run_mode_switch_to_board_uses_latest_for_target_board(self) -> None:
        viewer_state = MultiBoardViewerState(
            run_state=WaveMonitorRunState.RUN,
            selected_board_index=0,
        )
        for event_count in (10, 11, 12):
            _advance_multi_board_viewer_state(
                viewer_state,
                MultiBoardWaveUpdate(
                    board_name="dev1",
                    board_index=0,
                    frame=WaveMonitorFrame(
                        device_name="dev1",
                        event_count=event_count,
                        timestamp=event_count,
                        hit_mask=0,
                        send_mode=1,
                        channels=[[event_count] * 4 for _ in range(16)],
                    ),
                ),
            )
        for event_count in (20, 21):
            _advance_multi_board_viewer_state(
                viewer_state,
                MultiBoardWaveUpdate(
                    board_name="dev2",
                    board_index=1,
                    frame=WaveMonitorFrame(
                        device_name="dev2",
                        event_count=event_count,
                        timestamp=event_count,
                        hit_mask=0,
                        send_mode=1,
                        channels=[[event_count] * 4 for _ in range(16)],
                    ),
                ),
            )
        viewer_state.selected_board_index = 1
        self.assertTrue(_jump_to_latest_multi_board_event(viewer_state))
        self.assertEqual(viewer_state.selected_event_count, 21)

    def test_multi_board_single_armed_waits_for_selected_board_then_stops(self) -> None:
        viewer_state = MultiBoardViewerState(
            run_state=WaveMonitorRunState.SINGLE_ARMED,
            selected_board_index=1,
        )
        first_frame, next_frame = load_demo_frames()[:2]
        ignored = _advance_multi_board_viewer_state(
            viewer_state,
            MultiBoardWaveUpdate(board_name="dev1", board_index=0, frame=first_frame),
        )
        self.assertFalse(ignored.should_render)
        self.assertEqual(ignored.viewer_state.run_state, WaveMonitorRunState.SINGLE_ARMED)
        rendered = _advance_multi_board_viewer_state(
            viewer_state,
            MultiBoardWaveUpdate(board_name="dev2", board_index=1, frame=next_frame),
        )
        self.assertTrue(rendered.should_render)
        self.assertEqual(rendered.viewer_state.run_state, WaveMonitorRunState.STOP)
        self.assertEqual(rendered.viewer_state.selected_event_count, next_frame.event_count)

    def test_monitor_multi_demo_command_uses_default_100_events(self) -> None:
        entered_sessions = []

        class FakeContext:
            def __enter__(self):
                session = type(
                    "Session",
                    (),
                    {
                        "board_names": ["dev1", "dev2"],
                        "frame_queue": object(),
                        "stop_event": object(),
                    },
                )()
                entered_sessions.append(session)
                return session

            def __exit__(self, exc_type, exc, tb):
                return None

        with patch("daq_cli.cli.monitor.MonitorService") as service_cls:
            service = service_cls.return_value
            service.open_multi_board_demo_wave_session.return_value = FakeContext()
            with patch("daq_cli.cli.monitor.run_multi_board_wave_viewer") as viewer:
                result = self._cli_runner.invoke(app, ["monitor", "multi-demo"])

        self.assertEqual(result.exit_code, 0)
        service.open_multi_board_demo_wave_session.assert_called_once_with(events=100)
        viewer.assert_called_once()
        self.assertTrue(entered_sessions)


if __name__ == "__main__":
    unittest.main()
