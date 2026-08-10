from typing import Annotated

import typer

from daq_cli.application.tcm_service import TcmService
from daq_cli.cli.common import RequiredProfileOption
from daq_cli.presentation.console.printers import (
    print_tcm_trigger_config_read_result,
    print_tcm_trigger_config_write_result,
)

app = typer.Typer(no_args_is_help=True, help="TCM board operations.")


@app.command("show")
def tcm_show(
    name: Annotated[str, typer.Argument(help="TCM entry name from the profile.")],
    profile: RequiredProfileOption = ...,
) -> None:
    """Read TCM trigger-link configuration and status without writing."""
    service = TcmService()
    result = service.read_trigger_config(tcm_name=name, profile_path=profile)
    print_tcm_trigger_config_read_result(result)


@app.command("config")
def tcm_config(
    name: Annotated[str, typer.Argument(help="TCM entry name from the profile.")],
    enable: Annotated[
        bool,
        typer.Option("--enable/--disable", help="Enable or disable the trigger link."),
    ] = True,
    mask: Annotated[
        str | None,
        typer.Option(
            "--mask",
            help="8-bit channel participation mask as decimal or 0x-prefixed hex.",
        ),
    ] = None,
    width: Annotated[
        int,
        typer.Option(
            "--width",
            min=0,
            max=0xFF,
            help="Wide pulse width in 20M cycles (default 32 = 1.6us).",
        ),
    ] = 32,
    debounce: Annotated[
        int,
        typer.Option(
            "--debounce",
            min=0,
            max=0xFFFF,
            help="Trigger debounce in 20M cycles (default 20 = 1us).",
        ),
    ] = 20,
    clear_sticky: Annotated[
        bool,
        typer.Option(
            "--clear-sticky/--keep-sticky",
            help="Clear the trigger sticky status bit after writing.",
        ),
    ] = False,
    profile: RequiredProfileOption = ...,
) -> None:
    """Write TCM trigger-link configuration (0x20..0x23) and verify by readback."""
    parsed_mask = 0
    if mask is not None:
        try:
            parsed_mask = int(mask, 0)
        except ValueError as exc:
            raise typer.BadParameter(
                f"Invalid --mask '{mask}'. Use decimal or 0x-prefixed hex."
            ) from exc
        if parsed_mask < 0 or parsed_mask > 0xFF:
            raise typer.BadParameter("--mask must stay in range 0..0xFF")

    service = TcmService()
    result = service.configure_trigger(
        tcm_name=name,
        profile_path=profile,
        enable=enable,
        mask=parsed_mask,
        pulse_width=width,
        debounce=debounce,
    )
    print_tcm_trigger_config_write_result(result)
    if clear_sticky:
        service.clear_trigger_sticky(tcm_name=name, profile_path=profile)
