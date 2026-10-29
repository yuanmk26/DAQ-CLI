import multiprocessing


def main() -> None:
    # Required when the CLI is frozen by PyInstaller and spawns the decode /
    # wave-watch backends with multiprocessing.  Keep it before the heavy
    # typer import so the spawned child exits promptly.
    multiprocessing.freeze_support()

    from daq_cli.cli.app import app

    app()


if __name__ == "__main__":
    main()
