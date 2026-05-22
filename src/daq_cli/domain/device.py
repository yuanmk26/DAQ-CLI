from dataclasses import dataclass


@dataclass(slots=True)
class DeviceConfig:
    name: str
    ip: str
    rbcp_port: int
    tcp_port: int
    board_id: int
    role: str | None = None
