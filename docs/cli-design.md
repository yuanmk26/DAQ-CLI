# daq-cli Command Design

## 1. Command Model

`daq-cli` should be organized as a command-driven tool with a small number of clear top-level command groups.

Recommended top-level commands:

- `profile`
- `board`
- `group`
- `acquire`
- `monitor`
- `wave`
- `shell`

The first release does not need to fully implement every command, but the namespace should be planned from the beginning.

Current implementation status:

- `profile`: partially implemented
- `board`: partially implemented with real hardware-backed flows
- `acquire`: partially implemented for single-board and multi-board capture
- `group`: placeholder only
- `monitor`: placeholder only
- `wave`: placeholder only
- `shell`: not implemented

## 2. Profile Commands

Purpose:

- Manage and validate configuration profiles
- Select devices and groups by logical name instead of hard-coded IPs

Planned commands:

```bash
daq profile list
daq profile show <profile>
daq profile validate <profile>
```

Current implementation:

```bash
daq profile show
daq profile validate
daq profile show profiles/example.yaml
daq profile validate profiles/example.yaml
```

Possible future extensions:

```bash
daq profile init
daq profile edit <profile>
daq profile use <profile>
```

## 3. Board Commands

Purpose:

- Perform single-board operations
- Support both safe high-level actions and low-level debugging

Planned commands:

```bash
daq board info <device>
daq board sysmon <device>
daq board config <device>
daq board reg read <device> <address> --len <n>
daq board reg write <device> <address> <value>
daq board trigger show <device>
daq board trigger set <device> --mode <n> --position <n> --thresholds <a> <b> <c> <d>
daq board tcp-mode2 show <device>
daq board tcp-mode2 set <device> --pre <n> --post <n>
```

First-phase minimum:

- `info`
- `sysmon`
- `config`

Current implementation details:

- `daq board info <device>` works
- `daq board sysmon <device>` works through the legacy `sysmon.py` adapter
- `daq board config <device>` works through the legacy configuration script adapter
- `daq board trigger-show <device>` works
- `daq board tcp-mode2-show <device>` works
- `daq board config-show <device>` works
- `daq board reg-read <device> <address>` works

Current `board config` options:

```bash
daq board config dev1 --adc --clock --trigger --tcp-mode2
daq board config dev1 --trigger-mode 1 --trigger-position 40
daq board config dev1 --threshold-1 1950 --threshold-2 2400 --threshold-3 2300 --threshold-4 2300
daq board config dev1 --timestamp-clean
daq board config dev1 --no-timestamp-clean
daq board config dev1 --ext-trigger
daq board config dev1 --no-ext-trigger
daq board config dev1 --send-start-delay-us 100
```

Current defaults:

- `ext-trigger` is off unless `--ext-trigger` is passed
- `timestamp-clean` is off unless `--timestamp-clean` is passed

Current readback commands:

```bash
daq board trigger-show dev1
daq board tcp-mode2-show dev1
daq board config-show dev1
daq board reg-read dev1 0x10 --len 1
```

Recommended usage model:

- Prefer `trigger-show`, `tcp-mode2-show`, and `config-show` for normal operation
- Use `reg-read` only for low-level debugging

## 4. Group Commands

Purpose:

- Run coordinated operations on multiple boards
- Encapsulate TCM-aware workflows

Planned commands:

```bash
daq group info <group>
daq group config <group>
daq group align <group>
daq group start <group>
daq group stop <group>
```

First-phase minimum:

- `info`
- `config`
- `align`

Current status:

- Placeholder only

## 5. Acquire Commands

Purpose:

- Start data capture in single-board or multi-board modes

Planned commands:

```bash
daq acquire single <device> --events 1000
daq acquire single <device> --duration 10s
daq acquire multi <group>
daq acquire multi <group> --output out/run1
```

Expected behavior:

- Create a timestamped output directory
- Save run metadata
- Save acquisition logs
- Save data products in a structured format

First-phase minimum:

- `single`
- `multi`

Current implementation:

```bash
daq acquire single <device> --events 1000
daq acquire single <device> --timeout 10
daq acquire single <device> --output-dir out/single
daq acquire multi <group>
daq acquire multi <group> --aggregation-key event_count
```

Implementation note:

- `single` currently runs through the legacy `capture_tcp_sent_mode2.py` script adapter
- `multi` currently runs through the legacy `multi_board_acquire.py` script adapter

## 6. Monitor Commands

Purpose:

- Observe health and connectivity over time

Planned commands:

```bash
daq monitor board <device>
daq monitor board <device> --watch
daq monitor group <group>
daq monitor group <group> --watch --interval 1
```

Expected monitored values:

- FPGA temperature
- `vccint`
- `vccaux`
- `vccbram`
- RBCP reachability
- TCP reachability
- Recent data activity

First-phase minimum:

- `board`
- `board --watch`

Current status:

- Placeholder only

## 7. Wave Commands

Purpose:

- Inspect waveform data for selected channels
- Support both quick checks and live viewing

Planned commands:

```bash
daq wave show <device> --channels 0 1
daq wave watch <device> --channels 0 1
daq wave save <device> --channels 0 1 --events 200 --out out/wave1
daq wave watch-group <group> --board <device> --channels 0 1
```

Recommended first-phase implementation:

- `wave watch <device> --channels ...`

Suggested first-phase behavior:

- Start a data stream
- Decode incoming frames
- Filter selected channels
- Open a waveform display window
- Refresh the displayed traces in near real time

The initial viewer only needs a few controls:

- Pause/resume
- Current event number
- Timestamp display
- Save current frame

Current status:

- Placeholder only

## 8. Shell Mode

Purpose:

- Provide an interactive mode for repeated operations without retyping full commands

Planned command:

```bash
daq shell
```

Example session:

```text
daq> profile use lab
daq[lab]> use dev1
daq[lab|dev1]> info
daq[lab|dev1]> config
daq[lab|dev1]> sysmon
daq[lab|dev1]> wave watch --channels 0 1
```

Recommendation:

- Keep shell mode out of the first implementation milestone
- Build it after the normal CLI commands are stable

Current status:

- Not implemented

## 9. Profile Structure

Recommended profile format:

```yaml
devices:
  dev1:
    ip: 192.168.10.10
    rbcp_port: 4660
    tcp_port: 24
    board_id: 0

  dev2:
    ip: 192.168.10.11
    rbcp_port: 4660
    tcp_port: 24
    board_id: 1

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
  project_root: E:\\projects\\1-hardware\\FDU-ADC-250M-16ch
```

Current implementation note:

- `profiles/example.yaml` follows this structure and is used by the working commands today.

## 10. First Milestone

The first milestone should produce a usable command-line skeleton with the following command paths working end-to-end:

- `daq board info <device>`
- `daq board sysmon <device>`
- `daq board config <device>`
- `daq acquire single <device>`
- `daq monitor board <device> --watch`
- `daq wave watch <device> --channels ...`

This milestone is enough to validate:

- Profile loading
- Device selection
- Hardware communication
- Console output structure
- Waveform visualization path

Current milestone progress:

- Done:
  - `daq board info <device>`
  - `daq board sysmon <device>`
  - `daq board config <device>`
  - `daq board trigger-show <device>`
  - `daq board tcp-mode2-show <device>`
  - `daq board config-show <device>`
  - `daq board reg-read <device> <address>`
  - `daq acquire single <device>`
  - `daq acquire multi <group>`
- Not done yet:
  - `daq monitor ...`
  - `daq wave ...`

## 11. Follow-Up Milestone

After the first milestone works, the next expansion should add:

- Group alignment workflows
- Better waveform controls
- Run metadata persistence
- Shell mode
- More complete testing
