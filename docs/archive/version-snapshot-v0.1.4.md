# daq-cli v0.1.4 Version Snapshot (Archive)

This document is a fixed reference of the `daq-cli` state before the next
development cycle. It is archived at tag `v0.1.4` and summarizes the key
content of the whole v0.1.x line: command surface, profile format, firmware
contract, architecture, release flow, tests, and known limitations.

> Note: `v0.1.4` is an archive tag, not a published release. No offline
> release package was built for it.

## 1. Version State

- Tag: `v0.1.4` at commit `b11e172` (2026-06-16)
- Version: `pyproject.toml` = `0.1.4`, `src/daq_cli/__init__.py` `__version__` = `0.1.4`
- Python: `>=3.10`
- Dependencies: `matplotlib>=3.8`, `pyyaml>=6.0`, `typer>=0.12,<1.0`, `rich>=13.0`
- Entry point: `daq = daq_cli.main:main`

## 2. Command Surface

| Command | Description |
|---|---|
| `daq profile show / validate / init` | Inspect, validate, and generate machine-local profiles |
| `daq board info <device>` | Device metadata and legacy project path |
| `daq board sysmon <device>` | FPGA telemetry: temperature, `vccint`, `vccaux`, `vccbram` |
| `daq board config <device>` | Board setup via step toggles (`--adc/--clock/--trigger/--tcp-mode2`) and trigger options (`--trigger-mode`, `--trigger-position`, `--threshold-1..4`, `--timestamp-clean`, `--ext-trigger`, `--send-start-delay-us`) |
| `daq board trigger-show <device>` | Trigger config readback (no write) |
| `daq board tcp-mode2-show <device>` | `TCP_SENT` config readback (no write) |
| `daq board config-show <device>` | Combined semantic readback summary |
| `daq board reg-read <device> <address>` | Raw register read for debugging |
| `daq acquire single <device>` | Single-board capture with independent `raw` / `json` / `text` / `log` outputs and indexed run directories |
| `daq acquire multi <group>` | Multi-board capture: TCM alignment, aggregation by `timestamp` / `event_count`, streamed decode, waveform watch |
| `daq monitor wave <device>` | Live waveform preview (also `--demo`, `--replay`) with `RUN` / `STOP` / `SINGLE` keys |
| `daq monitor multi-demo` | Multi-board viewer demo |

Not implemented yet: additional `daq monitor ...` commands, `daq wave ...`,
`daq shell`.

## 3. Profile Format

`profiles/example.yaml` is the reference layout:

```yaml
devices:    # name -> ip / rbcp_port / tcp_port / board_id / role
tcm:        # name -> ip / rbcp_port
groups:     # name -> devices[] / tcm
defaults:
  adc_length: 64
  output_dir: out
  trigger_mode: 7
  trigger_position: 40
  thresholds: [1950, 2400, 2300, 2300]
  acquire_single:
    events: 1000
    timeout_s: 10.0
    progress_every: 50
    watch_every: 50
    outputs:            # raw / json / text / log, each with enabled + dir
      raw:  { enabled: true,  dir: out/raw }
      json: { enabled: true,  dir: out/json }
      text: { enabled: false, dir: out/text, max_events_per_file: 100,
              waveform_layout: point_rows }
      log:  { enabled: false, dir: out/log }
  acquire_multi:
    aggregation_key: timestamp        # or event_count
    timestamp_match_window_ticks: 10
    event_timeout_ms: 50
    tcp_timeout_s: 1.0
    allow_start_without_ack: true
    watch_waveforms: true
    watch_every: 100
    stop_on_watch_close: true
    outputs:            # same shape as acquire_single, default dirs out/multi_*
legacy:
  project_root: <path to FDU-ADC-250M-16ch>
```

Text output formats: `waveform_layout: channel_blocks | point_rows`;
segmented files `events_00001.txt` with `max_events_per_file` events each.

## 4. Firmware Contract (Stable Facts)

See `docs/firmware-compatibility.md` for the full reference. Key points:

- Stable RBCP register window `0x00..0x44` (config fields in `0x00..0x44`):
  - `0x06` bit1 `Time_clean`, bit2 `EXT_Trigger_en` — **must be
    read-modify-write, never blind whole-byte writes**
  - `0x10` `Trigger_model`; `0x11..0x18` 4 trigger thresholds (big-endian);
    `0x19` `Trigger_position`; `0x1A` `ADC_CONFIG`;
    `0x1B..0x1D` `SEND_START_DELAY[23:0]`
  - `0x20..0x3F` 16 hit thresholds; `0x40..0x41` 16 hit polarities
  - `0x42` `Send_mode`; `0x43` `Integ_pre_samples`; `0x44` `Integ_post_samples`
- `TCP_SENT` packet has **four modes**:
  `0` hit-selected waveform, `1` full-channel waveform,
  `2` hit-selected feature, `3` feature + waveform
  (`send_mode = 2` is **not** feature+waveform anymore)
- Fixed 20-byte packet header: `0xFF 0xFE 0x01` magic, `send_mode`,
  `event_count[31:0]`, `timestamp[63:0]`, `hit_mask[15:0]`, feature record
  length, reserved. Payload length must be derived from `send_mode`.
- Feature record (modes 2/3), 10 bytes per selected channel: channel id,
  `baseline[15:0]`, `peak_amp[15:0]`, `peak_pos[7:0]`, `integral[31:0]`.
- The `tcp-mode2-*` command names are historical; they operate on the
  `0x42..0x44` registers. A later rename toward `tcp-sent` / `packet-mode`
  terminology is planned.

## 5. Architecture and Key Modules

Layered layout under `src/daq_cli/` (~9600 lines including tests):

| Layer | Key modules |
|---|---|
| `cli/` | `app.py`, `board.py`, `acquire.py`, `monitor.py`, `wave.py`, `profile.py`, `group.py`, `decode.py`, `common.py` |
| `application/` | `board_service.py`, `acquire_service.py`, `telemetry_service.py`, `monitor_service.py`, `decode_service.py`, `multi_decode_service.py`, `profile_service.py`, `config_models.py`, `models.py`, `output_config.py` |
| `domain/` | `device.py`, `group.py` |
| `infrastructure/` | `config_loader.py`, `run_name_allocator.py`, `tcp_sent_protocol.py`, `tcp_sent_decode.py`, `multi_board_decode.py`, `text_event_writer.py`, `wave_monitor.py`; `adapters/` wraps the legacy hardware scripts; `_vendor/fdu_legacy/` holds the vendored legacy project code |
| `presentation/` | `console/printers.py`, `wave_monitor_viewer.py` |
| `monitoring_samples/` | demo frames and replay dumps for the wave viewer |

Vendored legacy scripts (`_vendor/fdu_legacy/`): `FPGA_CTRL.py`,
`HMCAD1511.py`, `multi_board_acquire.py`, `mux.py`, `si5345_16ch.py`,
`start_16CH_two_board.py`, plus `lib/{i2c,rbcp,spi_3wire,sysmon}.py`.

## 6. Release Flow

1. Update version in `pyproject.toml` and review user-facing docs
   (`README.md`, `docs/usage.md`, profiles).
2. `python -m pytest`
3. `.\scripts\build_release.ps1` — builds wheel + sdist, downloads dependency
   wheels, produces `dist\daq_cli-<version>-offline-win-amd64.zip`
   (needs network access at build time).
4. Tag `v<version>` matching `pyproject.toml`, push, create GitHub Release
   from the tag, upload the offline zip.
5. Full details: `docs/publish-release.md`, `docs/release-checklist.md`,
   `docs/install-on-new-pc.md`.

## 7. Tests

Six pytest files under `tests/`:

- `test_board_send_mode.py` — board config / send-mode readback
- `test_decode.py` — TCP_SENT packet decoding
- `test_acquire_single_monitoring.py` — single-board acquire + monitoring
- `test_multi_wave_watch.py` — multi-board capture + wave watch
- `test_wave_monitor.py` — wave monitor viewer behavior
- `test_release_portability.py` — offline release packaging portability

## 8. Known Limitations and Follow-ups

- `daq monitor wave` live monitoring supports only `send_mode = 1`.
- `tcp-mode2-*` naming is legacy; rename toward `tcp-sent` / `packet-mode` is
  planned.
- Acquisition still runs through legacy-script adapters; native protocol and
  parser modules are not yet implemented.
- Multi-board acquisition is implemented as a wrapper around the vendored
  `multi_board_acquire.py`, not natively.
- Not implemented: additional monitor commands, `daq wave`, `daq shell`.
- The `__version__` mismatch between `pyproject.toml` and
  `src/daq_cli/__init__.py` was fixed at this archive point.
- `dist/` contains offline packages for v0.1.0 .. v0.1.3; v0.1.4 was not
  built (archive only).
