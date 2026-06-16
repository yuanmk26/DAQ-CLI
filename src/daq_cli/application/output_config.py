from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class OutputTargetConfig:
    enabled: bool = True
    dir: Path | None = None


@dataclass(slots=True)
class TextOutputConfig(OutputTargetConfig):
    max_events_per_file: int = 100
    waveform_layout: str = "channel_blocks"


@dataclass(slots=True)
class AcquireOutputsConfig:
    raw: OutputTargetConfig
    json: OutputTargetConfig
    text: TextOutputConfig
    log: OutputTargetConfig

