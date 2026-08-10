from __future__ import annotations


ADC_LENGTH = 64
FEATURE_BYTES = 10
FRAME_PREFIX = b"\xFF\xFE\x01"
MODE2_MAGIC = b"\xff\xfe\x01\x02"

# Frame format version carried in header byte 19:
#   0 = legacy 20-byte header (byte 19 was reserved=0)
#   1 = 28-byte header, bytes 20..27 carry crossing_fine / accept_fine
# See FDU-ADC-250M-16ch/docs/delta_fine_timestamp.md
FORMAT_VERSION_LEGACY = 0
FORMAT_VERSION_FINE = 1

_HEADER_BYTES_LEGACY = 20
_HEADER_BYTES_FINE = 28

# Legacy constant kept for callers that only know the old 20-byte frame.
HEADER_BYTES = _HEADER_BYTES_LEGACY


def header_bytes_for(format_version: int) -> int:
    """Return the TCP_SENT header length for a frame format version."""
    if format_version >= FORMAT_VERSION_FINE:
        return _HEADER_BYTES_FINE
    return _HEADER_BYTES_LEGACY


def frame_total_size(
    send_mode: int,
    hit_count: int,
    adc_length: int,
    feature_bytes: int,
    *,
    format_version: int = FORMAT_VERSION_LEGACY,
) -> int:
    header_bytes = header_bytes_for(format_version)
    if send_mode == 0:
        return header_bytes + (hit_count * adc_length * 4)
    if send_mode == 1:
        return header_bytes + (16 * adc_length * 4)
    if send_mode == 2:
        return header_bytes + (hit_count * feature_bytes)
    if send_mode == 3:
        return header_bytes + (hit_count * feature_bytes) + (hit_count * adc_length * 4)
    raise ValueError(f"Unsupported send_mode {send_mode}")
