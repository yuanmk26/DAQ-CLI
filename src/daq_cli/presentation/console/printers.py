from rich.console import Console
from rich.table import Table

from daq_cli.application.board_service import BoardInfoResult

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
