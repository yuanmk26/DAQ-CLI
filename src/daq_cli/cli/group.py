import typer

app = typer.Typer(no_args_is_help=True, help="Multi-board group operations.")


@app.command("info")
def group_info() -> None:
    """Placeholder for group info commands."""
    typer.echo("Not implemented yet.")
    raise typer.Exit(code=1)
