import typer

app = typer.Typer(no_args_is_help=True, help="Waveform display commands.")


@app.command("watch")
def wave_watch() -> None:
    """Placeholder for waveform viewing."""
    typer.echo("Not implemented yet.")
    raise typer.Exit(code=1)
