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


class TcmLinkTests(unittest.TestCase):
    def _patched_service(self) -> tuple[BoardService, SimpleNamespace, SimpleNamespace, Mock]:
        profile = SimpleNamespace(
            path=Path("profiles/example.yaml"),
            legacy=SimpleNamespace(project_root=Path("legacy")),
        )
        device = SimpleNamespace(name="dev1")
        adapter = Mock()
        service = BoardService()
        profile_patcher = patch.object(service, "_resolve_device", return_value=(profile, device))
        adapter_patcher = patch.object(service, "_make_adapter", return_value=adapter)
        return service, profile, device, adapter

    def test_read_tcm_link_config_passes_through(self) -> None:
        service, profile, device, adapter = self._patched_service()
        adapter.read_tcm_link_config.return_value = SimpleNamespace(
            thresholds=[2700] + [0] * 15,
            mask=0x0003,
            polarity=0x0002,
            debounce=200,
            enable=True,
            pulse_width=20,
        )
        with patch.object(service, "_resolve_device", return_value=(profile, device)), patch.object(service, "_make_adapter", return_value=adapter):
            result = service.read_tcm_link_config(
                device_name="dev1", profile_path="profiles/example.yaml"
            )

        adapter.read_tcm_link_config.assert_called_once_with(device)
        self.assertEqual(result.mask, 0x0003)
        self.assertEqual(result.thresholds, [2700] + [0] * 15)
        self.assertEqual(result.polarity, 0x0002)
        self.assertEqual(result.debounce, 200)
        self.assertTrue(result.enable)
        self.assertEqual(result.pulse_width, 20)
        self.assertEqual(result.source_profile, profile.path)

    def test_configure_tcm_link_writes_and_reads_back(self) -> None:
        service, profile, device, adapter = self._patched_service()
        adapter.read_tcm_link_config.return_value = SimpleNamespace(
            thresholds=[1800] * 16,
            mask=0x0001,
            polarity=0x0001,
            debounce=200,
            enable=True,
            pulse_width=20,
        )
        with patch.object(service, "_resolve_device", return_value=(profile, device)), patch.object(service, "_make_adapter", return_value=adapter):
            result = service.configure_tcm_link(
                device_name="dev1",
                profile_path="profiles/example.yaml",
                thresholds=[1800] * 16,
                mask=0x0001,
                polarity=0x0001,
                debounce=200,
                pulse_width=20,
                enable=True,
            )

        adapter.write_tcm_link_config.assert_called_once()
        self.assertEqual(result.mask, 0x0001)
        self.assertTrue(result.enable)

    def test_configure_tcm_link_raises_on_readback_mismatch(self) -> None:
        service, profile, device, adapter = self._patched_service()
        adapter.read_tcm_link_config.return_value = SimpleNamespace(
            thresholds=[1800] * 16,
            mask=0x0000,  # differs from requested 0x0001
            polarity=0x0001,
            debounce=200,
            enable=True,
            pulse_width=20,
        )
        with patch.object(service, "_resolve_device", return_value=(profile, device)), patch.object(service, "_make_adapter", return_value=adapter):
            with self.assertRaises(RuntimeError):
                service.configure_tcm_link(
                    device_name="dev1",
                    profile_path="profiles/example.yaml",
                    thresholds=[1800] * 16,
                    mask=0x0001,
                    polarity=0x0001,
                    debounce=200,
                    pulse_width=20,
                    enable=True,
                )

    def test_write_registers_passes_through(self) -> None:
        service, profile, device, adapter = self._patched_service()
        with patch.object(
            service, "_resolve_device", return_value=(profile, device)
        ), patch.object(service, "_make_adapter", return_value=adapter):
            service.write_registers(
                device_name="dev1",
                profile_path="profiles/example.yaml",
                address=0x43,
                data=bytes([4]),
            )
        adapter.write_registers.assert_called_once_with(device, 0x43, bytes([4]))

    def test_cli_tcm_link_config_requires_mask(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "board",
                "tcm-link-config",
                "dev1",
                "--profile",
                "profiles/example.yaml",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--mask is required", result.output)

    def test_cli_tcm_link_show_invokes_service(self) -> None:
        runner = CliRunner()
        service = BoardService()
        with patch.object(BoardService, "read_tcm_link_config") as read_tcm_link_config:
            read_tcm_link_config.return_value = SimpleNamespace(
                device=SimpleNamespace(name="dev1"),
                source_profile=Path("profiles/example.yaml"),
                thresholds=[2700, 1800] + [0] * 14,
                mask=0x0003,
                polarity=0x0002,
                debounce=200,
                enable=True,
                pulse_width=20,
            )
            with patch("daq_cli.cli.board.BoardService", return_value=service):
                result = runner.invoke(
                    app,
                    [
                        "board",
                        "tcm-link-show",
                        "dev1",
                        "--profile",
                        "profiles/example.yaml",
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        read_tcm_link_config.assert_called_once_with(
            device_name="dev1", profile_path=Path("profiles/example.yaml")
        )
        self.assertIn("TCM Link Config", result.output)
        self.assertIn("2700", result.output)


if __name__ == "__main__":
    unittest.main()
