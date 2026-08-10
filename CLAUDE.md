# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`daq-cli` is a Python CLI (typer + rich) for DAQ boards (FDU-ADC-250M-16ch
hardware): board configuration, telemetry, single/multi-board capture,
TCP_SENT packet decoding, and waveform monitoring. Current version line:
v0.2.0 (see `CHANGELOG.md`).

Hardware access is NOT native: it runs through vendored legacy scripts
(`src/daq_cli/_vendor/fdu_legacy/`) wrapped by adapters in
`src/daq_cli/infrastructure/adapters/`. The project deliberately follows
"reuse before rewrite" — keep this arrangement until a native hardware
module is deliberately built. The vendored code is the stable source of
hardware knowledge; the external project `FDU-ADC-250M-16ch` is only
referenced as `legacy.project_root` in machine-local profiles.

## Commands

Development environment is Windows (Git Bash / PowerShell):

- Install editable: `pip install -e .` → provides the `daq` entry point
- Run without install (bash): `PYTHONPATH=src python -m daq_cli.main --help`
- Run all tests: `python -m pytest` (see `pytest.ini`; `out/`, `dist/`, `tmp*` are excluded)
- Run one test file: `python -m pytest tests/test_decode.py`
- Run one test: `python -m pytest tests/test_decode.py -k "pattern"`
- Build the offline release (PowerShell, needs network for dependency wheels): `.\scripts\build_release.ps1`
  → produces `dist\daq_cli-<version>-offline-win-amd64.zip`

CLI surface (`daq --help`): `profile` (show/validate/init),
`board` (info/sysmon/config/trigger-show/tcp-mode2-show/tcm-link-show/
tcm-link-config/config-show/reg-read), `tcm` (show/config),
`acquire` (single/multi), `monitor` (wave/multi-demo), `decode`, `group`,
`gui`. A separate `daq-gui` entry point launches the desktop GUI console
(tkinter).

## GUI console

`src/daq_cli/presentation/gui/` is a thin shell over the application
services; application/infrastructure layers stay GUI-free.

- `app.py` — main window (profile bar, 4-tab notebook, capped log panel)
- `threads.py` — background task marshalling, **tkinter-free** (inject
  `schedule` = `root.after`); unit-tested
- `formatting.py` — pure result→text and form→service-parameter builders;
  unit-tested
- tabs: `boards_tab` / `acquire_tab` / `monitor_tab` / `tcm_tab`
- **backend ordering constraint**: `daq-gui` (gui_main.py) calls
  `matplotlib.use("TkAgg")` before any other import, because the CLI import
  chain (cli/monitor → wave_monitor_viewer) already loads pyplot and locks
  the backend. Never import pyplot-using modules before the backend is set.
- the monitor tab reuses `WaveMonitorFigure` + `_advance_loop_state` /
  `_drain_latest_frame` driven by `root.after` — never call the blocking
  `run_*_viewer` entry points from the GUI
- all service calls run in daemon threads; results marshal through queues
  back to the GUI thread

## Architecture

Four layers under `src/daq_cli/`:

- `cli/` — typer command groups. Thin: parse args, load profile, call a
  service. No hardware logic.
- `application/` — services orchestrate workflows: `board_service`,
  `acquire_service`, `telemetry_service`, `monitor_service`,
  `decode_service`, `multi_decode_service`, `profile_service`.
  Business logic lives here.
- `infrastructure/` — everything that touches hardware or files:
  - `config_loader.py` — loads profiles (devices/tcm/groups/defaults/legacy)
  - `adapters/` — wrap the vendored legacy scripts (board config, single
    capture, multi capture, runtime)
  - native protocol/decode: `tcp_sent_protocol.py`, `tcp_sent_decode.py`,
    `multi_board_decode.py`
  - `text_event_writer.py` (segmented TXT outputs), `run_name_allocator.py`
    (indexed run dirs), `wave_monitor.py`
- `presentation/` — `console/printers.py` (rich output) and
  `wave_monitor_viewer.py` (matplotlib viewer with RUN/STOP/SINGLE keys).
  No acquisition or hardware logic.
- `domain/` — device/group models; `application/models.py` +
  `config_models.py` define decoded events and profile configuration.

Key workflow facts:

- Profile-driven: `--profile profiles/example.yaml`. Devices are
  IP/RBCP-port keyed; `defaults.acquire_single` / `defaults.acquire_multi`
  hold capture params, including independent `outputs.{raw,json,text,log}`
  switches and directories (text output supports
  `waveform_layout: channel_blocks | point_rows` and
  `max_events_per_file` segmentation).
- Multi-board capture wraps the vendored `multi_board_acquire.py`: TCM
  alignment, aggregation by `timestamp` or `event_count`, streamed decode,
  wave watch, monitor.jsonl snapshots.
- `monitoring_samples/` holds demo/replay data for the viewer
  (`daq monitor wave demo`, `daq monitor wave --replay ...`).
- Tests are hardware-free: they use the sample dumps and temp dirs.

## Firmware contract (stable facts — read before protocol work)

Full reference: `docs/firmware-compatibility.md`. Key rules:

- RBCP register window `0x00..0x44`. `0x06` (Time_clean / EXT_Trigger_en)
  must be handled read-modify-write, never blind whole-byte writes.
  Trigger fields `0x10..0x1D`; 16 hit thresholds `0x20..0x3F`;
  `0x42` Send_mode, `0x43/0x44` integration samples.
- `Send_mode` has four TCP_SENT packet modes: 0 = hit-selected waveform,
  1 = full-channel waveform, 2 = hit-selected feature,
  3 = feature + waveform. **send_mode = 2 is NOT feature+waveform**
  (semantics changed with the firmware).
- Packet header: 20 bytes (format version 0) or 28 bytes (version 1, byte 19
  >= 1) — magic `FF FE 01`, send_mode, event_count, timestamp, hit_mask,
  feature record length, then (v1) crossing_fine/accept_fine. **Header
  length is decided by byte 19; all parsers discriminate on it** so old
  firmware frames still work. Payload length derives from `send_mode`, not
  `hit_mask`. Length formulas (v1): mode 0 = 28+hit*256, mode 1 = 28+4096,
  mode 2 = 28+hit*10, mode 3 = 28+hit*266.
- `crossing_fine`/`accept_fine` are board-local 200M counters (5ns);
  `Δfine = (accept - crossing) & 0xFFFFFFFF` cancels TCM-link quantization
  for single-board crossing alignment. Never compare fine values across
  boards (phases differ); cross-board absolute time uses the 20M timestamp.
- Feature record (modes 2/3), 10 bytes per selected channel: channel id,
  baseline[15:0], peak_amp[15:0], peak_pos[7:0], integral[31:0] (signed).
- TCM trigger link, ADC side (board `0x45..0x6C`): 16 crossing thresholds,
  mask, polarity, debounce (5ns units), enable, M21 pulse width —
  `daq board tcm-link-show/config`. `Trigger_model = 9` is the TCM-trigger
  source; keep `Trigger_position` 0..10 (link delay D ≈ 397ns).
- TCM trigger link, TCM board side (FDU-TCM v2 `0x20..0x25`): TRG_CTRL
  (enable/clear-sticky), 8-bit TRG_IN_MASK, pulse width + debounce in 20M
  cycles (50ns units, NOT 5ns like the ADC side), TRG_STATUS, TRG_CHAN —
  `daq tcm show/config`. The profile `tcm:` section holds ip/rbcp_port
  (`domain/tcm.py` TcmConfig).
- `tcp-mode2-*` command names are historical labels for the TCP_SENT
  registers — keep them for compatibility; plan a rename toward
  `tcp-sent`/`packet-mode`.
- `daq monitor wave` live monitoring currently supports only `send_mode = 1`.

## Versioning and release

- Version source of truth: `pyproject.toml`. Keep
  `src/daq_cli/__init__.py` `__version__` in sync (they have drifted
  before — 0.1.3 vs 0.1.0).
- Release flow: bump version → `python -m pytest` → PowerShell
  `.\scripts\build_release.ps1` → annotated tag `v<version>` matching
  pyproject → push → GitHub Release with the offline zip.
  Details: `docs/publish-release.md`, `docs/release-checklist.md`,
  `docs/install-on-new-pc.md`.
- Commit style: conventional commits, e.g. `feat(acquire): ...`,
  `fix(monitor): ...`, `chore(release): ...`.

## Docs map

- `docs/usage.md` — user guide: commands, profile format, troubleshooting
- `docs/architecture.md` / `docs/cli-design.md` — design intent, layering, command design
- `docs/firmware-compatibility.md` — firmware contract details and gaps
- `docs/version-snapshot-v0.1.4.md` — archived snapshot of the v0.1.x line
- `CHANGELOG.md` — version history
