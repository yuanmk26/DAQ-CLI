from pathlib import Path
from typing import Annotated

import typer

from daq_cli.application.decode_service import DecodeService

app = typer.Typer(no_args_is_help=True, help="Offline decode commands.")


@app.command("run")
def decode_run(
    run_dir: Annotated[
        Path,
        typer.Argument(help="Single-board acquisition run directory containing raw/."),
    ],
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help="Directory for decoded JSON files. Defaults to <run_dir>/decoded.",
        ),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite/--no-overwrite",
            help="Allow overwriting existing decoded JSON files.",
        ),
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            min=1,
            help="Decode only the first N event files in filename order.",
        ),
    ] = None,
) -> None:
    service = DecodeService()
    result = service.decode_run(
        run_dir=run_dir,
        output_dir=output_dir,
        overwrite=overwrite,
        limit=limit,
    )
    typer.echo(f"Decoded run: {result.run_dir}")
    typer.echo(f"output_dir={result.output_dir}")
    typer.echo(f"success_count={result.success_count}")
    typer.echo(f"failure_count={result.failure_count}")
    typer.echo(
        "send_mode="
        + ("unknown" if result.send_mode is None else str(result.send_mode))
    )


@app.command("event")
def decode_event(
    event_file: Annotated[
        Path,
        typer.Argument(help="Single raw event_XXXXX.bin file to decode."),
    ],
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help="Directory for the decoded JSON file. Defaults to a decoded/ sibling.",
        ),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite/--no-overwrite",
            help="Allow overwriting an existing decoded JSON file.",
        ),
    ] = False,
) -> None:
    service = DecodeService()
    result = service.decode_event(
        event_file=event_file,
        output_dir=output_dir,
        overwrite=overwrite,
    )
    typer.echo(f"Decoded event: {result.input_file}")
    typer.echo(f"output_file={result.output_file}")
    typer.echo(f"send_mode={result.send_mode}")
    typer.echo(f"raw_packet_bytes={result.raw_packet_bytes}")
