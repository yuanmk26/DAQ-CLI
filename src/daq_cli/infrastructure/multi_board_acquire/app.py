"""Native multi-board acquisition orchestrator.

Drop-in replacement for the vendored ``AcquisitionApp``: same run directory
layout, same ``run_meta.json`` schema and status machine, same thread start and
stop ordering.
"""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path

from daq_cli.infrastructure.multi_board_acquire.alignment import (
    AlignSnapshot,
    RbcpFactory,
    TcmAlignController,
)
from daq_cli.infrastructure.multi_board_acquire.clock import MultiBoardClock, SYSTEM_CLOCK
from daq_cli.infrastructure.multi_board_acquire.config import MultiBoardAppConfig
from daq_cli.infrastructure.multi_board_acquire.constants import FORMAT_NAME, FORMAT_VERSION
from daq_cli.infrastructure.multi_board_acquire.aggregator import MultiBoardEventAggregator
from daq_cli.infrastructure.multi_board_acquire.frames import MultiBoardFrame
from daq_cli.infrastructure.multi_board_acquire.monitor import MultiBoardMonitorThread
from daq_cli.infrastructure.multi_board_acquire.receiver import (
    FrameSink,
    MultiBoardBoardReceiver,
    SocketFactory,
)
from daq_cli.infrastructure.multi_board_acquire.state import (
    EventLog,
    MultiBoardSharedState,
)
from daq_cli.infrastructure.multi_board_acquire.writer import MultiBoardDataWriter
from daq_cli.infrastructure.rbcp import RbcpClient


class MultiBoardAcquisitionApp:
    """Align the boards through the TCM, then capture and aggregate events."""

    def __init__(
        self,
        config: MultiBoardAppConfig,
        config_path: str | Path,
        *,
        clock: MultiBoardClock = SYSTEM_CLOCK,
        frame_sink: FrameSink | None = None,
        rbcp_factory: RbcpFactory = RbcpClient,
        socket_factory: SocketFactory | None = None,
    ) -> None:
        self.config = config
        self.config_path = str(config_path)
        self._clock = clock
        self.stop_event = threading.Event()
        self.run_dir = self._make_run_dir()
        self.logger = EventLog(Path(self.run_dir) / "log.txt", clock=clock)
        self.writer = MultiBoardDataWriter(
            config, self.run_dir, self.logger, clock=clock
        )
        self.state = MultiBoardSharedState(config.boards, clock=clock)
        self.meta_start_time = clock.iso_now()
        self.align_snapshot: AlignSnapshot | None = None
        self.aligned = False
        self._started = False
        self._stopped = False

        self.frame_queue: "queue.Queue[MultiBoardFrame]" = queue.Queue(
            maxsize=config.frame_queue_size
        )
        self.tcm = TcmAlignController(
            config, self.logger, clock=clock, rbcp_factory=rbcp_factory
        )
        self.receivers = [
            MultiBoardBoardReceiver(
                board,
                config,
                self.frame_queue,
                self.state,
                self.logger,
                self.stop_event,
                clock=clock,
                frame_sink=frame_sink,
                socket_factory=socket_factory,
            )
            for board in config.boards
        ]
        self.aggregator = MultiBoardEventAggregator(
            config.boards,
            config,
            self.frame_queue,
            self.writer,
            self.state,
            self.logger,
            self.stop_event,
            clock=clock,
        )
        self.monitor = MultiBoardMonitorThread(
            config, self.state, self.writer, self.logger, self.stop_event, clock=clock
        )

    # --------------------------------------------------------------- run dir

    def _make_run_dir(self) -> str:
        base_dir = Path(self.config.output_base_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        run_name = self.config.run_name
        if not run_name:
            run_name = "%s_%s" % (
                self.config.run_name_prefix,
                self._clock.local_timestamp(),
            )
        run_dir = base_dir / run_name
        run_dir.mkdir(parents=True, exist_ok=True)
        return str(run_dir)

    # -------------------------------------------------------------- run meta

    def write_run_meta(self, status: str, align_snapshot: AlignSnapshot | None) -> None:
        meta = {
            "format_name": FORMAT_NAME,
            "format_version": FORMAT_VERSION,
            "status": status,
            "config_path": self.config_path,
            "run_dir": self.run_dir,
            "start_time": self.meta_start_time,
            "stop_time": (
                self._clock.iso_now()
                if status in ("stopped", "align_failed")
                else None
            ),
            "tcm_ip": self.config.tcm_ip,
            "tcm_rbcp_port": self.config.tcm_rbcp_port,
            "tcm_allow_start_without_ack": self.config.tcm_allow_start_without_ack,
            "aggregation_key": self.config.aggregation_key,
            "event_timeout_ms": self.config.event_timeout_ms,
            "timestamp_match_window_ticks": self.config.timestamp_match_window_ticks,
            "adc_length": self.config.adc_length,
            "boards_expected": [
                {
                    "board_id": board.board_id,
                    "name": board.name,
                    "ip": board.ip,
                    "tcp_port": board.tcp_port,
                }
                for board in self.config.boards
            ],
        }
        if align_snapshot is not None:
            meta["align_snapshot"] = {
                "status": align_snapshot.status,
                "online_mask": align_snapshot.online_mask,
                "ack_mask": align_snapshot.ack_mask,
                "missing_mask": align_snapshot.missing_mask,
            }
        meta_path = Path(self.run_dir) / "run_meta.json"
        with meta_path.open("w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")

    # ------------------------------------------------------------------- run

    def start(self) -> None:
        self.write_run_meta("created", None)
        success, snapshot = self.tcm.align()
        self.align_snapshot = snapshot
        effective_success = success or self.config.tcm_allow_start_without_ack
        if success:
            meta_status = "aligned"
        elif self.config.tcm_allow_start_without_ack:
            meta_status = "aligned_ack_bypassed"
        else:
            meta_status = "align_failed"
        self.write_run_meta(meta_status, snapshot)
        if not effective_success:
            raise RuntimeError("TCM align failed")
        if not success and self.config.tcm_allow_start_without_ack:
            self.logger.log(
                "WARN",
                "TCM align failed but continuing because allow_start_without_ack=true",
            )

        self.aligned = True
        self.logger.log("INFO", "run_dir=%s" % self.run_dir)
        self.aggregator.start()
        self.monitor.start()
        for receiver in self.receivers:
            receiver.start()
        self._started = True
        self.logger.log("INFO", "acquisition started boards=%d" % len(self.receivers))

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.stop_event.set()
        for receiver in self.receivers:
            if receiver.ident is not None:
                receiver.join(timeout=2.0)
        if self.aggregator.ident is not None:
            self.aggregator.join(timeout=2.0)
        if self.monitor.ident is not None:
            self.monitor.join(timeout=2.0)
        final_status = "stopped" if self.aligned else "align_failed"
        self.write_run_meta(final_status, self.align_snapshot)
        self.writer.close()
        self.logger.log("INFO", "acquisition stopped")
        self.logger.close()


__all__ = ["FrameSink", "MultiBoardAcquisitionApp"]
