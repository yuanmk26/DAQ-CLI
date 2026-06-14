from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from typer.testing import CliRunner

from daq_cli.application.board_service import BoardService
from daq_cli.cli.app import app
from daq_cli.infrastructure.adapters.legacy_runtime import bundled_legacy_script_dir
from daq_cli.infrastructure.config_loader import load_profile


runner = CliRunner()
TMP_OUTPUT_DIR = Path("tmp_test_outputs")


def test_bundled_legacy_script_dir_contains_required_modules() -> None:
    script_dir = bundled_legacy_script_dir()

    assert (script_dir / "start_16CH_two_board.py").is_file()
    assert (script_dir / "FPGA_CTRL.py").is_file()
    assert (script_dir / "multi_board_acquire.py").is_file()
    assert (script_dir / "lib" / "rbcp.py").is_file()
    assert (script_dir / "lib" / "__init__.py").is_file()


def test_profile_init_writes_template() -> None:
    TMP_OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = TMP_OUTPUT_DIR / f"profile-init-{uuid.uuid4().hex}.yaml"
    result = runner.invoke(app, ["profile", "init", str(output_path)])

    assert result.exit_code == 0
    assert output_path.is_file()
    contents = output_path.read_text(encoding="utf-8")
    assert "devices:" in contents
    assert "legacy:" not in contents


def test_profile_commands_require_profile_option() -> None:
    result = runner.invoke(app, ["board", "info", "dev1"])

    assert result.exit_code != 0
    assert "--profile" in result.output


def test_load_profile_ignores_legacy_section() -> None:
    TMP_OUTPUT_DIR.mkdir(exist_ok=True)
    profile_path = TMP_OUTPUT_DIR / f"legacy-compatible-{uuid.uuid4().hex}.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "devices:",
                "  dev1:",
                "    ip: 192.168.10.10",
                "    role: adc",
                "tcm: {}",
                "groups: {}",
                "defaults: {}",
                "legacy:",
                "  project_root: C:\\legacy\\repo",
                "",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_profile(profile_path)

    assert loaded.path == profile_path
    assert "dev1" in loaded.devices
    assert not hasattr(loaded, "legacy")


def test_board_service_uses_bundled_runtime_without_legacy_profile_field() -> None:
    service = BoardService()
    device = SimpleNamespace(name="dev1", ip="192.168.10.10", rbcp_port=4660, tcp_port=24, board_id=0, role="adc")
    profile = SimpleNamespace(path=Path("profiles/example.yaml"), devices={"dev1": device})

    with patch.object(service, "_resolve_device", return_value=(profile, device)):
        with patch("daq_cli.application.board_service.LegacyBoardAdapter") as adapter_cls:
            adapter_cls.return_value.read_registers.return_value = SimpleNamespace(
                address=0x10,
                data=b"\xAA",
            )

            result = service.read_registers("dev1", "profiles/example.yaml", 0x10, 1)

    adapter_cls.assert_called_once_with()
    assert result.data == b"\xAA"
