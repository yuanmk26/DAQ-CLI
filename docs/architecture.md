# daq-cli Architecture

## 1. Goal

`daq-cli` is a Python-based data acquisition command-line application for DAQ board configuration, data capture, monitoring, and waveform viewing.

The project should provide:

- A unified CLI entry for hardware operations
- Reusable services instead of one-off scripts
- Support for both terminal workflows and optional waveform windows
- A clean migration path from the existing legacy scripts under `FDU-ADC-250M-16ch/script`

The first phase should prioritize usability and stability over completeness.

## 2. Design Principles

- CLI-first: all core operations must be usable from the command line
- Layered design: command parsing, business workflow, hardware access, and presentation should be separated
- Reuse before rewrite: legacy scripts should be adapted first, then gradually absorbed
- Config-driven: device IPs, ports, groups, and defaults must live in profile files
- Optional visualization: waveform viewing is an extra presentation mode, not the core of the system

## 3. High-Level Layers

The repository should be organized into four main layers.

### CLI Layer

Responsible for:

- Parsing commands and arguments
- Loading the selected profile
- Calling application services
- Returning structured results to the presentation layer

This layer should not directly access registers or sockets.

### Application Layer

Responsible for:

- Coordinating workflows such as board configuration, acquisition, and monitoring
- Translating user intent into a sequence of device operations
- Returning structured results for console output or waveform display

This is the main orchestration layer of the system.

### Infrastructure Layer

Responsible for:

- RBCP communication
- TCP stream connection and packet reading
- Register-level board access
- TCM control
- Legacy script adaptation
- Packet parsing

This layer talks to hardware, files, and external project resources.

### Presentation Layer

Responsible for:

- Console tables, status lines, and human-readable summaries
- Optional waveform display window

This layer should never contain acquisition or hardware logic.

## 4. Repository Layout

```text
daq-cli/
  docs/
    architecture.md
    cli-design.md
  profiles/
    example.yaml
    lab.yaml
  src/
    daq_cli/
      __init__.py
      main.py
      cli/
        __init__.py
        app.py
        profile.py
        board.py
        group.py
        acquire.py
        monitor.py
        wave.py
      application/
        __init__.py
        config_models.py
        models.py
        profile_service.py
        board_service.py
        acquire_service.py
        telemetry_service.py
      domain/
        __init__.py
        device.py
        group.py
      infrastructure/
        __init__.py
        config_loader.py
        adapters/
          __init__.py
          legacy_board_adapter.py
          legacy_capture_runner.py
          legacy_runtime.py
      presentation/
        __init__.py
        console/
          __init__.py
          printers.py
  tests/
```

Current note:

- The current repository implements the modules shown above.
- Some directories from the original architecture sketch, such as `transport/`, `hardware/`, `parsers/`, and `wave_window/`, are still planned but not created yet.

## 5. Core Concepts

### Device

Represents one DAQ board.

Expected fields:

- Device name
- IP address
- RBCP port
- TCP port
- Board ID
- Optional tags or role

### Group

Represents a named set of devices used together for coordinated operations.

Expected fields:

- Group name
- Device list
- Optional TCM reference

### Profile

Represents the configuration source for a lab, setup, or experiment environment.

Expected fields:

- Devices
- Groups
- TCM endpoints
- Default acquisition parameters
- Legacy project root path

### Waveform Frame

Represents one decoded waveform unit ready for display or saving.

Expected fields:

- Device identity
- Event number
- Timestamp
- Hit mask
- Selected channel waveforms
- Raw metadata

## 6. Legacy Integration Strategy

The existing scripts in `FDU-ADC-250M-16ch/script` should be treated as a source of stable hardware knowledge.

The initial implementation should:

- Reuse existing packet structure knowledge
- Reuse working configuration logic where practical
- Avoid copying everything into the new project immediately

The migration path should be:

1. Wrap stable legacy logic behind adapter modules
2. Move shared protocol and parser logic into native `daq-cli` infrastructure modules
3. Gradually replace legacy script entrypoints with native application services

This reduces early implementation risk while preserving a clean long-term architecture.

## 7. Waveform Viewing Strategy

Waveform display should not force the project into a full GUI architecture.

Recommended model:

- Core control remains CLI-based
- `daq wave watch ...` may open a dedicated plotting window
- The plotting window only consumes decoded waveform frames

This gives a practical hybrid model:

- CLI for control, automation, and scripting
- Windowed viewer for waveform inspection

The waveform viewer should be isolated behind the presentation layer so it can later be replaced by:

- A terminal renderer
- A desktop window
- A local web viewer

## 8. First-Phase Scope

The first implementation phase should focus on a minimal but coherent vertical slice.

Planned commands:

- `daq board info <device>`
- `daq board sysmon <device>`
- `daq board config <device>`
- `daq acquire single <device>`
- `daq acquire multi <group>`
- `daq monitor board <device> --watch`
- `daq wave watch <device> --channels ...`

These commands are enough to validate the architecture and cover the core DAQ workflow.

## 9. Current Implementation Status

Implemented end-to-end:

- `daq board info <device>`
  - Loads the selected profile
  - Resolves the logical device
  - Prints device metadata and legacy project path
- `daq board sysmon <device>`
  - Uses the legacy `lib/sysmon.py` flow through an adapter
  - Prints temperature, `vccint`, `vccaux`, and `vccbram`
- `daq board config <device>`
  - Uses the legacy `start_16CH_two_board.py` flow through an adapter
  - Supports step toggles:
    - `--adc/--no-adc`
    - `--clock/--no-clock`
    - `--trigger/--no-trigger`
    - `--tcp-mode2/--no-tcp-mode2`
  - Supports trigger-related options:
    - `--trigger-mode`
    - `--trigger-position`
    - `--threshold-1` to `--threshold-4`
    - `--timestamp-clean/--no-timestamp-clean`
    - `--ext-trigger/--no-ext-trigger`
    - `--send-start-delay-us`
- `daq acquire single <device>`
  - Uses the legacy `capture_tcp_sent_mode2.py` flow through an adapter
  - Supports event count, timeout, and output directory selection

Implemented but still minimal:

- `daq profile show`
- `daq profile validate`

Planned but not implemented:

- Multi-board acquisition
- Monitor commands
- Waveform commands
- Interactive shell mode
- Native protocol, parser, and hardware modules

## 10. Implementation Priorities

Recommended order:

1. Project skeleton
2. Profile loading
3. Device and group models
4. RBCP client wrapper
5. Board service
6. TCP stream reader and packet parser
7. Acquisition service
8. Console presentation
9. Waveform viewer integration

This sequence keeps the critical path short and testable.

## 11. Near-Term Deliverables

Recommended next coding steps:

- Extend TCP mode-2 configuration so integration window and hit settings are directly configurable
- Add monitor commands on top of the existing telemetry adapter
- Start separating protocol and parser logic from legacy-script wrappers
- Add waveform viewing on top of the single-board acquisition path
