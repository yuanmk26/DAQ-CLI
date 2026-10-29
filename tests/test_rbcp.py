"""Native RBCP client: wire-format parity with the vendored ``lib/rbcp.py``.

These tests are hardware-free: a fake UDP socket records what the client sends
and replays a canned reply.
"""

from __future__ import annotations

import socket
import struct

import pytest

from daq_cli.infrastructure.rbcp import (
    HEADER_READ,
    HEADER_WRITE,
    RbcpBusError,
    RbcpClient,
    RbcpError,
    RbcpTimeout,
    make_header,
)


class FakeUdpSocket:
    """Minimal stand-in for ``socket.socket(SOCK_DGRAM)``."""

    def __init__(self, replies: list[bytes] | None = None) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.timeout: float | None = None
        self.closed = False
        self._replies = list(replies or [])

    def has_reply(self) -> bool:
        return bool(self._replies)

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def sendto(self, data: bytes, address) -> int:
        self.sent.append((bytes(data), address))
        return len(data)

    def recvfrom(self, _size: int):
        if not self._replies:
            raise socket.timeout("no reply")
        return self._replies.pop(0), ("127.0.0.1", 4660)

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def fake_select(monkeypatch):
    """Make ``select.select`` consult :class:`FakeUdpSocket` readiness.

    A real UDP socket has a file descriptor that ``select`` can poll; the fake
    cannot, so route readiness through the fake's pending-reply queue instead.
    """
    import daq_cli.infrastructure.rbcp as rbcp_module

    def _select(read_list, _write_list, _error_list, _timeout):
        fake = next((s for s in read_list if isinstance(s, FakeUdpSocket)), None)
        if fake is None:
            return ([], [], [])
        return ([fake], [], []) if fake.has_reply() else ([], [], [])

    monkeypatch.setattr(rbcp_module.select, "select", _select)
    return _select


def _reply(packet_id: int, payload: bytes = b"", *, bus_error: bool = False) -> bytes:
    header = bytes([0xFF, 0x1 if bus_error else 0x0, packet_id, len(payload), 0, 0, 0, 0])
    return header + payload


def _client(replies: list[bytes] | None = None, **kwargs) -> tuple[RbcpClient, FakeUdpSocket]:
    sock = FakeUdpSocket(replies)
    client = RbcpClient("192.168.10.10", socket_factory=lambda: sock, **kwargs)
    return client, sock


class TestRbcpHeader:
    def test_read_header_layout_matches_spec(self):
        header = make_header(HEADER_READ, 0x42, 1, 7)
        assert header == bytes([0xFF, 0xC0, 7, 1, 0x00, 0x00, 0x00, 0x42])

    def test_write_header_layout_matches_spec(self):
        header = make_header(HEADER_WRITE, 0x0000_1234, 2, 0)
        assert header == bytes([0xFF, 0x80, 0, 2, 0x00, 0x00, 0x12, 0x34])

    def test_matches_vendored_header_builder(self):
        from daq_cli._vendor.fdu_legacy.lib import rbcp as vendored

        for address in (0x00, 0x42, 0x45, 0x6C, 0x00FFFFFF):
            for length in (0, 1, 7, 255):
                for packet_id in (0, 1, 255):
                    assert make_header(
                        HEADER_READ, address, length, packet_id
                    ) == vendored.Rbcp._make_header(
                        vendored.HEADER_READ, address, length, packet_id
                    )
                    assert make_header(
                        HEADER_WRITE, address, length, packet_id
                    ) == vendored.Rbcp._make_header(
                        vendored.HEADER_WRITE, address, length, packet_id
                    )

    def test_rejects_out_of_range_length(self):
        with pytest.raises(ValueError):
            make_header(HEADER_READ, 0x10, 256, 0)

    def test_rejects_negative_address(self):
        with pytest.raises(ValueError):
            make_header(HEADER_READ, -1, 1, 0)


class TestRbcpClient:
    def test_read_returns_payload_after_header(self):
        client, sock = _client([_reply(0, b"\x03")])
        assert client.read(0x42, 1) == b"\x03"
        sent, address = sock.sent[0]
        assert address == ("192.168.10.10", 4660)
        assert sent == bytes([0xFF, 0xC0, 0, 1, 0, 0, 0, 0x42])

    def test_write_sends_payload_and_returns_reply(self):
        client, sock = _client([_reply(0, b"")])
        client.write(0x42, b"\xAB")
        sent, _ = sock.sent[0]
        assert sent == bytes([0xFF, 0x80, 0, 1, 0, 0, 0, 0x42, 0xAB])

    def test_packet_id_wraps_at_256(self):
        replies = [_reply(i) for i in range(256)] + [_reply(0)]
        client, sock = _client(replies)
        for _ in range(257):
            client.read(0x00, 1)
        ids = [packet[2] for packet, _ in sock.sent]
        assert ids[:3] == [0, 1, 2]
        assert ids[254] == 254
        assert ids[255] == 255
        assert ids[256] == 0

    def test_timeout_ms_converted_to_seconds(self):
        client, _ = _client([], timeout_ms=3000)
        # FakeUdpSocket records the value passed to settimeout().
        assert client._sock.timeout == 3.0

    def test_no_reply_raises_timeout(self):
        client, _ = _client([])
        with pytest.raises(RbcpTimeout):
            client.read(0x00, 1)

    def test_bus_error_flag_raises(self):
        client, _ = _client([_reply(0, b"", bus_error=True)])
        with pytest.raises(RbcpBusError):
            client.read(0x00, 1)

    def test_version_mismatch_raises(self):
        bad = bytes([0x00, 0x00, 0, 0, 0, 0, 0, 0])
        client, _ = _client([bad])
        with pytest.raises(RbcpError, match="Version Mismatch"):
            client.read(0x00, 1)

    def test_packet_id_mismatch_raises(self):
        client, _ = _client([_reply(9)])
        with pytest.raises(RbcpError, match="Packet ID Mismatch"):
            client.read(0x00, 1)

    def test_short_reply_raises(self):
        client, _ = _client([b"\xff\x00"])
        with pytest.raises(RbcpError, match="too short"):
            client.read(0x00, 1)

    def test_context_manager_closes_socket(self):
        sock = FakeUdpSocket([_reply(0, b"\x01")])
        with RbcpClient("192.168.10.10", socket_factory=lambda: sock) as client:
            assert client.read(0x00, 1) == b"\x01"
        assert sock.closed

    def test_environment_fallback_for_ip_and_port(self, monkeypatch):
        monkeypatch.setenv("SITCP_DEVICE_IP", "10.0.0.5")
        monkeypatch.setenv("SITCP_UDP_PORT", "1234")
        sock = FakeUdpSocket([_reply(0, b"\x00")])
        client = RbcpClient(socket_factory=lambda: sock)
        client.read(0x00, 1)
        assert sock.sent[0][1] == ("10.0.0.5", 1234)


class TestRbcpAgainstVendoredRoundTrip:
    """The native client and the vendored client must speak identical bytes."""

    def test_same_request_bytes_as_vendored(self):
        from daq_cli._vendor.fdu_legacy.lib import rbcp as vendored

        native_sock = FakeUdpSocket([_reply(0, b"\x05\x06")])
        native = RbcpClient("192.168.10.10", socket_factory=lambda: native_sock)
        assert native.read(0x19, 2) == b"\x05\x06"

        # Build the same request with the vendored code and compare.
        expected_header = vendored.Rbcp._make_header(
            vendored.HEADER_READ, 0x19, 2, 0
        )
        assert native_sock.sent[0][0] == expected_header

    def test_payload_length_field_matches_data(self):
        client, sock = _client([_reply(0, b"\x00" * 4)])
        client.write(0x100, struct.pack("BBBB", 1, 2, 3, 4))
        sent, _ = sock.sent[0]
        assert sent[3] == 4
