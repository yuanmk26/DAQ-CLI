# daq-cli

`daq-cli` is a Python command-line application for DAQ board configuration,
acquisition, monitoring, and waveform viewing.

## Current status

The repository currently contains:

- Architecture and command design documents in `docs/`
- A user guide in `docs/usage.md`
- Firmware compatibility notes in `docs/firmware-compatibility.md`
- A Python package under `src/` with layered architecture
- Profile-driven device loading
- Native multi-board acquisition; legacy-script adapters for board telemetry,
  board configuration, and the TCM chain
- Working command paths:
  - `daq board info <device>`
  - `daq board sysmon <device>`
  - `daq board config <device>`
  - `daq board trigger-show <device>`
  - `daq board tcp-mode2-show <device>`
  - `daq board tcm-link-show <device>`
  - `daq board tcm-link-config <device> --mask ...`
  - `daq board config-show <device>`
  - `daq board reg-read <device> <address>`
  - `daq tcm show <name>`
  - `daq tcm config <name> --mask ...`
  - `daq acquire single <device>`
  - `daq acquire multi <group>`
  - `daq monitor wave <device>`
  - `daq-gui [--profile ...]` / `daq gui` — desktop GUI console

Not implemented yet:

- additional `daq monitor ...` commands
- `daq shell`

## Quick start

Install in editable mode:

```bash
pip install -e .
```

### Standalone executables (no Python needed on the target PC)

Build the versioned, one-file GUI executable with PyInstaller:

```powershell
.\scripts\build_gui_exe.ps1
```

Output: `dist\daq-gui-<version>.exe`. It bundles Python, matplotlib,
tkinter, and the vendored legacy scripts, so it runs on another Windows PC
without installing anything. On startup it auto-discovers a profile next to
the exe (`DAQ_PROFILE`, `daq-profile.yaml`, or a single
`profiles\*.yaml`) — see `docs/deploy-exe.md` for the deployment layout.

To build both the GUI and the CLI as one-file executables instead:

```powershell
.\scripts\build_exe.ps1
```

Outputs land in `dist-exe\` (`daq-gui.exe` + `daq.exe`).

```bash
dist\daq-gui-0.4.6.exe --profile profiles\examples\example.tcm-trigger.yaml
dist-exe\daq.exe --help
```

A ready-to-use TCM trigger-link example profile ships at
`profiles/examples/example.tcm-trigger.yaml` (3 ADC boards + TCM, mode 9 workflow,
per-type output directories, step-by-step configuration notes).

Install from a GitHub Releases offline package on a new PC:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --no-index --find-links wheelhouse daq_cli-<version>-py3-none-any.whl
daq --help
daq profile init .\lab-pc-01.yaml
```

For a release-style install and machine-specific profile setup, see
`docs/install-on-new-pc.md`. For a public configuration starting point, use
`daq profile init` to write a machine-local YAML file and then edit the
hardware-specific values there.

Run the example command:

```bash
daq board info dev1 --profile profiles/examples/example.yaml
```

Read telemetry:

```bash
daq board sysmon dev1 --profile profiles/examples/example.yaml
```

Run configurable board setup:

```bash
daq board config dev1 --profile profiles/examples/example.yaml
daq board config dev1 --adc --clock --trigger --tcp-mode2 --profile profiles/examples/example.yaml
daq board config dev1 --trigger-mode 1 --trigger-position 40 --threshold-1 1950 --threshold-2 2400 --threshold-3 2300 --threshold-4 2300 --profile profiles/examples/example.yaml
```

Read configuration back without writing:

```bash
daq board trigger-show dev1 --profile profiles/examples/example.yaml
daq board tcp-mode2-show dev1 --profile profiles/examples/example.yaml
daq board config-show dev1 --profile profiles/examples/example.yaml
daq board reg-read dev1 0x10 --len 1 --profile profiles/examples/example.yaml
```

Firmware notes:

- current board readback commands still use historical `tcp-mode2` naming
- latest firmware exposes four `TCP_SENT` packet modes rather than a single
  special "mode-2" protocol
- since v0.2.0 frames carry a 28-byte header (format version in byte 19) with
  `crossing_fine` / `accept_fine` timestamps; old 20-byte frames still decode
- `daq board tcm-link-*` drives the ADC-side TCM trigger link registers
  (`0x45..0x6C`), `daq tcm show/config` drives the TCM-board side
  (`0x20..0x25`), and `Trigger_model = 9` is supported
- see `docs/firmware-compatibility.md` for the current firmware-facing contract

Capture single-board data:

```bash
daq acquire single dev1 --events 100 --profile profiles/examples/example.yaml
```

Run multi-board acquisition:

```bash
daq acquire multi two_board --profile profiles/examples/example.yaml
daq acquire multi two_board --aggregation-key event_count --allow-start-without-ack --profile profiles/examples/example.yaml
daq acquire multi two_board --decode-json --profile profiles/examples/example.yaml
```

Configure capture outputs in the profile with independent `raw`, `json`, `text`,
and `log` switches and directories:

```yaml
defaults:
  acquire_single:
    outputs:
      raw:
        enabled: true
        dir: out/raw
      json:
        enabled: false
      text:
        enabled: true
        dir: out/text
        max_events_per_file: 1000
        waveform_layout: channel_blocks
      log:
        enabled: true
        dir: out/log
```

With this layout you can, for example, disable JSON while still keeping TXT
event dumps enabled.

Preview or watch waveforms:

```bash
daq monitor wave dev1 --profile profiles/examples/example.yaml
daq monitor wave demo --demo
daq monitor wave replay --replay src/daq_cli/monitoring_samples/replay_dump.txt
daq monitor multi-demo
```

The waveform viewer supports keyboard-driven `RUN`, `STOP`, and `SINGLE`
display control for quick frame inspection.
