from dataclasses import dataclass, field


@dataclass(slots=True)
class GroupConfig:
    name: str
    devices: list[str] = field(default_factory=list)
    tcm: str | None = None
