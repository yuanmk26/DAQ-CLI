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

    def __post_init__(self) -> None:
        # 0x10 Trigger_model is an 8-bit register.  Accept the full byte
        # range so new firmware modes (10/11/12 today) do not require a
        # script update; the current firmware defines 0..12.
        if not 0 <= self.trigger_mode <= 0xFF:
            raise ValueError(
                "trigger_mode must be in 0..255 (register 0x10 is 8-bit; "
                f"current firmware defines 0..12), got {self.trigger_mode}"
            )


def board_profile_options(defaults: dict) -> BoardConfigOptions:
    fallback = BoardConfigOptions()
    thresholds = defaults.get("thresholds", fallback.trigger_thresholds)
    if not isinstance(thresholds, (list, tuple)) or len(thresholds) != 4:
        raise ValueError("defaults.thresholds must contain four trigger thresholds")
    position = int(defaults.get("trigger_position", fallback.trigger_position))
    if not 0 <= position <= 255:
        raise ValueError("defaults.trigger_position must be in 0..255")
    values = tuple(int(value) for value in thresholds)
    if any(not 0 <= value <= 0xFFFF for value in values):
        raise ValueError("defaults.thresholds values must be in 0..65535")
    return BoardConfigOptions(
        trigger_mode=int(defaults.get("trigger_mode", fallback.trigger_mode)),
        trigger_position=position,
        trigger_thresholds=values,
    )
