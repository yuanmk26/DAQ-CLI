from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from typer.testing import CliRunner

from daq_cli.application.board_service import (
    BoardService,
    SendModeSetResult,
)
from daq_cli.application.config_models import BoardConfigOptions
from daq_cli.cli.app import app


class BoardSendModeTests(unittest.TestCase):
    def test_set_send_mode_writes_and_reads_back(self) -> None:
        profile = SimpleNamespace(
            path=Path("profiles/example.yaml"),
            legacy=SimpleNamespace(project_root=Path("legacy")),
        )
        device = SimpleNamespace(name="dev1")
        adapter = Mock()
        adapter.read_tcp_mode2_config.return_value = SimpleNamespace(send_mode=1)
        service = BoardService()

        with patch.object(service, "_resolve_device", return_value=(profile, device)):
            with patch.object(service, "_make_adapter", return_value=adapter):
                result = service.set_send_mode(
                    device_name="dev1",
                    profile_path="profiles/example.yaml",
                    send_mode=1,
                )

        adapter.write_send_mode.assert_called_once_with(device, 1)
        adapter.read_tcp_mode2_config.assert_called_once_with(device)
        self.assertEqual(
            result,
            SendModeSetResult(
                device=device,
                source_profile=profile.path,
                requested_send_mode=1,
                effective_send_mode=1,
            ),
        )

    def test_set_send_mode_raises_on_readback_mismatch(self) -> None:
        profile = SimpleNamespace(
            path=Path("profiles/example.yaml"),
            legacy=SimpleNamespace(project_root=Path("legacy")),
        )
        device = SimpleNamespace(name="dev1")
        adapter = Mock()
        adapter.read_tcp_mode2_config.return_value = SimpleNamespace(send_mode=0)
        service = BoardService()

        with patch.object(service, "_resolve_device", return_value=(profile, device)):
            with patch.object(service, "_make_adapter", return_value=adapter):
                with self.assertRaises(RuntimeError):
                    service.set_send_mode(
                        device_name="dev1",
                        profile_path="profiles/example.yaml",
                        send_mode=1,
                    )

    def test_configure_board_with_send_mode_writes_and_reads_back(self) -> None:
        profile = SimpleNamespace(
            path=Path("profiles/example.yaml"),
            legacy=SimpleNamespace(project_root=Path("legacy")),
        )
        device = SimpleNamespace(name="dev1")
        adapter = Mock()
        adapter.configure_board.return_value = SimpleNamespace(
            success=True,
            log_output="### Configuring TCP Hit Selection ###\nRead Send Mode: 0\n",
        )
        adapter.read_tcp_mode2_config.return_value = SimpleNamespace(send_mode=1)
        service = BoardService()

        with patch.object(service, "_resolve_device", return_value=(profile, device)):
            with patch("daq_cli.application.board_service.LegacyBoardAdapter", return_value=adapter):
                result = service.configure_board(
                    device_name="dev1",
                    profile_path="profiles/example.yaml",
                    options=BoardConfigOptions(send_mode=1),
                )

        adapter.configure_board.assert_called_once()
        adapter.write_send_mode.assert_called_once_with(device, 1)
        adapter.read_tcp_mode2_config.assert_called_once_with(device)
        self.assertEqual(result.requested_send_mode, 1)
        self.assertEqual(result.effective_send_mode, 1)
        self.assertIn("Pre-write Read Send Mode: 0", result.log_output)
        self.assertIn("Final verified send_mode: 1", result.log_output)

    def test_configure_board_without_send_mode_skips_send_mode_write(self) -> None:
        profile = SimpleNamespace(
            path=Path("profiles/example.yaml"),
            legacy=SimpleNamespace(project_root=Path("legacy")),
        )
        device = SimpleNamespace(name="dev1")
        adapter = Mock()
        adapter.configure_board.return_value = SimpleNamespace(
            success=True,
            log_output="configured",
        )
        service = BoardService()

        with patch.object(service, "_resolve_device", return_value=(profile, device)):
            with patch("daq_cli.application.board_service.LegacyBoardAdapter", return_value=adapter):
                result = service.configure_board(
                    device_name="dev1",
                    profile_path="profiles/example.yaml",
                    options=BoardConfigOptions(),
                )

        adapter.write_send_mode.assert_not_called()
        adapter.read_tcp_mode2_config.assert_not_called()
        self.assertIsNone(result.requested_send_mode)
        self.assertIsNone(result.effective_send_mode)

    def test_cli_send_mode_set_invokes_service(self) -> None:
        runner = CliRunner()
        result_payload = SendModeSetResult(
            device=SimpleNamespace(name="dev1"),
            source_profile=Path("profiles/example.yaml"),
            requested_send_mode=1,
            effective_send_mode=1,
        )

        with patch("daq_cli.cli.board.BoardService") as service_cls:
            service = service_cls.return_value
            service.set_send_mode.return_value = result_payload
            result = runner.invoke(
                app,
                [
                    "board",
                    "send-mode-set",
                    "dev1",
                    "1",
                    "--profile",
                    "profiles/example.yaml",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        service.set_send_mode.assert_called_once_with(
            device_name="dev1",
            profile_path=Path("profiles/example.yaml"),
            send_mode=1,
        )
        self.assertIn("Send Mode Set: dev1", result.output)
        self.assertIn("requested_send_mode", result.output)
        self.assertIn("effective_send_mode", result.output)

    def test_cli_send_mode_set_rejects_out_of_range_mode(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "board",
                "send-mode-set",
                "dev1",
                "4",
                "--profile",
                "profiles/example.yaml",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Invalid value", result.output)

    def test_cli_board_config_passes_send_mode_when_requested(self) -> None:
        runner = CliRunner()

        with patch("daq_cli.cli.board.BoardService") as service_cls:
            service = service_cls.return_value
            service.configure_board.return_value = SimpleNamespace(
                device=SimpleNamespace(name="dev1"),
                source_profile=Path("profiles/example.yaml"),
                success=True,
                send_start_delay_us=0.0,
                adc_enabled=False,
                clock_enabled=False,
                trigger_enabled=True,
                tcp_mode2_enabled=True,
                trigger_thresholds=(1950, 2400, 2300, 2300),
                trigger_mode=1,
                trigger_position=40,
                timestamp_clean_enabled=False,
                ext_trigger_enabled=False,
                requested_send_mode=1,
                effective_send_mode=1,
                log_output="",
            )
            result = runner.invoke(
                app,
                [
                    "board",
                    "config",
                    "dev1",
                    "--send-mode",
                    "1",
                    "--profile",
                    "profiles/example.yaml",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        options = service.configure_board.call_args.kwargs["options"]
        self.assertEqual(options.send_mode, 1)
        self.assertIn("requested_send_mode", result.output)
        self.assertIn("effective_send_mode", result.output)


if __name__ == "__main__":
    unittest.main()
