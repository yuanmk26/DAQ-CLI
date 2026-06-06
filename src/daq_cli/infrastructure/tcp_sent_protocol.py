from __future__ import annotations


ADC_LENGTH = 64
HEADER_BYTES = 20
FEATURE_BYTES = 10
FRAME_PREFIX = b"\xFF\xFE\x01"
MODE2_MAGIC = b"\xff\xfe\x01\x02"


def frame_total_size(
    send_mode: int,
    hit_count: int,
    adc_length: int,
    feature_bytes: int,
) -> int:
    if send_mode == 0:
        return HEADER_BYTES + (hit_count * adc_length * 4)
    if send_mode == 1:
        return HEADER_BYTES + (16 * adc_length * 4)
    if send_mode == 2:
        return HEADER_BYTES + (hit_count * feature_bytes)
    if send_mode == 3:
        return HEADER_BYTES + (hit_count * feature_bytes) + (hit_count * adc_length * 4)
    raise ValueError(f"Unsupported send_mode {send_mode}")
