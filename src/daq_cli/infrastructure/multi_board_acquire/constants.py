"""Constants and small helpers shared by the native multi-board pipeline.

Struct format strings are imported from
:mod:`daq_cli.infrastructure.multi_board_decode` (the reader) rather than
re-declared here, so the writer and the reader can never drift apart.
"""

from __future__ import annotations

from daq_cli.infrastructure.multi_board_decode import (
    AGGREGATE_FORMAT_VERSION_V2,
    BOARD_FLAG_HAS_FEATURE,
    BOARD_FLAG_HAS_FINE,
    BOARD_FLAG_HAS_WAVEFORM,
    BOARD_FLAG_TCP_RECONNECTED_BEFORE_FRAME,
    EVENT_FLAG_COMPLETE,
    EVENT_FLAG_EVENT_COUNT_MISMATCH,
    EVENT_FLAG_PARTIAL,
    EVENT_FLAG_TIMEOUT_FLUSH,
    FILE_HEADER_FMT,
    FILE_MAGIC,
    FORMAT_NAME,
    INDEX_ENTRY_FMT,
    BOARD_HEADER_FMT_V2,
    EVENT_HEADER_FMT,
)
from daq_cli.infrastructure.tcp_sent_protocol import bit_count

# ---------------------------------------------------------------- format

FORMAT_VERSION = AGGREGATE_FORMAT_VERSION_V2

# ------------------------------------------------------------- TCM align

ALIGN_CTRL_ADDR = 0x18
ALIGN_STATUS_ADDR = 0x19
ALIGN_ONLINE_MASK_ADDR = 0x1A
ALIGN_ACK_MASK_ADDR = 0x1B
ALIGN_MISSING_ACK_MASK_ADDR = 0x1C

ALIGN_CTRL_START = 0x01
ALIGN_CTRL_CLEAR = 0x02

STATUS_DONE_STICKY_BIT = 1
STATUS_TIMEOUT_STICKY_BIT = 2

# ------------------------------------------------------------- TCP modes

MODE_HIT_WAVEFORM = 0
MODE_FULL_WAVEFORM = 1
MODE_HIT_FEATURE = 2
MODE_HIT_FEATURE_WAVEFORM = 3

# Modes the wave monitor can display (contains waveform samples).
WAVEFORM_MODES = (MODE_FULL_WAVEFORM, MODE_HIT_FEATURE_WAVEFORM)
# Modes carrying feature records.
FEATURE_MODES = (MODE_HIT_FEATURE, MODE_HIT_FEATURE_WAVEFORM)

# -------------------------------------------------------------- defaults

DEFAULT_ADC_LENGTH = 256
DEFAULT_TCP_TIMEOUT_S = 1.0
DEFAULT_RECONNECT_DELAY_S = 1.0
DEFAULT_EVENT_TIMEOUT_MS = 50
DEFAULT_MONITOR_INTERVAL_S = 1.0
DEFAULT_MONITOR_JSONL_INTERVAL_S = 5.0
DEFAULT_QUEUE_SIZE = 10000
DEFAULT_RECV_BUFFER_BYTES = 8192
DEFAULT_BOARD_WARN_NO_DATA_S = 3.0
DEFAULT_PARTIAL_WARN_RATIO = 0.01
DEFAULT_RECONNECT_WARN_COUNT = 3

DEFAULT_TCM_TIMEOUT_MS = 3000
DEFAULT_TCM_COMMAND_DELAY_S = 0.02
DEFAULT_TCM_POLL_INTERVAL_S = 0.05
DEFAULT_TCM_POLL_TIMEOUT_S = 2.0

# Number of events written before the writer flushes the data/index files.
WRITER_FLUSH_EVERY = 16

# Channel count hard-coded into the aggregated board chunk by the legacy
# writer. The reader recovers the real per-channel feature record length as
# ``feature_len // hit_count``; see paperwork in docs/firmware-compatibility.md.
BOARD_CHUNK_CHANNEL_COUNT = 16


def status_bit(value: int, bit_index: int) -> int:
    return (value >> bit_index) & 0x1


def mask_from_board_ids(board_ids) -> int:
    mask = 0
    for board_id in board_ids:
        mask |= 1 << board_id
    return mask


def pretty_secs(value: float) -> str:
    value = max(float(value), 0.0)
    if value < 60.0:
        return "%.1fs" % value
    minutes = int(value // 60)
    seconds = int(value % 60)
    return "%dm%02ds" % (minutes, seconds)


__all__ = [
    "ALIGN_ACK_MASK_ADDR",
    "ALIGN_CTRL_ADDR",
    "ALIGN_CTRL_CLEAR",
    "ALIGN_CTRL_START",
    "ALIGN_MISSING_ACK_MASK_ADDR",
    "ALIGN_ONLINE_MASK_ADDR",
    "ALIGN_STATUS_ADDR",
    "BOARD_CHUNK_CHANNEL_COUNT",
    "BOARD_FLAG_HAS_FEATURE",
    "BOARD_FLAG_HAS_FINE",
    "BOARD_FLAG_HAS_WAVEFORM",
    "BOARD_FLAG_TCP_RECONNECTED_BEFORE_FRAME",
    "BOARD_HEADER_FMT_V2",
    "DEFAULT_ADC_LENGTH",
    "DEFAULT_BOARD_WARN_NO_DATA_S",
    "DEFAULT_EVENT_TIMEOUT_MS",
    "DEFAULT_MONITOR_INTERVAL_S",
    "DEFAULT_MONITOR_JSONL_INTERVAL_S",
    "DEFAULT_PARTIAL_WARN_RATIO",
    "DEFAULT_QUEUE_SIZE",
    "DEFAULT_RECV_BUFFER_BYTES",
    "DEFAULT_RECONNECT_DELAY_S",
    "DEFAULT_RECONNECT_WARN_COUNT",
    "DEFAULT_TCM_COMMAND_DELAY_S",
    "DEFAULT_TCM_POLL_INTERVAL_S",
    "DEFAULT_TCM_POLL_TIMEOUT_S",
    "DEFAULT_TCM_TIMEOUT_MS",
    "DEFAULT_TCP_TIMEOUT_S",
    "EVENT_FLAG_COMPLETE",
    "EVENT_FLAG_EVENT_COUNT_MISMATCH",
    "EVENT_FLAG_PARTIAL",
    "EVENT_FLAG_TIMEOUT_FLUSH",
    "EVENT_HEADER_FMT",
    "FEATURE_MODES",
    "FILE_HEADER_FMT",
    "FILE_MAGIC",
    "FORMAT_NAME",
    "FORMAT_VERSION",
    "INDEX_ENTRY_FMT",
    "MODE_FULL_WAVEFORM",
    "MODE_HIT_FEATURE",
    "MODE_HIT_FEATURE_WAVEFORM",
    "MODE_HIT_WAVEFORM",
    "STATUS_DONE_STICKY_BIT",
    "STATUS_TIMEOUT_STICKY_BIT",
    "WAVEFORM_MODES",
    "WRITER_FLUSH_EVERY",
    "bit_count",
    "mask_from_board_ids",
    "pretty_secs",
    "status_bit",
]
