# Firmware Compatibility Notes

## 1. Purpose

This document summarizes the current firmware-facing facts that `daq-cli`
should treat as stable, and records the main gaps between the latest firmware
behavior and the current CLI implementation.

Source references used for this summary live in the external hardware project:

- `FDU-ADC-250M-16ch/docs/rbcp_register_map.md`
- `FDU-ADC-250M-16ch/docs/tcp_sent_selected_channel_packet.md`
- `FDU-ADC-250M-16ch/docs/changes/2026-06-02/2026-06-02_tcp-sent-four-mode-packets.md`
- `FDU-ADC-250M-16ch/docs/changes/2026-05-21/2026-05-21_multi-board-acquisition-script.md`

## 2. Firmware Facts To Keep In This Repo

### 2.1 Stable RBCP register areas

The current firmware exposes a software-usable RBCP register window at
`0x00..0x7F`, with most stable DAQ-facing configuration fields in `0x00..0x44`.

Key stable fields for `daq-cli` are:

- `0x06`
  - `bit1`: `Time_clean`
  - `bit2`: `EXT_Trigger_en`
- `0x10`
  - `Trigger_model`
- `0x11..0x18`
  - 4 trigger thresholds, big-endian per 16-bit threshold
- `0x19`
  - `Trigger_position`
- `0x1A`
  - `ADC_CONFIG`
- `0x1B..0x1D`
  - `SEND_START_DELAY[23:0]`, big-endian
- `0x20..0x3F`
  - 16 hit thresholds, big-endian per channel
- `0x40..0x41`
  - 16 hit polarities
- `0x42`
  - `Send_mode`
- `0x43`
  - `Integ_pre_samples`
- `0x44`
  - `Integ_post_samples`

Important implementation rule:

- `0x06` should be handled with read-modify-write, not blind whole-byte writes.

### 2.2 `Send_mode` semantics changed

The latest firmware defines four explicit `TCP_SENT` packet modes:

```text
0 = hit-selected waveform
1 = full-channel waveform
2 = hit-selected feature
3 = hit-selected feature + waveform
```

Compatibility note:

- `send_mode = 2` no longer means `feature + waveform`.
- `send_mode = 3` is now `feature + waveform`.

### 2.3 Packet framing is now mode-dependent

Every packet starts with a fixed header, either 20 bytes (format version 0)
or 28 bytes (format version 1):

```text
byte 0      : 0xFF
byte 1      : 0xFE
byte 2      : 0x01
byte 3      : send_mode
byte 4..7   : event_count[31:0]
byte 8..15  : timestamp[63:0]
byte 16..17 : hit_mask[15:0]
byte 18     : feature record length
byte 19     : frame format version（0 = 20-byte header, >=1 = 28-byte header）
byte 20..23 : crossing_fine[31:0]（>=1 only；200M 域过阈时刻，5ns 粒度）
byte 24..27 : accept_fine[31:0]  （>=1 only；200M 域事件接受时刻）
```

Receiver-side implication:

- **header length is decided by byte 19**, not by send_mode; all daq-cli
  parsers (native decode, live capture, wave monitor, vendored multi-board
  script) discriminate on byte 19 so old-firmware frames still parse
- payload length must be derived from `send_mode`
- `hit_mask` alone is not enough to infer frame length
- `mode 1` still carries a real `hit_mask`, even though payload is full-waveform
- frame length formulas start from 28 when version >= 1:
  mode 0 = `28 + hit*256`, mode 1 = `28 + 4096`, mode 2 = `28 + hit*10`,
  mode 3 = `28 + hit*266`

### 2.4 Feature payload exists as a first-class format

For `send_mode = 2` and `3`, each selected channel may emit a 10-byte feature
record:

```text
byte 0      : channel id
byte 1..2   : baseline[15:0]
byte 3..4   : peak_amp[15:0]
byte 5      : peak_pos[7:0]
byte 6..9   : integral[31:0], signed int32
```

This matters because future native parsing in `daq-cli` should not assume that
all packets contain waveform payload.

### 2.5 Fine crossing timestamps (format version >= 1)

`crossing_fine` / `accept_fine` are latched on the board-local 200M counter
(5ns granularity); their difference `Δfine = accept_fine - crossing_fine`
(wrap-safe unsigned subtraction) is the "crossing -> accept" on-board delay
and cancels the 20M TCM-link quantization when aligning crossing positions.

Precision facts:

- single-board crossing moments: 5ns
- crossing-position alignment across events: ~6ns (measured)
- cross-board crossing alignment: still 50ns (20M timestamp) — the 200M
  phases differ per board; level-2 phase locking is not implemented
- do NOT compute absolute crossing time as `timestamp - Δfine`; cross-board
  absolute time always uses the 20M `timestamp`

Reference: `FDU-ADC-250M-16ch/docs/delta_fine_timestamp.md`.

### 2.6 TCM trigger-link registers (ADC board 0x45..0x6C)

Firmware `b02db46`+ exposes the TCM trigger link: real-time per-channel
threshold crossing -> M21 pulse to the TCM board; TCM returns a wide MOSI
pulse that acts as the acquisition trigger source (`Trigger_model = 9`).

| Address | Content | Reset | Notes |
| --- | --- | --- | --- |
| `0x45..0x64` | 16 crossing thresholds `thr[15:0]` | 0 | ch0@0x45/46 ... ch15@0x63/64, big-endian, 12-bit effective |
| `0x65..0x66` | channel mask `mask[15:0]` | 0 | bitN = chN participates |
| `0x67..0x68` | polarity `polarity[15:0]` | 0 | 0 = pos (adc>thr), 1 = neg (adc<thr) |
| `0x69..0x6A` | debounce interval | 200 | unit 5ns @200M (default 1us) |
| `0x6B` | enable | 0 | bit0 = pulse output enable |
| `0x6C` | M21 pulse width | 20 | unit 5ns (default 100ns); 0 = no pulse |

Rules:

- fully decoupled from `Hit_threshold` (0x20..0x3F, baseline-relative)
- measured full-chain delay D ≈ 397ns; keep `Trigger_position` <= 10 when
  using the TCM link so the crossing point stays inside the window
- `Trigger_model = 9` is the TCM-trigger source; values 0..8 unchanged
- TCM board side (FDU-TCM v2) exposes its own trigger-link registers at
  `0x20..0x25` (TRG_CTRL / TRG_IN_MASK / TRG_PULSE_WIDTH / TRG_DEBOUNCE /
  TRG_STATUS / TRG_CHAN) — different address space, not conflicting; driven
  by `daq tcm show/config` since v0.2.0. Note the units: TCM-side width and
  debounce are in 20M cycles (50ns), unlike the ADC-side 5ns units.

### 2.7 Multi-board acquisition already has a legacy workflow

The external hardware project contains `script/multi_board_acquire.py` and a
matching example config. That workflow already supports:

- one TCP receiver thread per board
- TCM alignment before acquisition
- aggregation by `timestamp` or `event_count`
- `timestamp_match_window_ticks`
- complete and partial event outputs
- monitor snapshots written to `monitor.jsonl`

`daq-cli` vendors a copy under `_vendor/fdu_legacy/` and wraps it from
`legacy_multi_capture_runner.py`. The vendored FrameParser is version-aware
(byte 19) while the upstream script parses 28-byte headers unconditionally;
keep that divergence marked with comments when re-syncing.

## 3. What In `daq-cli` Is Now Out Of Date

### 3.1 Terminology around "mode-2"

Current code and docs still use names such as:

- `tcp-mode2-show`
- `--tcp-mode2/--no-tcp-mode2`
- `capture_tcp_sent_mode2.py`
- "Capture raw mode-2 packets"

This is no longer a good conceptual model for the firmware, because the board
now exposes a four-mode `TCP_SENT` protocol, not a single special "mode-2"
capture path.

Recommended direction:

- keep current command names temporarily for compatibility
- document clearly that these commands currently operate on the
  `0x42..0x44` `TCP_SENT` registers
- expose explicit write commands with `send_mode` terminology where appropriate
- plan a later rename toward `tcp-sent` or `packet-mode`

### 3.2 Acquisition docs currently overstate the packet assumption

`daq acquire single` currently wraps `capture_tcp_sent_mode2.py`, but the repo
docs describe the current capture path as if "mode-2" were the protocol model.

That needs correction because:

- the firmware packet contract is now four-mode
- since v0.2.0 the native parser branches on `send_mode` and on the frame
  format version (byte 19), and validation rejects incompatible `send_mode`
  values before capture

### 3.3 Multi-board acquisition runs through the vendored legacy script

`daq acquire multi` wraps the vendored `multi_board_acquire.py` (not a native
implementation). The vendored FrameParser supports both 20-byte and 28-byte
frames (byte 19 discrimination); the upstream script parses 28-byte headers
unconditionally. Keep this divergence documented when re-syncing.

### 3.4 No local firmware compatibility reference existed

Before this document, the repo relied on external project docs for:

- stable RBCP addresses
- packet header shape
- `send_mode` semantics
- multi-board acquisition behavior

That made it too easy for the CLI repo to drift from the firmware contract.
This document is now the local reference; the external docs
(`delta_fine_timestamp.md`, `tcp_sent_selected_channel_packet.md`,
`rbcp_register_map.md`) are the firmware-side authority for details.

## 4. Recommended Code Changes

Status as of v0.2.0:

- ~~Add `daq acquire multi <group>` as a wrapper~~ — done, plus configurable
  multi-board profile defaults (aggregation key, match window, timeouts,
  outputs).
- ~~Remove the `send_mode = 2` means `feature + waveform` assumption; base
  packet length on `send_mode`; support all four frame types~~ — done; native
  parser branches on `send_mode` and byte-19 format version (20B/28B).
- ~~Add native data models for packet headers, feature records, waveform
  frames~~ — done (`tcp_sent_decode.py` models, fine fields since v0.2.0).

Still open:

- Rename `tcp-mode2-*` commands toward `tcp-sent` / `packet-mode` terminology
  (kept for compatibility; see 3.1).
- Add a board-level readback for firmware version registers:
  `0x00..0x03` `SYN_DATE`, `0x04` `FPGA_VER`.
- Level-2 phase locking (200M locked to 20M) for cross-board 5ns alignment —
  firmware-side open item, not implemented.

## 5. Recommended Documentation Changes

The following information is worth keeping inside this repo's `docs/` directory:

- the stable RBCP register subset that `daq-cli` depends on
- the current four-mode `TCP_SENT` contract
- the difference between legacy script names and current firmware semantics
- the fact that multi-board acquisition already exists as a legacy integration
  target

This avoids forcing future CLI work to rediscover firmware behavior by scanning
the external hardware repository again.
