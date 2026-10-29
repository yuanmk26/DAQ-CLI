"""Board configuration for the native multi-board pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from daq_cli.infrastructure.multi_board_acquire.constants import (
    DEFAULT_ADC_LENGTH,
    DEFAULT_BOARD_WARN_NO_DATA_S,
    DEFAULT_EVENT_TIMEOUT_MS,
    DEFAULT_MONITOR_INTERVAL_S,
    DEFAULT_MONITOR_JSONL_INTERVAL_S,
    DEFAULT_PARTIAL_WARN_RATIO,
    DEFAULT_QUEUE_SIZE,
    DEFAULT_RECV_BUFFER_BYTES,
    DEFAULT_RECONNECT_DELAY_S,
    DEFAULT_RECONNECT_WARN_COUNT,
    DEFAULT_TCM_COMMAND_DELAY_S,
    DEFAULT_TCM_POLL_INTERVAL_S,
    DEFAULT_TCM_POLL_TIMEOUT_S,
    DEFAULT_TCM_TIMEOUT_MS,
    DEFAULT_TCP_TIMEOUT_S,
    bit_count,
)


@dataclass(slots=True)
class MultiBoardConfig:
    """One ADC board participating in a multi-board capture."""

    board_id: int
    name: str
    ip: str
    tcp_port: int = 24


@dataclass(slots=True)
class MultiBoardAppConfig:
    """Runtime configuration for :class:`MultiBoardAcquisitionApp`.

    Field names mirror the vendored ``AppConfig`` so the JSON payload produced
    by the capture runner is interchangeable between the two implementations.
    """

    run_name_prefix: str = "run"
    run_name: str | None = None
    output_base_dir: str = "out/multi_board_acquire"
    tcm_ip: str = ""
    tcm_rbcp_port: int = 4660
    tcm_timeout_ms: int = DEFAULT_TCM_TIMEOUT_MS
    tcm_command_delay_s: float = DEFAULT_TCM_COMMAND_DELAY_S
    tcm_poll_interval_s: float = DEFAULT_TCM_POLL_INTERVAL_S
    tcm_poll_timeout_s: float = DEFAULT_TCM_POLL_TIMEOUT_S
    tcm_allow_start_without_ack: bool = False
    adc_length: int = DEFAULT_ADC_LENGTH
    aggregation_key: str = "timestamp"
    timestamp_match_window_ticks: int = 0
    event_timeout_ms: int = DEFAULT_EVENT_TIMEOUT_MS
    monitor_interval_s: float = DEFAULT_MONITOR_INTERVAL_S
    monitor_jsonl_interval_s: float = DEFAULT_MONITOR_JSONL_INTERVAL_S
    tcp_timeout_s: float = DEFAULT_TCP_TIMEOUT_S
    reconnect_delay_s: float = DEFAULT_RECONNECT_DELAY_S
    recv_buffer_bytes: int = DEFAULT_RECV_BUFFER_BYTES
    frame_queue_size: int = DEFAULT_QUEUE_SIZE
    board_warn_no_data_s: float = DEFAULT_BOARD_WARN_NO_DATA_S
    partial_warn_ratio: float = DEFAULT_PARTIAL_WARN_RATIO
    reconnect_warn_count: int = DEFAULT_RECONNECT_WARN_COUNT
    boards: list[MultiBoardConfig] = field(default_factory=list)

    # ------------------------------------------------------------------ ctors

    @classmethod
    def from_payload(cls, raw: dict) -> "MultiBoardAppConfig":
        """Build the config from the JSON payload written by the capture runner."""
        boards: list[MultiBoardConfig] = []
        for item in raw.get("boards", []):
            boards.append(
                MultiBoardConfig(
                    board_id=int(item["board_id"]),
                    name=str(item["name"]),
                    ip=str(item["ip"]),
                    tcp_port=int(item.get("tcp_port", 24)),
                )
            )

        board_ids = [board.board_id for board in boards]
        if len(board_ids) != len(set(board_ids)):
            raise ValueError("board_id values must be unique")
        if any(board_id < 0 or board_id > 31 for board_id in board_ids):
            raise ValueError("board_id must stay in range 0..31 for 32-bit masks")

        tcm = raw.get("tcm") or {}
        run_name = raw.get("run_name")
        return cls(
            run_name_prefix=str(raw.get("run_name_prefix", "run")),
            run_name=str(run_name) if run_name not in (None, "") else None,
            output_base_dir=str(
                raw.get("output_base_dir", "out/multi_board_acquire")
            ),
            tcm_ip=str(tcm.get("ip", "")),
            tcm_rbcp_port=int(tcm.get("rbcp_port", 4660)),
            tcm_timeout_ms=int(tcm.get("timeout_ms", DEFAULT_TCM_TIMEOUT_MS)),
            tcm_command_delay_s=float(
                tcm.get("command_delay_s", DEFAULT_TCM_COMMAND_DELAY_S)
            ),
            tcm_poll_interval_s=float(
                tcm.get("poll_interval_s", DEFAULT_TCM_POLL_INTERVAL_S)
            ),
            tcm_poll_timeout_s=float(
                tcm.get("poll_timeout_s", DEFAULT_TCM_POLL_TIMEOUT_S)
            ),
            tcm_allow_start_without_ack=bool(tcm.get("allow_start_without_ack", False)),
            adc_length=int(raw.get("adc_length", DEFAULT_ADC_LENGTH)),
            aggregation_key=str(raw.get("aggregation_key", "timestamp")),
            timestamp_match_window_ticks=int(
                raw.get("timestamp_match_window_ticks", 0)
            ),
            event_timeout_ms=int(raw.get("event_timeout_ms", DEFAULT_EVENT_TIMEOUT_MS)),
            monitor_interval_s=float(
                raw.get("monitor_interval_s", DEFAULT_MONITOR_INTERVAL_S)
            ),
            monitor_jsonl_interval_s=float(
                raw.get("monitor_jsonl_interval_s", DEFAULT_MONITOR_JSONL_INTERVAL_S)
            ),
            tcp_timeout_s=float(raw.get("tcp_timeout_s", DEFAULT_TCP_TIMEOUT_S)),
            reconnect_delay_s=float(
                raw.get("reconnect_delay_s", DEFAULT_RECONNECT_DELAY_S)
            ),
            recv_buffer_bytes=int(raw.get("recv_buffer_bytes", DEFAULT_RECV_BUFFER_BYTES)),
            frame_queue_size=int(raw.get("frame_queue_size", DEFAULT_QUEUE_SIZE)),
            board_warn_no_data_s=float(
                raw.get("board_warn_no_data_s", DEFAULT_BOARD_WARN_NO_DATA_S)
            ),
            partial_warn_ratio=float(
                raw.get("partial_warn_ratio", DEFAULT_PARTIAL_WARN_RATIO)
            ),
            reconnect_warn_count=int(
                raw.get("reconnect_warn_count", DEFAULT_RECONNECT_WARN_COUNT)
            ),
            boards=boards,
        )

    # --------------------------------------------------------------- helpers

    @property
    def board_ids(self) -> list[int]:
        return [board.board_id for board in self.boards]

    def run_dir_for(self, base_dir: Path | str, run_name: str) -> Path:
        return Path(base_dir) / run_name


__all__ = ["MultiBoardAppConfig", "MultiBoardConfig", "bit_count"]
