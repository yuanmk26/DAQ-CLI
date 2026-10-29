"""Per-board TCP_SENT receiver thread."""

from __future__ import annotations

import queue
import socket
import threading
from typing import Any, Callable, Protocol

from daq_cli.infrastructure.adapters.legacy_capture_runner import _TcpSentRawStreamReader
from daq_cli.infrastructure.multi_board_acquire.clock import MultiBoardClock, SYSTEM_CLOCK
from daq_cli.infrastructure.multi_board_acquire.config import (
    MultiBoardAppConfig,
    MultiBoardConfig,
)
from daq_cli.infrastructure.multi_board_acquire.frames import (
    MultiBoardFrame,
    frame_from_fields,
)

SocketFactory = Callable[[], socket.socket]


class FrameSink(Protocol):
    """Receives every parsed frame (used by the waveform watch publisher)."""

    def on_frame(self, frame: MultiBoardFrame) -> None: ...


def _default_socket_factory() -> socket.socket:
    return socket.socket(socket.AF_INET, socket.SOCK_STREAM)


class MultiBoardBoardReceiver(threading.Thread):
    """Read one board's TCP_SENT stream, reconnecting on failure."""

    def __init__(
        self,
        board: MultiBoardConfig,
        config: MultiBoardAppConfig,
        frame_queue: "queue.Queue[MultiBoardFrame]",
        state: Any,
        logger: Any,
        stop_event: threading.Event,
        *,
        clock: MultiBoardClock = SYSTEM_CLOCK,
        frame_sink: FrameSink | None = None,
        socket_factory: SocketFactory | None = None,
    ) -> None:
        super().__init__(daemon=True, name="recv_%s" % board.name)
        self.board = board
        self.config = config
        self.frame_queue = frame_queue
        self.state = state
        self.logger = logger
        self.stop_event = stop_event
        self._clock = clock
        self.frame_sink = frame_sink
        self._socket_factory = socket_factory or _default_socket_factory
        self._mark_next_frame_reconnect = False

    # ------------------------------------------------------------------ run

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self._run_session()
            except Exception as exc:  # noqa: BLE001 - reconnect on any failure
                self.state.mark_recv_error(self.board.board_id)
                self.logger.log(
                    "WARN", "board=%s receiver exception=%s" % (self.board.name, str(exc))
                )
            if self.stop_event.is_set():
                break
            reconnects = self.state.mark_reconnect(self.board.board_id)
            self._mark_next_frame_reconnect = True
            self.state.mark_disconnected(self.board.board_id)
            if reconnects >= self.config.reconnect_warn_count:
                self.logger.log(
                    "WARN", "board=%s reconnect_count=%d" % (self.board.name, reconnects)
                )
            self._clock.sleep(self.config.reconnect_delay_s)

    def _run_session(self) -> None:
        sock = self._socket_factory()
        try:
            sock.settimeout(self.config.tcp_timeout_s)
            self.logger.log(
                "INFO",
                "board=%s connect %s:%d"
                % (self.board.name, self.board.ip, self.board.tcp_port),
            )
            sock.connect((self.board.ip, self.board.tcp_port))
            self.state.mark_connected(self.board.board_id)
            reader = _TcpSentRawStreamReader(
                sock,
                expected_send_mode=None,
                adc_length=self.config.adc_length,
            )

            while not self.stop_event.is_set():
                try:
                    fields = reader.read_frame()
                except socket.timeout:
                    # No data yet; keep the connection alive.
                    continue
                except EOFError:
                    # Peer closed the connection; let run() reconnect.
                    raise ConnectionError("socket closed by peer") from None
                self._publish(fields)
        finally:
            sock.close()

    def _publish(self, fields) -> None:
        frame = frame_from_fields(
            fields,
            self.board,
            recv_unix_ns=self._clock.unix_ns(),
            reconnect_mark=self._mark_next_frame_reconnect,
        )
        self._mark_next_frame_reconnect = False
        self.state.record_frame(frame)
        self._put_frame(frame)
        if self.frame_sink is not None:
            self.frame_sink.on_frame(frame)

    def _put_frame(self, frame: MultiBoardFrame) -> None:
        # Backpressure on a full queue, but never block past a stop request.
        while not self.stop_event.is_set():
            try:
                self.frame_queue.put(frame, timeout=0.1)
                return
            except queue.Full:
                continue


__all__ = ["FrameSink", "MultiBoardBoardReceiver", "SocketFactory"]
