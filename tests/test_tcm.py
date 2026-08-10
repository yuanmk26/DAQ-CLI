from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from typer.testing import CliRunner

from daq_cli.application.tcm_service import (
    TcmService,
    TcmTriggerConfigReadResult,
)
from daq_cli.cli.app import app
from daq_cli.domain.tcm import TcmConfig


class TcmServiceTests(unittest.TestCase):
    def _patched_service(self):
        profile = SimpleNamespace(
            path=Path("profiles/example.yaml"),
            tcm={
                "main": TcmConfig(name="main", ip="192.168.10.16", rbcp_port=4660),
            },
        )
        tcm = profile.tcm["main"]
        adapter = Mock()
        service = TcmService()
        return service, profile, tcm, adapter

    def test_read_trigger_config_passes_through(self) -> None:
        service, profile, tcm, adapter = self._patched_service()
        adapter.read_trigger_config.return_value = SimpleNamespace(
            enable=True,
            mask=0x03,
            pulse_width=32,
            debounce=20,
            trig_sticky=True,
            pending=False,
            wide_pulse_active=False,
            last_trigger_channels=0x02,
        )
        with patch.object(
            service, "_resolve_tcm", return_value=(profile, tcm)
        ), patch.object(service, "_make_adapter", return_value=adapter):
            result = service.read_trigger_config(
                tcm_name="main", profile_path="profiles/example.yaml"
            )

        adapter.read_trigger_config.assert_called_once_with(tcm)
        self.assertIsInstance(result, TcmTriggerConfigReadResult)
        self.assertTrue(result.enable)
        self.assertEqual(result.mask, 0x03)
        self.assertEqual(result.pulse_width, 32)
        self.assertEqual(result.debounce, 20)
        self.assertTrue(result.trig_sticky)
        self.assertEqual(result.last_trigger_channels, 0x02)
        self.assertEqual(result.source_profile, profile.path)

    def test_configure_trigger_writes_and_reads_back(self) -> None:
        service, profile, tcm, adapter = self._patched_service()
        adapter.read_trigger_config.return_value = SimpleNamespace(
            enable=True,
            mask=0x01,
            pulse_width=40,
            debounce=25,
            trig_sticky=False,
            pending=False,
            wide_pulse_active=False,
            last_trigger_channels=0,
        )
        with patch.object(
            service, "_resolve_tcm", return_value=(profile, tcm)
        ), patch.object(service, "_make_adapter", return_value=adapter):
            result = service.configure_trigger(
                tcm_name="main",
                profile_path="profiles/example.yaml",
                enable=True,
                mask=0x01,
                pulse_width=40,
                debounce=25,
            )

        adapter.write_trigger_config.assert_called_once_with(
            tcm,
            enable=True,
            mask=0x01,
            pulse_width=40,
            debounce=25,
        )
        self.assertEqual(result.mask, 0x01)
        self.assertEqual(result.pulse_width, 40)
        self.assertEqual(result.debounce, 25)
        self.assertTrue(result.enable)

    def test_configure_trigger_raises_on_readback_mismatch(self) -> None:
        service, profile, tcm, adapter = self._patched_service()
        adapter.read_trigger_config.return_value = SimpleNamespace(
            enable=False,  # differs from requested enable=True
            mask=0x01,
            pulse_width=40,
            debounce=25,
            trig_sticky=False,
            pending=False,
            wide_pulse_active=False,
            last_trigger_channels=0,
        )
        with patch.object(
            service, "_resolve_tcm", return_value=(profile, tcm)
        ), patch.object(service, "_make_adapter", return_value=adapter):
            with self.assertRaises(RuntimeError):
                service.configure_trigger(
                    tcm_name="main",
                    profile_path="profiles/example.yaml",
                    enable=True,
                    mask=0x01,
                    pulse_width=40,
                    debounce=25,
                )

    def test_unknown_tcm_name_raises(self) -> None:
        service = TcmService()
        profile = SimpleNamespace(
            path=Path("profiles/example.yaml"), tcm={}
        )
        with patch.object(
            service._profile_service, "load_profile", return_value=profile
        ):
            with self.assertRaisesRegex(ValueError, "Unknown TCM 'ghost'"):
                service.read_trigger_config(
                    tcm_name="ghost", profile_path="profiles/example.yaml"
                )

    def test_clear_trigger_sticky_delegates(self) -> None:
        service, profile, tcm, adapter = self._patched_service()
        with patch.object(
            service, "_resolve_tcm", return_value=(profile, tcm)
        ), patch.object(service, "_make_adapter", return_value=adapter):
            service.clear_trigger_sticky(
                tcm_name="main", profile_path="profiles/example.yaml"
            )
        adapter.clear_trigger_sticky.assert_called_once_with(tcm)


class TcmCliTests(unittest.TestCase):
    def test_cli_show_invokes_service(self) -> None:
        runner = CliRunner()
        service = TcmService()
        with patch.object(TcmService, "read_trigger_config") as read_trigger_config:
            read_trigger_config.return_value = SimpleNamespace(
                tcm=TcmConfig(name="main", ip="192.168.10.16", rbcp_port=4660),
                source_profile=Path("profiles/example.yaml"),
                enable=True,
                mask=0x03,
                pulse_width=32,
                debounce=20,
                trig_sticky=True,
                pending=False,
                wide_pulse_active=False,
                last_trigger_channels=0x02,
            )
            with patch("daq_cli.cli.tcm.TcmService", return_value=service):
                result = runner.invoke(
                    app,
                    [
                        "tcm",
                        "show",
                        "main",
                        "--profile",
                        "profiles/example.yaml",
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        read_trigger_config.assert_called_once_with(
            tcm_name="main", profile_path=Path("profiles/example.yaml")
        )
        self.assertIn("TCM Trigger Config", result.output)
        self.assertIn("0x03", result.output)
        self.assertIn("1.6", result.output)  # pulse width 32 x 50ns

    def test_cli_config_invokes_service_and_clears_sticky(self) -> None:
        runner = CliRunner()
        service = TcmService()
        with patch.object(TcmService, "configure_trigger") as configure_trigger:
            configure_trigger.return_value = SimpleNamespace(
                tcm=TcmConfig(name="main", ip="192.168.10.16", rbcp_port=4660),
                source_profile=Path("profiles/example.yaml"),
                enable=True,
                mask=0x01,
                pulse_width=32,
                debounce=20,
            )
            with patch.object(TcmService, "clear_trigger_sticky") as clear_sticky:
                with patch("daq_cli.cli.tcm.TcmService", return_value=service):
                    result = runner.invoke(
                        app,
                        [
                            "tcm",
                            "config",
                            "main",
                            "--mask",
                            "0x01",
                            "--width",
                            "40",
                            "--debounce",
                            "25",
                            "--clear-sticky",
                            "--profile",
                            "profiles/example.yaml",
                        ],
                    )

        self.assertEqual(result.exit_code, 0, result.output)
        configure_trigger.assert_called_once_with(
            tcm_name="main",
            profile_path=Path("profiles/example.yaml"),
            enable=True,
            mask=0x01,
            pulse_width=40,
            debounce=25,
        )
        clear_sticky.assert_called_once_with(
            tcm_name="main", profile_path=Path("profiles/example.yaml")
        )
        self.assertIn("TCM Trigger Config Written", result.output)

    def test_cli_config_rejects_out_of_range_mask(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "tcm",
                "config",
                "main",
                "--mask",
                "0x1FF",
                "--profile",
                "profiles/example.yaml",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("0..0xFF", result.output)

    def test_cli_config_rejects_invalid_mask_text(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "tcm",
                "config",
                "main",
                "--mask",
                "not-a-number",
                "--profile",
                "profiles/example.yaml",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Invalid --mask", result.output)


if __name__ == "__main__":
    unittest.main()
