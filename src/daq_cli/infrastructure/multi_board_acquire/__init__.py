"""Native multi-board acquisition.

This package is the native replacement for the vendored
``_vendor/fdu_legacy/multi_board_acquire.py``. It keeps the same on-disk
formats (aggregated ``complete_events.dat`` / ``partial_events.dat`` /
``complete_events.idx`` / ``monitor.jsonl`` / ``run_meta.json``) so existing
decode tooling and previously captured runs keep working.

Thread/queue topology::

    N x BoardReceiver --put--> frame_queue --> EventAggregator --> DataWriter
                 \\-- frame_sink --> watch publisher (optional)

    MonitorThread --> EventLog + monitor.jsonl
"""

from __future__ import annotations

from daq_cli.infrastructure.multi_board_acquire.alignment import (
    AlignSnapshot,
    TcmAlignController,
)
from daq_cli.infrastructure.multi_board_acquire.app import (
    FrameSink,
    MultiBoardAcquisitionApp,
)
from daq_cli.infrastructure.multi_board_acquire.config import (
    MultiBoardAppConfig,
    MultiBoardConfig,
)
from daq_cli.infrastructure.multi_board_acquire.frames import (
    MultiBoardFrame,
    frame_from_fields,
)

__all__ = [
    "AlignSnapshot",
    "FrameSink",
    "MultiBoardAcquisitionApp",
    "MultiBoardAppConfig",
    "MultiBoardConfig",
    "MultiBoardFrame",
    "TcmAlignController",
    "frame_from_fields",
]
