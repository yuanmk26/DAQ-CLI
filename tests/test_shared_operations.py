from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest
from typer.testing import CliRunner

from daq_cli.application.acquire_options import (
    resolve_multi_acquire_options,
    resolve_single_acquire_options,
)
from daq_cli.application.board_service import BoardService
from daq_cli.cli.app import app
from daq_cli.presentation.gui.acquire_tab import AcquireTab


def test_board_cli_uses_selected_profile_and_individual_overrides():
    runner = CliRunner()
    with patch("daq_cli.cli.board.BoardService") as service, patch(
        "daq_cli.cli.board.print_board_config_result"
    ):
        result = runner.invoke(
            app, ["board", "config", "dev1", "--threshold-2", "0"],
            env={"DAQ_PROFILE": "profiles/muon-imaging.yaml"},
        )
        assert result.exit_code == 0, result.output
        options = service.return_value.configure_board.call_args.kwargs["options"]
        assert (options.trigger_mode, options.trigger_position) == (9, 74)
        assert options.trigger_thresholds == (1838, 0, 1849, 1939)


def test_gui_reload_replaces_ack_watch_and_storage_defaults():
    tab = Mock()
    tab._single_storage_modes = {"Rate": "rate", "Aggregate": "aggregate"}
    for storage in (tab._single_storage, tab._multi_storage):
        storage.dirs = {}
    profile = SimpleNamespace(devices={"dev1": None}, groups={"four_board": None})
    for defaults in (
        {"acquire_single": {"storage_mode": "rate", "watch_every": 5},
         "acquire_multi": {"allow_start_without_ack": True}},
        {},
    ):
        single = resolve_single_acquire_options(defaults=defaults)
        multi = resolve_multi_acquire_options(defaults=defaults)
        AcquireTab.refresh(tab, profile, single, multi)
    assert tab._allow_no_ack.set.call_args_list == [call(True), call(False)]
    assert tab._watch_enabled.set.call_args_list == [call(True), call(False)]
    assert tab._storage_mode_var.set.call_args_list == [call("Rate"), call("Aggregate")]


def test_mode9_write_order_delay_units_and_readback_verification():
    service = Mock(spec=BoardService)
    service.configure_board.return_value.success = True
    service.read_mode9.side_effect = lambda *args: BoardService.read_mode9(service, *args)
    service.read_trigger_config.return_value = SimpleNamespace(
        trigger_mode=9, trigger_position=74, send_start_delay=21,
        timestamp_clean_enabled=False, ext_trigger_enabled=False,
    )
    tcp = SimpleNamespace(send_mode=1, integration_pre_samples=4, integration_post_samples=12)
    service.read_tcp_mode2_config.return_value = tcp
    settings = dict(
        trigger_mode=9, trigger_position=74, send_start_delay_ticks=21,
        timestamp_clean=False, ext_trigger=False, send_mode=1, thresholds=[1800] * 16,
        mask=4095, polarity=4095, debounce=200, pulse_width=20, enable=True,
        integration_pre=4, integration_post=12,
    )
    _, actual = BoardService.configure_mode9(service, "dev1", "profile.yaml", **settings)
    assert actual.tcp is tcp
    assert service.configure_board.call_args.kwargs["send_start_delay_us"] == 21 / 200
    assert [name for name, _, _ in service.method_calls] == [
        "configure_board", "configure_tcm_link", "write_registers", "write_registers",
        "read_mode9", "read_trigger_config", "read_tcm_link_config", "read_tcp_mode2_config",
    ]
    assert service.write_registers.call_args_list == [
        call("dev1", "profile.yaml", address=0x43, data=bytes([4])),
        call("dev1", "profile.yaml", address=0x44, data=bytes([12])),
    ]
    tcp.integration_post_samples = 0
    with pytest.raises(RuntimeError, match="integration post"):
        BoardService.configure_mode9(service, "dev1", "profile.yaml", **settings)
    service.reset_mock()
    with pytest.raises(ValueError, match="integration_pre"):
        BoardService.configure_mode9(service, "dev1", "profile.yaml", **(settings | {"integration_pre": 256}))
    service.configure_board.assert_not_called()
