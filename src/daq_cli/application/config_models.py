from dataclasses import dataclass
from typing import Tuple


@dataclass(slots=True)
class BoardConfigOptions:
    adc_enabled: bool = False
    clock_enabled: bool = False
    trigger_enabled: bool = True
    tcp_mode2_enabled: bool = True
    trigger_thresholds: Tuple[int, int, int, int] = (1950, 2400, 2300, 2300)
    trigger_mode: int = 1
    trigger_position: int = 40
    timestamp_clean_enabled: bool = False
    ext_trigger_enabled: bool = False
    send_mode: int | None = None
