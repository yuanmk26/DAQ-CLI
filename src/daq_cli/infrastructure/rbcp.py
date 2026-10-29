"""Native SiTCP RBCP (register access over UDP) client.

This is the native replacement for the vendored ``lib/rbcp.py``. It speaks the
same wire protocol byte-for-byte so it can be swapped in behind the board/TCM
adapters without changing any register semantics:

* 8-byte header ``[0xFF, cmd, packet_id, length, addr_be[4]]`` where ``cmd`` is
  ``0xC0`` for read and ``0x80`` for write.
* ``packet_id`` is an 8-bit rolling counter (mod 256) echoed by the device.
* Reads/writes are one UDP round trip; the reply payload follows the header.

``timeout_ms`` is in milliseconds (matching the legacy client's API); the socket
timeout is ``timeout_ms / 1000`` seconds.
"""

from __future__ import annotations

import os
import select
import socket
import struct
from typing import Callable

HEADER_SIZE = 8
HEADER_READ = 0
HEADER_WRITE = 1
HEADER_VERTYPE = 0xFF

DEFAULT_RBCP_PORT = 4660
DEFAULT_SOCKET_TIMEOUT_MS = 3000
MAX_PAYLOAD_BYTES = 255

# SiTCP devices expose their RBCP port and IP through the environment when the
# legacy scripts are in play; keep that fallback for callers that pass None.
ENV_DEVICE_IP = "SITCP_DEVICE_IP"
ENV_UDP_PORT = "SITCP_UDP_PORT"
FALLBACK_DEVICE_IP = "192.168.10.11"

SocketFactory = Callable[[], socket.socket]


def _default_socket_factory() -> socket.socket:
    return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


class RbcpError(Exception):
    """Base class for RBCP transport/protocol errors."""


class RbcpBusError(RbcpError):
    """The device replied with the RBCP bus-error flag set.

    Raised when the register address/length pair is rejected by the firmware.
    """

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "SiTCP RBCP Bus Error. Check Device Address and Length for read/write"
        )


class RbcpTimeout(RbcpError):
    """No reply arrived within the configured timeout."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "SiTCP RBCP Timeout. Check Device IP and UDP Port.")


def make_header(
    read_write: int,
    register_address: int,
    length: int,
    packet_id: int,
) -> bytes:
    """Build an 8-byte RBCP header.

    ``read_write`` is :data:`HEADER_READ` (0) or :data:`HEADER_WRITE` (1).
    """
    if not isinstance(register_address, int):
        raise ValueError("Register address must be an int.")
    if not isinstance(length, int):
        raise ValueError("Length must be an int.")
    if register_address < 0 or register_address > 0xFFFFFFFF:
        raise ValueError("Invalid register address.")
    if length < 0 or length > MAX_PAYLOAD_BYTES:
        raise ValueError(
            "Specify a value between 0 and 255 for SiTCP read/write length."
        )
    if register_address + length > 0xFFFFFFFF:
        raise ValueError("Invalid register address.")

    command_type = 0xC0 if read_write == HEADER_READ else 0x80
    return struct.pack(
        "8B",
        HEADER_VERTYPE,
        command_type,
        packet_id & 0xFF,
        length,
        (register_address >> 24) & 0xFF,
        (register_address >> 16) & 0xFF,
        (register_address >> 8) & 0xFF,
        register_address & 0xFF,
    )


class RbcpClient:
    """UDP RBCP client for one SiTCP device.

    >>> with RbcpClient("192.168.10.10") as bus:
    ...     mode = bus.read(0x42, 1)[0]
    """

    def __init__(
        self,
        device_ip: str | None = None,
        udp_port: int | None = None,
        timeout_ms: int = DEFAULT_SOCKET_TIMEOUT_MS,
        *,
        socket_factory: SocketFactory | None = None,
    ) -> None:
        if device_ip is None:
            device_ip = os.environ.get(ENV_DEVICE_IP, FALLBACK_DEVICE_IP)
        if udp_port is None:
            udp_port = int(os.environ.get(ENV_UDP_PORT, str(DEFAULT_RBCP_PORT)))

        self.device_ip = str(device_ip)
        self.udp_port = int(udp_port)
        self._address = (self.device_ip, self.udp_port)
        self._packet_id = 0
        self._socket_timeout_s = max(float(timeout_ms), 0.0) / 1000.0
        factory = socket_factory or _default_socket_factory
        self._sock = factory()
        self._sock.settimeout(self._socket_timeout_s)

    # ------------------------------------------------------------- lifecycle

    def __enter__(self) -> "RbcpClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    # ------------------------------------------------------------ operations

    def read(self, register_address: int, length: int) -> bytes:
        """Read ``length`` bytes starting at ``register_address``."""
        return self._send_recv(HEADER_READ, register_address, length, b"")

    def write(self, register_address: int, data: bytes | bytearray) -> bytes:
        """Write ``data`` at ``register_address``; returns the reply payload."""
        payload = bytes(data)
        return self._send_recv(HEADER_WRITE, register_address, len(payload), payload)

    # --------------------------------------------------------------- internals

    def _next_packet_id(self) -> int:
        wait_id = self._packet_id
        self._packet_id = (self._packet_id + 1) % 256
        return wait_id

    def _send_recv(
        self,
        read_write: int,
        register_address: int,
        length: int,
        payload: bytes,
    ) -> bytes:
        header = make_header(read_write, register_address, length, self._packet_id)
        wait_id = self._next_packet_id()
        packet = header + payload

        sent = 0
        while sent < len(packet):
            try:
                written = self._sock.sendto(packet[sent:], self._address)
            except OSError as exc:
                raise RbcpError(f"RBCP Socket Error on send_packet {exc}") from exc
            if written <= 0:
                raise RbcpError(
                    f"RBCP Socket send_packet sendto returns non-positive({written})"
                )
            sent += written

        reply = self._recv_packet()
        self._check_packet(reply, wait_id)
        return reply[HEADER_SIZE:]

    def _recv_packet(self) -> bytes:
        try:
            readable, _, _ = select.select(
                [self._sock], [], [], self._socket_timeout_s
            )
        except OSError as exc:
            raise RbcpError(f"RBCP:Exception when receiving packet [{exc}]") from exc
        if not readable:
            raise RbcpTimeout()
        try:
            reply, _addr = self._sock.recvfrom(HEADER_SIZE + MAX_PAYLOAD_BYTES)
        except OSError as exc:
            raise RbcpError(f"RBCP:Exception when receiving packet [{exc}]") from exc
        if not reply:
            raise RbcpError("RBCP:Receive Data Length was zero.")
        return bytes(reply)

    @staticmethod
    def _check_packet(packet: bytes, wait_id: int) -> None:
        if len(packet) < HEADER_SIZE:
            raise RbcpError(
                f"RBCP header too short({len(packet)}/{HEADER_SIZE})"
            )
        if packet[0] != HEADER_VERTYPE:
            raise RbcpError("RBCP Header Version Mismatch")
        if (packet[1] & 0x1) == 1:
            raise RbcpBusError()
        if packet[2] != wait_id:
            raise RbcpError("RBCP Packet ID Mismatch")
