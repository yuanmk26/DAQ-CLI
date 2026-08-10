# Changelog

All notable changes to `daq-cli` are documented in this file.

Each version is tagged as `v<version>` on the `main` branch. The detailed
snapshot of the v0.1.x line (commands, firmware contract, architecture,
release flow) is archived in `docs/version-snapshot-v0.1.4.md`.

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
