# daq-cli

`daq-cli` is a Python command-line application for DAQ board configuration,
acquisition, monitoring, and waveform viewing.

## Current status

The repository currently contains:

- Architecture and command design documents in `docs/`
- A user guide in `docs/usage.md`
- Firmware compatibility notes in `docs/firmware-compatibility.md`
- A Python package skeleton under `src/`
- Profile-driven device loading
- Legacy-script adapters for board telemetry, board configuration, and acquisition
- Working command paths:
  - `daq board info <device>`
  - `daq board sysmon <device>`
  - `daq board config <device>`
  - `daq board trigger-show <device>`
  - `daq board tcp-mode2-show <device>`
  - `daq board config-show <device>`
  - `daq board reg-read <device> <address>`
  - `daq acquire single <device>`
  - `daq acquire multi <group>`
  - `daq monitor wave <device>`

Not implemented yet:

- additional `daq monitor ...` commands
- `daq wave ...`
- `daq shell`

## Quick start

Install in editable mode:

```bash
pip install -e .
```

Run the example command:

```bash
daq board info dev1 --profile profiles/example.yaml
```

Read telemetry:

```bash
daq board sysmon dev1 --profile profiles/example.yaml
```

Run configurable board setup:

```bash
daq board config dev1 --profile profiles/example.yaml
daq board config dev1 --adc --clock --trigger --tcp-mode2 --profile profiles/example.yaml
daq board config dev1 --trigger-mode 1 --trigger-position 40 --threshold-1 1950 --threshold-2 2400 --threshold-3 2300 --threshold-4 2300
```

Read configuration back without writing:

```bash
daq board trigger-show dev1 --profile profiles/example.yaml
daq board tcp-mode2-show dev1 --profile profiles/example.yaml
daq board config-show dev1 --profile profiles/example.yaml
daq board reg-read dev1 0x10 --len 1 --profile profiles/example.yaml
```

Firmware notes:

- current board readback commands still use historical `tcp-mode2` naming
- latest firmware exposes four `TCP_SENT` packet modes rather than a single
  special "mode-2" protocol
- see `docs/firmware-compatibility.md` for the current firmware-facing contract

Capture single-board data:

```bash
daq acquire single dev1 --events 100 --profile profiles/example.yaml
```

Run multi-board acquisition:

```bash
daq acquire multi two_board --profile profiles/example.yaml
daq acquire multi two_board --aggregation-key event_count --allow-start-without-ack --profile profiles/example.yaml
daq acquire multi two_board --decode-json --profile profiles/example.yaml
```

Preview or watch waveforms:

```bash
daq monitor wave dev1 --profile profiles/example.yaml
daq monitor wave demo --demo
daq monitor wave replay --replay src/daq_cli/monitoring_samples/replay_dump.txt
```

The waveform viewer supports keyboard-driven `RUN`, `STOP`, and `SINGLE`
display control for quick frame inspection.
