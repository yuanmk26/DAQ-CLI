import typer

app = typer.Typer(no_args_is_help=True, help="Acquisition commands.")


@app.command("single")
def acquire_single() -> None:
    """Placeholder for single-board acquisition."""
    typer.echo("Not implemented yet.")
    raise typer.Exit(code=1)
