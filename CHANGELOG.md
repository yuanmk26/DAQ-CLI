# Changelog

All notable changes to `daq-cli` are documented in this file.

Each version is tagged as `v<version>` on the `main` branch. The detailed
snapshot of the v0.1.x line (commands, firmware contract, architecture,
release flow) is archived in `docs/version-snapshot-v0.1.4.md`.

## [v0.3.0] - 2026-08-10

Desktop GUI console (tkinter, zero new dependencies) wrapping the full CLI
surface.

### Added

- `daq-gui` dedicated entry point (selects the TkAgg matplotlib backend
  before any pyplot import) and a `daq gui` subcommand.
- Main window: profile bar with file dialog, four-tab notebook, shared
  capped log panel, clean shutdown of background work.
- 板卡 tab: info / sysmon / trigger-show / tcp-mode2-show / config-show /
  tcm-link-show, board config form (steps, trigger params, thresholds,
  send-mode), TCM link config form, reg-read hex dump.
- 采集 tab: single capture with live progress bar (progress callback
  marshalled through a queue), multi capture with busy state and result
  summary (watch disabled; waveforms belong to the monitor tab).
- 监视 tab: live / demo / replay waveform monitoring embedded via
  `FigureCanvasTkAgg`, reusing `WaveMonitorFigure` and the pure loop state
  machine with RUN/STOP/SINGLE buttons; stopping restores the original
  `send_mode` through the existing session context.
- TCM tab: show config + status (sticky / pending / wide pulse / last
  trigger channels), config with readback verification and clear-sticky.
- GUI helpers (background task marshalling, result formatting) are
  tkinter-free pure functions with unit tests (19 new tests).

## [v0.2.0] - 2026-08-10

Frame format upgrade (28-byte header + fine timestamps) and TCM trigger-link
support. Requires ADC firmware `64c2885`+ (fine stamps) / `b02db46`+ (TCM
trigger link) for the new features; old 20-byte frames remain decodable.

### Added

- 28-byte TCP_SENT frame header support (format version in byte 19):
  `crossing_fine` / `accept_fine` fields and wrap-safe `delta_fine` on
  decoded events, JSON, and TXT outputs.
- Version-aware parsing everywhere (native decoder, live single capture,
  wave monitor, vendored multi-board script, aggregated files), so old and
  new firmware frames coexist during transitions.
- Aggregated format v2: board chunks carry fine fields; v1 files still read.
- `daq board tcm-link-show <device>` — read TCM trigger-link configuration
  (0x45..0x6C) without writing.
- `daq board tcm-link-config <device> --mask ... --thr ...` — write the TCM
  trigger-link configuration with readback verification (single-value
  broadcast or 16 threshold values).
- `Trigger_model = 9` support (TCM-trigger source) in `board config`.
- `daq tcm show <name>` / `daq tcm config <name>` — TCM board trigger-link
  configuration and status (0x20..0x25): enable, 8-bit mask, pulse width /
  debounce (20M cycles), sticky/pending/wide-pulse status, last trigger
  channels. Write path verifies by readback.
- TCM profile entries now load as typed `TcmConfig` (name/ip/rbcp_port).
- Vendored `FPGA_CTRL.py` synced from upstream (TCM config functions,
  trigger_model 0..9).

### Changed

- Vendored `multi_board_acquire.py` synced from upstream; FrameParser keeps a
  documented byte-19 version discrimination divergence.
- Text event outputs include `format_version` / `crossing_fine` /
  `accept_fine` / `delta_fine`.

## [v0.1.4] - 2026-08-10 (archived)

Archive point before the next development cycle. Contains everything from
`v0.1.3` plus the following unreleased commits.

### Added

- Configurable capture text outputs (`defaults.*.outputs.text`) with segmented
  TXT event files (`max_events_per_file`, `waveform_layout`).
- Indexed run directories via `allocate_next_run_dir` (`<prefix>_<NNNNN>`).

### Fixed

- Wave monitor viewer bug.
- Multi-board acquire viewer bug.
- Multi-board viewer bug.

## [v0.1.3] - 2026-06-15

### Fixed

- Bug in the multi-board acquire viewer.

## [v0.1.2] - 2026-06-15

### Changed

- Wave monitor viewer y-range handling.

## [v0.1.1] - 2026-06-14

### Added

- Vendored legacy scripts under `src/daq_cli/_vendor/fdu_legacy/` so the
  package no longer depends on the external hardware project at runtime.
- Offline Windows release packaging (`scripts/build_release.ps1`,
  `scripts/install_offline.ps1`).

## [v0.1.0] - 2026-06-09

### Added

- Project skeleton with layered architecture (cli / application / domain /
  infrastructure / presentation).
- Profile-driven device loading (`profiles/example.yaml`).
- `daq board` read-only config inspection commands:
  `trigger-show`, `tcp-mode2-show`, `config-show`, `reg-read`.
- `daq acquire multi <group>` wrapping the legacy `multi_board_acquire.py`
  workflow (TCM alignment, aggregation, decode, watch).
- `daq monitor wave <device>` waveform monitoring preview (live / demo /
  replay) with keyboard-driven `RUN` / `STOP` / `SINGLE`.
- `daq acquire single` decode, watch, and profile defaults.
- Streamed decode during multi-board capture.
- Release packaging guide (`docs/publish-release.md`).
