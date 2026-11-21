"""Entry point for the Windows one-file workstation and its capture workers."""

if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()

    from daq_cli.qt_replay import main

    main()
