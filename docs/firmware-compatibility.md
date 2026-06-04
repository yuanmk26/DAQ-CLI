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

Every packet now starts with a fixed 20-byte header:

```text
byte 0      : 0xFF
byte 1      : 0xFE
byte 2      : 0x01
byte 3      : send_mode
byte 4..7   : event_count[31:0]
byte 8..15  : timestamp[63:0]
byte 16..17 : hit_mask[15:0]
byte 18     : feature record length
byte 19     : reserved
```

Receiver-side implication:

- payload length must be derived from `send_mode`
- `hit_mask` alone is not enough to infer frame length
- `mode 1` still carries a real `hit_mask`, even though payload is full-waveform

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

### 2.5 Multi-board acquisition already has a legacy workflow

The external hardware project now contains `script/multi_board_acquire.py` and a
matching example config. That workflow already supports:

- one TCP receiver thread per board
- TCM alignment before acquisition
- aggregation by `timestamp` or `event_count`
- `timestamp_match_window_ticks`
- complete and partial event outputs
- monitor snapshots written to `monitor.jsonl`

This means multi-board acquisition is no longer only a design goal; there is now
an existing legacy entrypoint that `daq-cli` can wrap.

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
- plan a later rename toward `tcp-sent` or `packet-mode`

### 3.2 Acquisition docs currently overstate the packet assumption

`daq acquire single` currently wraps `capture_tcp_sent_mode2.py`, but the repo
docs describe the current capture path as if "mode-2" were the protocol model.

That needs correction because:

- the firmware packet contract is now four-mode
- future native parsers must branch on `send_mode`
- future validation should detect incompatible `send_mode` values before capture

### 3.3 Multi-board acquisition status is behind reality

The current repo still documents multi-board acquisition as "not implemented",
which is true for this CLI surface, but incomplete from an integration point of
view because the legacy project already provides a usable script.

The docs should distinguish:

- not implemented natively in `daq-cli`
- already available as a legacy workflow that can be wrapped next

### 3.4 No local firmware compatibility reference existed

Before this document, the repo relied on external project docs for:

- stable RBCP addresses
- packet header shape
- `send_mode` semantics
- multi-board acquisition behavior

That made it too easy for the CLI repo to drift from the firmware contract.

## 4. Recommended Code Changes

These are the highest-value follow-up code changes.

### 4.1 Short term

- Add a firmware-aware note to single-board acquisition output and docs that the
  current adapter is legacy-script based.
- Add a dedicated doc-backed explanation that current `tcp-mode2-*` commands are
  historical names for `TCP_SENT` configuration readback.
- Add a board-level readback for firmware version registers:
  - `0x00..0x03` `SYN_DATE`
  - `0x04` `FPGA_VER`

### 4.2 Medium term

- Add `daq acquire multi <group>` as a wrapper around
  `script/multi_board_acquire.py`.
- Extend profile/default models so multi-board acquisition can express:
  - aggregation key
  - timestamp match window
  - TCM startup policy
  - reconnect and timeout settings
- Add native data models for packet headers, feature records, and waveform
  frames.

### 4.3 Before native parser work

- Remove any future assumption that `send_mode = 2` means
  `feature + waveform`.
- Base packet-length computation on `send_mode`.
- Support all four frame types from the start.

## 5. Recommended Documentation Changes

The following information is worth keeping inside this repo's `docs/` directory:

- the stable RBCP register subset that `daq-cli` depends on
- the current four-mode `TCP_SENT` contract
- the difference between legacy script names and current firmware semantics
- the fact that multi-board acquisition already exists as a legacy integration
  target

This avoids forcing future CLI work to rediscover firmware behavior by scanning
the external hardware repository again.
