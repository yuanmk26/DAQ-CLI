import typer

from daq_cli.cli.acquire import app as acquire_app
from daq_cli.cli.board import app as board_app
from daq_cli.cli.decode import app as decode_app
from daq_cli.cli.group import app as group_app
from daq_cli.cli.monitor import app as monitor_app
from daq_cli.cli.profile import app as profile_app
from daq_cli.cli.wave import app as wave_app

app = typer.Typer(
    no_args_is_help=True,
    help="DAQ board configuration, acquisition, monitoring, and waveform tools.",
)

app.add_typer(profile_app, name="profile")
app.add_typer(board_app, name="board")
app.add_typer(group_app, name="group")
app.add_typer(acquire_app, name="acquire")
app.add_typer(decode_app, name="decode")
app.add_typer(monitor_app, name="monitor")
app.add_typer(wave_app, name="wave")
