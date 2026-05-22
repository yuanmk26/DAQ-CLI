from pathlib import Path
from typing import Annotated

import typer

ProfileOption = Annotated[
    Path,
    typer.Option(
        "--profile",
        "-p",
        help="Path to the DAQ profile YAML file.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
]
