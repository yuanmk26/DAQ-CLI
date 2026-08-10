# daq-cli User Guide

## 1. Purpose

This guide explains how to use the currently implemented parts of `daq-cli`.

At the moment, the most useful command paths are:

- `daq board info <device>`
- `daq board sysmon <device>`
- `daq board config <device>`
- `daq board trigger-show <device>`
- `daq board tcp-mode2-show <device>`
- `daq board send-mode-set <device> <mode>`
- `daq board config-show <device>`
- `daq board reg-read <device> <address>`
- `daq acquire single <device>`
- `daq acquire multi <group>`
- `daq monitor wave <device>`

These commands use a YAML profile file and the vendored legacy control scripts bundled inside `daq-cli`.

## 2. Prerequisites

Before using the CLI, make sure:

- Python 3.10 or newer is available
- The board is reachable through the configured IP and ports
- The selected profile points to the correct boards and TCM

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

The CLI uses a YAML profile file to describe devices, groups, and defaults.

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
```

Important fields:

- `devices`: logical names used by CLI commands
- `rbcp_port`: UDP/RBCP port
- `tcp_port`: TCP data port
- `defaults.output_dir`: base output folder for capture results
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
- `--send-mode`
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

Example with send mode:

```bash
daq board config dev1 --send-mode 1 --profile profiles/example.yaml
```

The command prints:

- Whether configuration succeeded
- Which steps were enabled
- Final trigger-related options
- Optional `send_mode` write request and readback
- `Pre-write Read Send Mode` when the legacy config log reports the mode before the CLI writeback
- `Final verified send_mode: ...` after the CLI readback check succeeds
- Captured log output from the legacy script

## 9. Single-Board Capture

Use `acquire single` to capture mode-2 TCP packets from one device.

Basic usage:

```bash
daq acquire single dev1 --profile profiles/example.yaml
```

You can move the common `acquire single` defaults into the profile to keep commands short:

```yaml
defaults:
  output_dir: out
  acquire_single:
    events: 1000
    timeout_s: 10.0
    progress_every: 50
    watch_every: null
    outputs:
      raw:
        enabled: true
      json:
        enabled: false
      text:
        enabled: true
        dir: out/text
        max_events_per_file: 1000
        waveform_layout: point_rows
      log:
        enabled: false
  acquire_multi:
    aggregation_key: timestamp
    timestamp_match_window_ticks: 10
    event_timeout_ms: 50
    tcp_timeout_s: 1.0
    allow_start_without_ack: true
    watch_waveforms: false
    watch_every: 100
    outputs:
      raw:
        enabled: true
      json:
        enabled: false
      text:
        enabled: true
        dir: out/multi_text
        max_events_per_file: 1000
        waveform_layout: point_rows
      log:
        enabled: true
        dir: out/logs
```

When these keys are present, `daq acquire single dev1 --profile profiles/example.yaml` and `daq acquire multi two_board --profile profiles/example.yaml` will use them automatically, and any explicit CLI option still overrides the profile value.

Useful options:

- `--events`: number of events to capture
- `--timeout`: TCP socket timeout in seconds
- `--output-dir`: base output directory for generated run folders
- `--decode-json`: also generate decoded JSON during capture
- `--decoded-output-dir`: choose where online decoded JSON files are written
- `--watch-every`: show a low-rate waveform watch window using every Nth captured event
- `--progress-every`: print one live progress line every N captured events

Profile-driven output routing:

- `outputs.raw.enabled/dir`: control raw packet file output
- `outputs.json.enabled/dir`: control decoded JSON output
- `outputs.text.enabled/dir`: control TXT event output
- `outputs.text.max_events_per_file`: roll TXT files after N events
- `outputs.text.waveform_layout`: recommends `point_rows`; legacy `channel_blocks` values remain accepted and render with the same point-row output
- `outputs.log.enabled/dir`: control capture log file output
- `--decode-json` and `--raw-only` only toggle JSON output; they do not disable TXT output

Examples:

```bash
daq acquire single dev1 --events 100 --profile profiles/example.yaml
daq acquire single dev1 --events 1000 --timeout 10 --profile profiles/example.yaml
daq acquire single dev1 --events 200 --output-dir out/single --profile profiles/example.yaml
daq acquire single dev1 --events 100 --decode-json --profile profiles/example.yaml
daq acquire single dev1 --events 1000 --watch-every 100 --profile profiles/example.yaml
daq acquire single dev1 --events 1000 --progress-every 50 --profile profiles/example.yaml
```

Current behavior:

- The command reads the board's current `send_mode` before capture
- The native single-board receiver parses packet length from that `send_mode`
- Current single-board capture supports firmware `send_mode` 0, 1, 2, and 3
- A timestamped run directory is created under the selected output base directory
- Raw event files are written by the native runner in the same per-event format as before
- `--decode-json` adds a separate online decode pipeline that writes JSON when `outputs.json.enabled` is on
- The online decode pipeline is best-effort and does not take priority over raw capture throughput
- `--watch-every N` opens a waveform watch viewer and refreshes it with every Nth captured event
- The watch viewer is a best-effort sampling path that always yields to raw capture throughput
- A line-by-line live monitor shows progress, event rate, latest `hit_mask`, packet bytes, and output directory during capture
- `--progress-every N` throttles those live progress lines while still forcing the final `events=N/N` line
- `defaults.acquire_single` in the profile can provide default values for `events`, `timeout_s`, `output_dir`, `watch_every`, `progress_every`, and `outputs.*`
- A summary table is printed after the run
- A final native capture summary is also shown

Typical output data includes:

- Event binary files
- Optional decoded JSON files under the configured JSON output directory
- Optional TXT files such as `events_00001.txt` under the configured text output directory
- Optional capture log file under the configured log output directory
- `capture_info.txt`

## 10. Offline Decode

Use `decode` to convert raw single-board event packets into structured JSON.

Run-level decode:

```bash
daq decode run out/single/20260606_205506
```

Single-event decode:

```bash
daq decode event out/single/20260606_205506/raw/event_00000.bin
```

Multi-board aggregated decode:

```bash
daq decode multi-run out/multi/two_board_20260607_220946
```

Useful options:

- `--output-dir`: choose where decoded JSON files are written
- `--overwrite`: replace existing JSON outputs
- `--limit`: decode only the first N event files when using `decode run`
- `decode multi-run` writes aggregated-event JSON into `decoded/complete/` and `decoded/partial/`

Current behavior:

- `decode run` scans `raw/event_*.bin` in filename order
- `decode multi-run` scans `complete_events.dat` and `partial_events.dat`
- If `capture_info.txt` exists, it uses `send_mode` and `adc_length` as decode context
- First-version output is one JSON file per event
- The decoder supports `send_mode` 0, 1, 2, and 3
- For partial-waveform modes, JSON still uses a fixed 16-channel structure, with missing channels written as `null`
- Multi decoded JSON is organized by aggregated event, not by original board packet

The mode1 sample directory below is a good first validation target:

```bash
daq decode run out/single/20260606_205506
```

## 11. Reading Configuration Back

The CLI now supports three levels of read-only configuration inspection.

### 11.1 Semantic Block Readback

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

To write the current board `send_mode` directly:

```bash
daq board send-mode-set dev1 1 --profile profiles/example.yaml
daq board tcp-mode2-show dev1 --profile profiles/example.yaml
```

Supported modes:

- `0`: hit-selected waveform
- `1`: full-channel waveform
- `2`: hit-selected feature
- `3`: hit-selected feature + waveform

Important behavior:

- `send-mode-set` writes the board's current `send_mode` persistently
- it immediately reads the value back and fails if the readback does not match
- `board config --send-mode ...` uses the same write-and-readback verification path
- this is different from `monitor wave`, which temporarily switches to `send_mode = 1` for the live viewer session and then restores the previous mode

### 11.2 TCM Trigger-Link Readback

The TCM trigger link (firmware `b02db46`+) adds real-time per-channel
threshold crossing that pulses the M21 line toward the TCM board; the TCM
board can return a wide MOSI pulse that acts as the acquisition trigger
(`Trigger_model = 9`). Read the current configuration without writing:

```bash
daq board tcm-link-show dev1 --profile profiles/example.yaml
```

`tcm-link-show` reports:

- Channel mask (which channels participate)
- Polarity mask (pos = `adc > thr`, neg = `adc < thr`)
- Debounce interval (5ns units)
- M21 pulse width (5ns units)
- Enable state
- Thresholds for the enabled channels

Write the configuration with readback verification:

```bash
daq board tcm-link-config dev1 \
  --mask 0x0003 --polarity 0x0002 --thr 2700,1800 \
  --debounce 200 --width 20 --enable \
  --profile profiles/example.yaml
```

Options:

- `--mask` (required): 16-bit channel mask, decimal or `0x`-prefixed hex
- `--polarity`: 0 = pos (`adc>thr`), 1 = neg (`adc<thr`)
- `--thr`: single value broadcast to all 16 channels, or 16 comma-separated values
- `--debounce`: min pulse interval in 5ns units (default 200 = 1us)
- `--width`: M21 pulse width in 5ns units (default 20 = 100ns)
- `--enable/--disable`: pulse output enable (default enabled)

TCM-link notes:

- the registers (`0x45..0x6C`) are fully decoupled from the event `hit`
  thresholds (`0x20..0x3F`)
- polarity direction matters: a positive-signal threshold must sit above the
  baseline, a negative one below it
- with the TCM link, keep `Trigger_position` at 0..10 (measured link delay
  D ≈ 397ns), otherwise the crossing point may fall outside the event window
- `--trigger-mode 9` is accepted by `board config` as the TCM-trigger source

### 11.3 TCM Board Trigger-Link Commands

The TCM board (FDU-TCM v2 firmware `5550276`+) receives the M21 threshold
pulses from up to 8 ADC boards, applies a mask-OR decision, and broadcasts a
wide trigger pulse back. Its trigger-link registers live at `0x20..0x25`:

| Address | Content |
| --- | --- |
| `0x20` | TRG_CTRL: bit0 = enable, bit1 = clear trigger sticky (write 1) |
| `0x21` | TRG_IN_MASK: 8-bit channel participation mask |
| `0x22` | TRG_PULSE_WIDTH: wide pulse width in 20M cycles (default 32 = 1.6us) |
| `0x23` | TRG_DEBOUNCE: debounce in 20M cycles (default 20 = 1us) |
| `0x24` | TRG_STATUS: bit0 = trig_sticky, bit1 = pending, bit2 = wide pulse active |
| `0x25` | TRG_CHAN: channels of the most recent trigger event |

Read the current configuration and status:

```bash
daq tcm show main --profile profiles/example.yaml
```

Write the configuration with readback verification:

```bash
daq tcm config main --mask 0x01 --width 32 --debounce 20 --enable \
  --clear-sticky --profile profiles/example.yaml
```

Options:

- `--enable/--disable`: trigger-link enable (default enabled)
- `--mask`: 8-bit participation mask, decimal or `0x`-prefixed hex (default 0)
- `--width`: wide pulse width in 20M cycles, 0..255 (default 32)
- `--debounce`: debounce in 20M cycles, 0..65535 (default 20)
- `--clear-sticky/--keep-sticky`: clear the trigger sticky status bit after
  writing (default keep)

`tcm show` also reports `trig_sticky` / `pending` / `wide_pulse_active` and
the `last_trigger_channels` mask — useful during TCM-link bring-up to confirm
the trigger actually arrived and which board channel fired.

TCM-link integration notes:

- the TCM `TRG_IN_MASK` channel N corresponds to ADC board N's M21 pulse
- the TCM wide pulse must be >= 800ns (16 cycles) for the ADC side to
  recognize it as a trigger return
- keep the ADC-side `Trigger_position` at 0..10 while the TCM link drives
  acquisition (measured link delay D ≈ 397ns)

### 11.4 Semantic Summary Readback

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
- `--decode-json`
- `--watch-waveforms`
- `--watch-every`
- `--output-dir`

Examples:

```bash
daq acquire multi two_board --aggregation-key timestamp --timestamp-match-window 10
daq acquire multi two_board --aggregation-key event_count --allow-start-without-ack
daq acquire multi two_board --decode-json
daq acquire multi two_board --watch-waveforms --watch-every 100
```

Current behavior:

- The command generates a temporary JSON config for the legacy
  `multi_board_acquire.py` script
- The selected group devices and TCM endpoint are taken from the profile
- The legacy script still performs the actual TCM align, TCP receive, packet
  parse, aggregation, and run-file writing
- `--decode-json` enables multi-board decoded JSON output
- `--watch-waveforms` adds a best-effort sampled waveform monitor with one window, same-aggregate-event board switching, and short history navigation
- Multi waveform watch only supports boards currently sending waveform-bearing modes `1` or `3`
- The watcher samples packets from the legacy multi receive path; it does not read waveform data from `monitor.jsonl`
- If you want the viewer to follow essentially every watched event, use `--watch-every 1`; larger values intentionally sample the stream
- `defaults.acquire_multi` in the profile can provide default values for `output_dir`, `aggregation_key`, `timestamp_match_window_ticks`, `event_timeout_ms`, `tcp_timeout_s`, `allow_start_without_ack`, `watch_waveforms`, `watch_every`, and `outputs.*`
- The command prints the final run directory, generated config path, and status

Typical output data includes:

- `run_meta.json`
- `complete_events.dat`
- `partial_events.dat`
- `complete_events.idx`
- `monitor.jsonl`
- `log.txt`
- `complete/event_XXXXX.json` and `partial/event_XXXXX.json` under the configured JSON output root when multi decode is enabled
- `complete/events_00001.txt` and `partial/events_00001.txt` under the configured text output root when TXT output is enabled

Multi decoded JSON is written per aggregated event, not per original board packet.
Each JSON contains top-level aggregation metadata plus one decoded board entry
for each board that was present in that event. Partial events are decoded too,
and include `missing_board_ids` derived from the aggregated file mask.

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
daq monitor multi-demo
```

Preview notes:

- `--demo` uses a bundled sample frame set
- `--replay` reads a structured dump file and replays it in the same 16-channel view
- `--demo` and `--replay` are mutually exclusive
- `monitor multi-demo` opens a two-board offline viewer with about 100 sampled events by default
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

- `space`: toggle between `RUN` and `STOP`; returning to `RUN` immediately jumps to the latest cached event on the selected board
- `s`: arm `SINGLE`, wait for the next frame, then freeze on it
- `r`: force the viewer back to `RUN` and immediately jump to the latest cached event on the selected board
- `tab`, `]`, `[` and `1-9`: switch boards in the multi-board watcher while keeping the same aggregated event
- `,` or `left`: in `STOP` only, move to the previous captured event in the selected board history
- `.` or `right`: in `STOP` only, move to the next captured event in the selected board history
- `q`: close the viewer

Multi-board watcher notes:

- Board switching locks onto the same aggregated event across boards instead of each board's latest frame
- In the multi-board viewer, title `event=` and `timestamp=` are aggregated-event values, not the raw per-board packet fields
- If another board does not yet belong to the selected aggregated event, the title reports that the event is missing on that board
- The multi-board watcher keeps a short recent history per board so you can step backward and forward through sampled events
- That recent history is intentionally much larger than before, but it is still a recent-window cache rather than the full run archive
- The multi-board viewer also keeps a small recent update queue so same-event board switching can compare multiple board updates before they are drained into the viewer cache
- History browsing is only available in `STOP`; `RUN` always tracks the latest event for the selected board
- `daq monitor multi-demo --events 100` is the quickest offline way to test this behavior without hardware

Mode definitions:

- `RUN`: keep consuming the stream and refresh on the latest frame
- `STOP`: freeze the current display while the live stream continues in the background
- `SINGLE`: wait for the next incoming frame, display it once, then automatically return to `STOP`

`SINGLE` here means "wait for the next frame and freeze on it". It does not stop
hardware acquisition and it is not a hardware single-shot sampling mode.

## 13. GUI Console

Since v0.3.0 the desktop GUI console wraps the full CLI surface. It needs no
new dependencies (tkinter ships with Python on Windows).

Launch it:

```bash
daq-gui --profile profiles/example.yaml
```

or from the CLI:

```bash
daq gui --profile profiles/example.yaml
```

> Prefer `daq-gui`: it selects the TkAgg matplotlib backend before any other
> import, which the `daq gui` subcommand cannot guarantee.

The window has four tabs plus a shared log panel at the bottom:

- **板卡**: device dropdown with info / sysmon / trigger-show /
  tcp-mode2-show / config-show / tcm-link-show buttons, the board config
  form (step toggles, trigger parameters, thresholds, send-mode), a full
  **TCM 触发 (mode 9) 寄存器面板** — three groups of editable registers:
  trigger source (`0x10` model, `0x19` position, `0x06` Time_clean /
  EXT_Trigger, `0x1B~1D` start delay), the TCM link (`0x45~6C` with 16
  per-channel threshold fields plus a broadcast-fill helper, mask,
  polarity, debounce, width, enable), and data format (`0x42` send mode,
  `0x43/0x44` integration samples). **应用全部并回读验证** writes every
  group and verifies by readback; **回读刷新** fills the form from the
  current registers. Per-channel thresholds exist because channel baselines
  differ — use the broadcast-fill only when they match. The register reader
  shows hex dumps.
- **采集**: single capture (device, events, timeout, output switches) with a
  live progress bar, and multi capture (group, aggregation key, match
  window, no-ack allowance) with a busy indicator and result summary.
- **监视**: waveform monitor with live / demo / replay sources and
  RUN / STOP / SINGLE buttons. Stopping the monitor restores the board's
  original `send_mode`. Use demo or replay to try it without hardware.
- **TCM**: TCM board trigger-link show (configuration + status: sticky,
  pending, wide pulse, last trigger channels) and config with readback
  verification and an optional clear-sticky.

All operations run in background threads; the UI never blocks. The shared
log panel keeps the last 5000 lines.

## 14. Suggested Workflow

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

## 15. Current Limitations

Not implemented yet:

- Additional monitor commands beyond `monitor wave`
- Separate `wave` command workflows
- Interactive shell mode

Current technical limitation:

- `board config`, `acquire single`, and `acquire multi` still rely on bundled
  legacy script behavior
- `monitor wave` currently supports only `send_mode = 1` full-waveform monitoring
- `monitor wave` currently supports only single-board monitoring
- `monitor wave` currently has no advanced trigger conditions or frame history buffer
- cross-board crossing alignment stays at 20M (50ns) precision; the 200M fine
  fields are board-local and must not be compared across boards

## 16. Troubleshooting

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

## 17. Related Documents

- [Architecture](./architecture.md)
- [CLI Design](./cli-design.md)
- [Firmware Compatibility Notes](./firmware-compatibility.md)
