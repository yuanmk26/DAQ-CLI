from dataclasses import dataclass


@dataclass(slots=True)
class TcmConfig:
    """One TCM board entry from the profile `tcm:` section."""

    name: str
    ip: str
    rbcp_port: int = 4660
