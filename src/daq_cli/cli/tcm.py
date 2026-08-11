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


@app.command("align-clear")
def tcm_align_clear(
    name: Annotated[str, typer.Argument(help="TCM entry name from the profile.")],
    profile: RequiredProfileOption = ...,
) -> None:
    """Release a stuck TCM alignment controller (recover after a failed
    align blocks trigger broadcasts)."""
    service = TcmService()
    service.clear_align(tcm_name=name, profile_path=profile)
    typer.echo(f"TCM '{name}' align controller cleared.")


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
    coincidence: Annotated[
        bool,
        typer.Option(
            "--coincidence/--no-coincidence",
            help="Enable coincidence mode (>=N per group, AND over groups).",
        ),
    ] = False,
    coinc_groups: Annotated[
        int,
        typer.Option("--coinc-groups", min=0, max=4, help="Enabled group count (0=default 2)."),
    ] = 0,
    coinc_window: Annotated[
        int,
        typer.Option(
            "--coinc-window",
            min=0,
            max=0xFF,
            help="Coincidence window in 20M cycles (0=default 4).",
        ),
    ] = 0,
    coinc_masks: Annotated[
        str | None,
        typer.Option(
            "--coinc-masks",
            help="4 group participation masks, comma-separated hex, e.g. 0x03,0x0C.",
        ),
    ] = None,
    coinc_ns: Annotated[
        str | None,
        typer.Option(
            "--coinc-ns",
            help="4 group N values (1..8, 0=default 1), comma-separated, e.g. 1,1,0,0.",
        ),
    ] = None,
    profile: RequiredProfileOption = ...,
) -> None:
    """Write TCM trigger-link configuration (0x20..0x2F) and verify by readback."""
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

    group_masks = (0, 0, 0, 0)
    if coinc_masks is not None:
        raw_masks = [part.strip() for part in coinc_masks.split(",")]
        if len(raw_masks) != 4:
            raise typer.BadParameter("--coinc-masks needs exactly 4 comma-separated values")
        parsed_masks = []
        for item in raw_masks:
            try:
                parsed = int(item, 0)
            except ValueError as exc:
                raise typer.BadParameter(f"Invalid --coinc-masks value '{item}'") from exc
            if parsed < 0 or parsed > 0xFF:
                raise typer.BadParameter("--coinc-masks values must stay in range 0..0xFF")
            parsed_masks.append(parsed)
        group_masks = tuple(parsed_masks)  # type: ignore[assignment]

    group_n = (0, 0, 0, 0)
    if coinc_ns is not None:
        raw_ns = [part.strip() for part in coinc_ns.split(",")]
        if len(raw_ns) != 4:
            raise typer.BadParameter("--coinc-ns needs exactly 4 comma-separated values")
        parsed_ns = []
        for item in raw_ns:
            try:
                parsed = int(item, 0)
            except ValueError as exc:
                raise typer.BadParameter(f"Invalid --coinc-ns value '{item}'") from exc
            if parsed < 0 or parsed > 8:
                raise typer.BadParameter("--coinc-ns values must stay in range 0..8")
            parsed_ns.append(parsed)
        group_n = tuple(parsed_ns)  # type: ignore[assignment]

    service = TcmService()
    result = service.configure_trigger(
        tcm_name=name,
        profile_path=profile,
        enable=enable,
        mask=parsed_mask,
        pulse_width=width,
        debounce=debounce,
        coincidence_enabled=coincidence,
        grp_count=coinc_groups,
        coinc_window=coinc_window,
        group_masks=group_masks,  # type: ignore[arg-type]
        group_n=group_n,  # type: ignore[arg-type]
    )
    print_tcm_trigger_config_write_result(result)
    if clear_sticky:
        service.clear_trigger_sticky(tcm_name=name, profile_path=profile)
