# daq-cli

`daq-cli` is a Python command-line application for DAQ board configuration,
acquisition, monitoring, and waveform viewing.

## Current status

The repository currently contains:

- Architecture and command design documents in `docs/`
- A user guide in `docs/usage.md`
- A Python package skeleton under `src/`
- Profile-driven device loading
- Legacy-script adapters for board telemetry, board configuration, and single-board capture
- Working command paths:
  - `daq board info <device>`
  - `daq board sysmon <device>`
  - `daq board config <device>`
  - `daq acquire single <device>`

Not implemented yet:

- `daq acquire multi`
- `daq monitor ...`
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

Capture single-board data:

```bash
daq acquire single dev1 --events 100 --profile profiles/example.yaml
```
