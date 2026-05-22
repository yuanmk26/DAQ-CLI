from rich.console import Console
from rich.table import Table

from daq_cli.application.acquire_service import SingleAcquireResult
from daq_cli.application.board_service import BoardConfigResult, BoardInfoResult
from daq_cli.application.telemetry_service import BoardSysmonResult

console = Console()


def print_board_info(info: BoardInfoResult) -> None:
    table = Table(title=f"Board Info: {info.device.name}")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("name", info.device.name)
    table.add_row("ip", info.device.ip)
    table.add_row("rbcp_port", str(info.device.rbcp_port))
    table.add_row("tcp_port", str(info.device.tcp_port))
    table.add_row("board_id", str(info.device.board_id))
    table.add_row("role", info.device.role or "-")
    table.add_row("profile", str(info.source_profile))
    table.add_row("legacy_project_root", str(info.legacy_project_root or "-"))

    console.print(table)


def print_board_sysmon(result: BoardSysmonResult) -> None:
    table = Table(title=f"Board Sysmon: {result.device.name}")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("temperature_c", f"{result.snapshot.temperature_c:.2f}")
    table.add_row("vccint_v", f"{result.snapshot.vccint_v:.3f}")
    table.add_row("vccaux_v", f"{result.snapshot.vccaux_v:.3f}")
    table.add_row("vccbram_v", f"{result.snapshot.vccbram_v:.3f}")
    table.add_row("profile", str(result.source_profile))

    console.print(table)


def print_board_config_result(result: BoardConfigResult) -> None:
    status = "OK" if result.success else "FAILED"
    table = Table(title=f"Board Config: {result.device.name}")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("status", status)
    table.add_row("adc_enabled", str(result.adc_enabled))
    table.add_row("clock_enabled", str(result.clock_enabled))
    table.add_row("trigger_enabled", str(result.trigger_enabled))
    table.add_row("tcp_mode2_enabled", str(result.tcp_mode2_enabled))
    table.add_row(
        "trigger_thresholds",
        ", ".join(str(value) for value in result.trigger_thresholds),
    )
    table.add_row("trigger_mode", str(result.trigger_mode))
    table.add_row("trigger_position", str(result.trigger_position))
    table.add_row("timestamp_clean_enabled", str(result.timestamp_clean_enabled))
    table.add_row("ext_trigger_enabled", str(result.ext_trigger_enabled))
    table.add_row("send_start_delay_us", f"{result.send_start_delay_us}")
    table.add_row("profile", str(result.source_profile))
    console.print(table)

    if result.log_output.strip():
        console.print(result.log_output.rstrip())


def print_single_acquire_result(result: SingleAcquireResult) -> None:
    table = Table(title=f"Single Acquire: {result.device.name}")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("requested_events", str(result.requested_events))
    table.add_row("captured_events", str(result.captured_events or "-"))
    table.add_row("timeout_s", f"{result.tcp_timeout_s}")
    table.add_row("output_base_dir", str(result.output_base_dir))
    table.add_row("run_output_dir", str(result.run_output_dir or "-"))
    table.add_row("profile", str(result.source_profile))
    console.print(table)

    if result.log_output.strip():
        console.print(result.log_output.rstrip())
