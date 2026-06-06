from typing import Annotated
from pathlib import Path

import typer

from daq_cli.application.board_service import BoardService
from daq_cli.application.config_models import BoardConfigOptions
from daq_cli.application.telemetry_service import TelemetryService
from daq_cli.cli.common import ProfileOption
from daq_cli.presentation.console.printers import (
    print_board_config_result,
    print_board_config_summary_result,
    print_board_info,
    print_send_mode_set_result,
    print_board_sysmon,
    print_register_read_result,
    print_tcp_mode2_config_read_result,
    print_trigger_config_read_result,
)

app = typer.Typer(no_args_is_help=True, help="Single-board operations.")


@app.command("info")
def board_info(
    device: Annotated[str, typer.Argument(help="Logical device name from the profile.")],
    profile: ProfileOption = Path("profiles/example.yaml"),
) -> None:
    """Show profile-backed board information."""
    service = BoardService()
    info = service.get_board_info(device_name=device, profile_path=profile)
    print_board_info(info)


@app.command("sysmon")
def board_sysmon(
    device: Annotated[str, typer.Argument(help="Logical device name from the profile.")],
    profile: ProfileOption = Path("profiles/example.yaml"),
) -> None:
    """Read FPGA telemetry through the legacy sysmon path."""
    service = TelemetryService()
    result = service.get_board_sysmon(device_name=device, profile_path=profile)
    print_board_sysmon(result)


@app.command("config")
def board_config(
    device: Annotated[str, typer.Argument(help="Logical device name from the profile.")],
    adc_enabled: Annotated[
        bool,
        typer.Option(
            "--adc/--no-adc",
            help="Enable or skip ADC configuration.",
        ),
    ] = False,
    clock_enabled: Annotated[
        bool,
        typer.Option(
            "--clock/--no-clock",
            help="Enable or skip clock configuration.",
        ),
    ] = False,
    trigger_enabled: Annotated[
        bool,
        typer.Option(
            "--trigger/--no-trigger",
            help="Enable or skip trigger configuration.",
        ),
    ] = True,
    tcp_mode2_enabled: Annotated[
        bool,
        typer.Option(
            "--tcp-mode2/--no-tcp-mode2",
            help="Enable or skip TCP mode-2 hit-selection configuration.",
        ),
    ] = True,
    send_start_delay_us: Annotated[
        float,
        typer.Option(
            "--send-start-delay-us",
            help="Send-start delay written during trigger configuration.",
        ),
    ] = 0.0,
    threshold_1: Annotated[
        int,
        typer.Option("--threshold-1", help="Trigger threshold 1."),
    ] = 1950,
    threshold_2: Annotated[
        int,
        typer.Option("--threshold-2", help="Trigger threshold 2."),
    ] = 2400,
    threshold_3: Annotated[
        int,
        typer.Option("--threshold-3", help="Trigger threshold 3."),
    ] = 2300,
    threshold_4: Annotated[
        int,
        typer.Option("--threshold-4", help="Trigger threshold 4."),
    ] = 2300,
    trigger_mode: Annotated[
        int,
        typer.Option("--trigger-mode", help="Trigger mode register value."),
    ] = 1,
    trigger_position: Annotated[
        int,
        typer.Option("--trigger-position", help="Trigger position register value."),
    ] = 40,
    timestamp_clean_enabled: Annotated[
        bool,
        typer.Option(
            "--timestamp-clean/--no-timestamp-clean",
            help="Enable or disable timestamp clean.",
        ),
    ] = False,
    ext_trigger_enabled: Annotated[
        bool,
        typer.Option(
            "--ext-trigger/--no-ext-trigger",
            help="Enable or disable external trigger.",
        ),
    ] = False,
    send_mode: Annotated[
        int | None,
        typer.Option(
            "--send-mode",
            min=0,
            max=3,
            help=(
                "Optionally write TCP send mode after configuration: "
                "0=hit-selected waveform, 1=full-channel waveform, "
                "2=hit-selected feature, 3=hit-selected feature + waveform."
            ),
        ),
    ] = None,
    profile: ProfileOption = Path("profiles/example.yaml"),
) -> None:
    """Configure a board through the legacy configuration script."""
    service = BoardService()
    result = service.configure_board(
        device_name=device,
        profile_path=profile,
        send_start_delay_us=send_start_delay_us,
        options=BoardConfigOptions(
            adc_enabled=adc_enabled,
            clock_enabled=clock_enabled,
            trigger_enabled=trigger_enabled,
            tcp_mode2_enabled=tcp_mode2_enabled,
            trigger_thresholds=(
                threshold_1,
                threshold_2,
                threshold_3,
                threshold_4,
            ),
            trigger_mode=trigger_mode,
            trigger_position=trigger_position,
            timestamp_clean_enabled=timestamp_clean_enabled,
            ext_trigger_enabled=ext_trigger_enabled,
            send_mode=send_mode,
        ),
    )
    print_board_config_result(result)


@app.command("trigger-show")
def board_trigger_show(
    device: Annotated[str, typer.Argument(help="Logical device name from the profile.")],
    profile: ProfileOption = Path("profiles/example.yaml"),
) -> None:
    """Read trigger-related configuration without writing registers."""
    service = BoardService()
    result = service.read_trigger_config(device_name=device, profile_path=profile)
    print_trigger_config_read_result(result)


@app.command("tcp-mode2-show")
def board_tcp_mode2_show(
    device: Annotated[str, typer.Argument(help="Logical device name from the profile.")],
    profile: ProfileOption = Path("profiles/example.yaml"),
) -> None:
    """Read TCP mode-2 configuration without writing registers."""
    service = BoardService()
    result = service.read_tcp_mode2_config(device_name=device, profile_path=profile)
    print_tcp_mode2_config_read_result(result)


@app.command("send-mode-set")
def board_send_mode_set(
    device: Annotated[str, typer.Argument(help="Logical device name from the profile.")],
    mode: Annotated[
        int,
        typer.Argument(
            min=0,
            max=3,
            help=(
                "TCP send mode: 0=hit-selected waveform, 1=full-channel waveform, "
                "2=hit-selected feature, 3=hit-selected feature + waveform."
            ),
        ),
    ],
    profile: ProfileOption = Path("profiles/example.yaml"),
) -> None:
    """Write the board send_mode register and verify it by readback."""
    service = BoardService()
    result = service.set_send_mode(
        device_name=device,
        profile_path=profile,
        send_mode=mode,
    )
    print_send_mode_set_result(result)


@app.command("config-show")
def board_config_show(
    device: Annotated[str, typer.Argument(help="Logical device name from the profile.")],
    profile: ProfileOption = Path("profiles/example.yaml"),
) -> None:
    """Read a semantic board configuration summary without writing registers."""
    service = BoardService()
    result = service.read_board_config_summary(
        device_name=device, profile_path=profile
    )
    print_board_config_summary_result(result)


@app.command("reg-read")
def board_reg_read(
    device: Annotated[str, typer.Argument(help="Logical device name from the profile.")],
    address: Annotated[
        str, typer.Argument(help="Register address such as 0x10 or 16.")
    ],
    length: Annotated[
        int,
        typer.Option("--len", min=1, max=255, help="Number of bytes to read."),
    ] = 1,
    profile: ProfileOption = Path("profiles/example.yaml"),
) -> None:
    """Read raw register bytes for debugging."""
    try:
        parsed_address = int(address, 0)
    except ValueError as exc:
        raise typer.BadParameter(
            f"Invalid register address '{address}'. Use decimal or 0x-prefixed hex."
        ) from exc

    service = BoardService()
    result = service.read_registers(
        device_name=device,
        profile_path=profile,
        address=parsed_address,
        length=length,
    )
    print_register_read_result(result)
