# daq-cli

`daq-cli` is a Python command-line application for DAQ board configuration,
acquisition, monitoring, and waveform viewing.

## Current status

The repository currently contains:

- Architecture and command design documents in `docs/`
- A minimal Python package skeleton under `src/`
- Profile-driven device loading
- A working `daq board info <device>` command path

## Quick start

Install in editable mode:

```bash
pip install -e .
```

Run the example command:

```bash
daq board info dev1 --profile profiles/example.yaml
```
