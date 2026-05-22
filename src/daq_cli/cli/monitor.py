import typer

app = typer.Typer(no_args_is_help=True, help="Monitoring commands.")


@app.command("board")
def monitor_board() -> None:
    """Placeholder for board monitoring."""
    typer.echo("Not implemented yet.")
    raise typer.Exit(code=1)
