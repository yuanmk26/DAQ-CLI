# daq-cli User Guide

## 1. Purpose

This guide explains how to use the currently implemented parts of `daq-cli`.

At the moment, the most useful command paths are:

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

These commands use the profile file in `profiles/` and the legacy DAQ project referenced by `legacy.project_root`.

## 2. Prerequisites

Before using the CLI, make sure:

- Python 3.10 or newer is available
- The legacy hardware project exists on disk
- The board is reachable through the configured IP and ports
- The selected profile points to the correct legacy project path

The current implementation depends on the legacy scripts under:

```text
FDU-ADC-250M-16ch/script
```

## 3. Installation

From the repository root:

```bash
pip install -e .
```

After installation, the `daq` command should be available:

```bash
daq --help
```

If you do not want to install it yet, you can also run it directly:

```bash
$env:PYTHONPATH='src'
python -m daq_cli.main --help
```

## 4. Profile File

The CLI uses a YAML profile file to describe devices, groups, defaults, and the legacy project path.

Current example:

```yaml
devices:
  dev1:
    ip: 192.168.10.10
    rbcp_port: 4660
    tcp_port: 24
    board_id: 0
    role: adc

  dev2:
    ip: 192.168.10.11
    rbcp_port: 4660
    tcp_port: 24
    board_id: 1
    role: adc

tcm:
  main:
    ip: 192.168.10.20
    rbcp_port: 4660

groups:
  two_board:
    devices: [dev1, dev2]
    tcm: main

defaults:
  adc_length: 64
  output_dir: out
  trigger_mode: 1
  trigger_position: 40
  thresholds: [1950, 2400, 2300, 2300]

legacy:
  project_root: E:\projects\1-hardware\FDU-ADC-250M-16ch
```

Important fields:

- `devices`: logical names used by CLI commands
- `rbcp_port`: UDP/RBCP port
- `tcp_port`: TCP data port
- `defaults.output_dir`: base output folder for capture results
- `legacy.project_root`: path to the existing hardware-control project

Example command with explicit profile:

```bash
daq board info dev1 --profile profiles/example.yaml
```

## 5. Inspecting the Profile

Use these commands to inspect and validate a profile:

```bash
daq profile show --profile profiles/example.yaml
daq profile validate --profile profiles/example.yaml
```

Note:

- `profile show` prints a simple summary
- `profile validate` checks whether the file can be loaded into the current data model

## 6. Reading Board Information

Use `board info` to confirm that the CLI resolves the logical device correctly:

```bash
daq board info dev1 --profile profiles/example.yaml
```

This command currently shows:

- Device name
- IP
- RBCP port
- TCP port
- Board ID
- Role
- Profile path
- Legacy project root path

This is a profile-backed command. It does not talk to hardware yet.

## 7. Reading FPGA Telemetry

Use `board sysmon` to read telemetry from the board:

```bash
daq board sysmon dev1 --profile profiles/example.yaml
```

This command uses the legacy `lib/sysmon.py` path and currently reports:

- Temperature
- `vccint`
- `vccaux`
- `vccbram`

If this command fails, the likely causes are:

- Wrong device IP
- Wrong RBCP port
- Board not powered or not reachable
- Incorrect `legacy.project_root`

## 8. Configuring a Board

Use `board config` to run the board configuration flow through the legacy script adapter.

Basic usage:

```bash
daq board config dev1 --profile profiles/example.yaml
```

Default behavior:

- ADC configuration: disabled
- Clock configuration: disabled
- Trigger configuration: enabled
- TCP mode-2 configuration: enabled

### 8.1 Step Toggles

Use these options to control which configuration steps run:

```bash
daq board config dev1 --adc
daq board config dev1 --clock
daq board config dev1 --no-trigger
daq board config dev1 --no-tcp-mode2
```

Common examples:

```bash
daq board config dev1 --adc --clock --trigger --tcp-mode2
daq board config dev1 --no-trigger --tcp-mode2
```

### 8.2 Trigger Parameters

The current implementation supports trigger-related options directly from CLI:

```bash
daq board config dev1 \
  --trigger-mode 1 \
  --trigger-position 40 \
  --threshold-1 1950 \
  --threshold-2 2400 \
  --threshold-3 2300 \
  --threshold-4 2300
```

Supported options:

- `--trigger-mode`
- `--trigger-position`
- `--threshold-1`
- `--threshold-2`
- `--threshold-3`
- `--threshold-4`
- `--timestamp-clean/--no-timestamp-clean`
- `--ext-trigger/--no-ext-trigger`
- `--send-start-delay-us`

Important default behavior:

- `ext-trigger` is disabled by default
- `timestamp-clean` is disabled by default

To explicitly keep external trigger disabled:

```bash
daq board config dev1 --no-ext-trigger --profile profiles/example.yaml
```

To explicitly keep timestamp clean disabled:

```bash
daq board config dev1 --no-timestamp-clean --profile profiles/example.yaml
```

Example with external trigger enabled:

```bash
daq board config dev1 \
  --trigger \
  --ext-trigger \
  --trigger-mode 1 \
  --trigger-position 40
```

Example with send-start delay:

```bash
daq board config dev1 --send-start-delay-us 100
```

The command prints:

- Whether configuration succeeded
- Which steps were enabled
- Final trigger-related options
- Captured log output from the legacy script

## 9. Single-Board Capture

Use `acquire single` to capture mode-2 TCP packets from one device.

Basic usage:

```bash
daq acquire single dev1 --profile profiles/example.yaml
```

Useful options:

- `--events`: number of events to capture
- `--timeout`: TCP socket timeout in seconds
- `--output-dir`: base output directory for generated run folders

Examples:

```bash
daq acquire single dev1 --events 100 --profile profiles/example.yaml
daq acquire single dev1 --events 1000 --timeout 10 --profile profiles/example.yaml
daq acquire single dev1 --events 200 --output-dir out/single --profile profiles/example.yaml
```

Current behavior:

- The command uses the legacy `capture_tcp_sent_mode2.py` script through an adapter
- A timestamped run directory is created under the selected output base directory
- Raw event files are written by the legacy script
- A summary table is printed after the run
- The legacy script output is also shown

Typical output data includes:

- Event binary files
- `capture_info.txt`

## 10. Reading Configuration Back

The CLI now supports three levels of read-only configuration inspection.

### 10.1 Semantic Block Readback

These commands read meaningful configuration groups instead of raw register addresses:

```bash
daq board trigger-show dev1 --profile profiles/example.yaml
daq board tcp-mode2-show dev1 --profile profiles/example.yaml
```

`trigger-show` currently reports:

- Trigger mode
- Trigger position
- Four trigger thresholds
- Send-start-delay register value
- Timestamp clean enable state
- External trigger enable state

`tcp-mode2-show` currently reports:

- Send mode
- Integration pre-samples
- Integration post-samples
- Hit thresholds for all 16 channels
- Hit polarities for all 16 channels

### 10.2 Semantic Summary Readback

To view the most important trigger and TCP mode-2 settings together:

```bash
daq board config-show dev1 --profile profiles/example.yaml
```

This is the recommended command for routine verification after configuration.

### 10.3 Raw Register Readback

For low-level debugging, a raw register-read command is also available:

```bash
daq board reg-read dev1 0x10 --len 1 --profile profiles/example.yaml
daq board reg-read dev1 0x11 --len 8 --profile profiles/example.yaml
```

Recommended usage:

- Use `trigger-show`, `tcp-mode2-show`, and `config-show` for normal operation
- Use `reg-read` only when you need to inspect the underlying register bytes directly

## 11. Multi-Board Capture

Use `acquire multi` to run the current legacy multi-board acquisition flow for a
group defined in the profile.

Basic usage:

```bash
daq acquire multi two_board --profile profiles/example.yaml
```

Useful options:

- `--aggregation-key timestamp`
- `--aggregation-key event_count`
- `--timestamp-match-window`
- `--event-timeout-ms`
- `--timeout`
- `--allow-start-without-ack`
- `--output-dir`

Examples:

```bash
daq acquire multi two_board --aggregation-key timestamp --timestamp-match-window 10
daq acquire multi two_board --aggregation-key event_count --allow-start-without-ack
```

Current behavior:

- The command generates a temporary JSON config for the legacy
  `multi_board_acquire.py` script
- The selected group devices and TCM endpoint are taken from the profile
- The legacy script still performs the actual TCM align, TCP receive, packet
  parse, aggregation, and run-file writing
- The command prints the final run directory, generated config path, and status

Typical output data includes:

- `run_meta.json`
- `complete_events.dat`
- `partial_events.dat`
- `complete_events.idx`
- `monitor.jsonl`
- `log.txt`

## 12. Waveform Monitoring

Use `monitor wave` to open a 16-channel waveform monitor window.

Basic live usage:

```bash
daq monitor wave dev1 --profile profiles/example.yaml
```

Important behavior:

- The live monitor reads the current `send_mode`
- It then switches the board to `send_mode = 1` for full-waveform output
- On exit, it attempts to restore the original `send_mode`
- The viewer supports runtime `RUN`, `STOP`, and `SINGLE` display control

Offline preview modes:

```bash
daq monitor wave demo --demo
daq monitor wave replay --replay src/daq_cli/monitoring_samples/replay_dump.txt
```

Preview notes:

- `--demo` uses a bundled sample frame set
- `--replay` reads a structured dump file and replays it in the same 16-channel view
- `--demo` and `--replay` are mutually exclusive
- The viewer scales its default window size to the current screen when possible

The monitor window currently shows:

- 16 channels in a 4x4 layout
- Current viewer state: `RUN`, `STOP`, or `SINGLE-ARMED`
- Current `event_count`
- Current `timestamp`
- Current `hit_mask`
- Current `send_mode`
- Current source mode: `live`, `demo`, or `replay`

Viewer keyboard controls:

- `space`: toggle between `RUN` and `STOP`
- `s`: arm `SINGLE`, wait for the next frame, then freeze on it
- `r`: force the viewer back to `RUN`
- `q`: close the viewer

Mode definitions:

- `RUN`: keep consuming the stream and refresh on the latest frame
- `STOP`: freeze the current display while the live stream continues in the background
- `SINGLE`: wait for the next incoming frame, display it once, then automatically return to `STOP`

`SINGLE` here means "wait for the next frame and freeze on it". It does not stop
hardware acquisition and it is not a hardware single-shot sampling mode.

## 13. Suggested Workflow

A simple single-board workflow looks like this:

1. Validate the profile.
2. Check board metadata.
3. Read telemetry.
4. Configure the board.
5. Read configuration back.
6. Run single-board capture.

Example:

```bash
daq profile validate --profile profiles/example.yaml
daq board info dev1 --profile profiles/example.yaml
daq board sysmon dev1 --profile profiles/example.yaml
daq board config dev1 --profile profiles/example.yaml
daq board config-show dev1 --profile profiles/example.yaml
daq acquire single dev1 --events 100 --profile profiles/example.yaml
```

For a synchronized multi-board run:

```bash
daq profile validate --profile profiles/example.yaml
daq board config dev1 --profile profiles/example.yaml
daq board config dev2 --profile profiles/example.yaml
daq acquire multi two_board --profile profiles/example.yaml
```

## 14. Current Limitations

Not implemented yet:

- Additional monitor commands beyond `monitor wave`
- Separate `wave` command workflows
- Interactive shell mode
- Native protocol and parser modules independent of legacy scripts

Current technical limitation:

- `board config`, `acquire single`, and `acquire multi` still rely on legacy
  script behavior under the external project path
- `monitor wave` currently supports only `send_mode = 1` full-waveform monitoring
- `monitor wave` currently supports only single-board monitoring
- `monitor wave` currently has no advanced trigger conditions or frame history buffer

## 15. Troubleshooting

### Command not found

If `daq` is not found, either:

- run `pip install -e .`
- or use `python -m daq_cli.main ...`

### Profile loads but hardware commands fail

Check:

- Device IP
- RBCP port
- TCP port
- Physical network connection
- Board power state
- `legacy.project_root`

### Capture does not create output

Check:

- Whether the board was configured first
- Whether the TCP port is correct
- Whether the board is sending mode-2 data
- Whether the selected output directory is writable

### Multi-board run does not start

Check:

- Whether the selected group defines a valid `tcm`
- Whether each device in the group has the correct `board_id`
- Whether the TCM IP and RBCP port are reachable
- Whether you need `--allow-start-without-ack` for current bring-up conditions

### Wave monitor does not start

Check:

- Whether `matplotlib` is installed in the current environment
- Whether the board TCP port is reachable for live mode
- Whether the dump path passed to `--replay` is readable
- Whether the board is producing `send_mode = 1` packets after the CLI switches modes

## 16. Related Documents

- [Architecture](./architecture.md)
- [CLI Design](./cli-design.md)
- [Firmware Compatibility Notes](./firmware-compatibility.md)
