"""Pure formatting helpers for the GUI console.

Everything here is free of tkinter so it can be unit tested without a
display. It mirrors the semantic content of ``presentation/console/printers``
as plain "field: value" text, plus form-value helpers for building service
parameters.
"""

from __future__ import annotations

from pathlib import Path

from daq_cli.application.acquire_service import (
    MultiAcquireResult,
    SingleAcquireResult,
    SingleAcquireProgress,
)
from daq_cli.application.board_service import (
    BoardInfoResult,
    RegisterReadResult,
    TcmLinkConfigReadResult,
    TcmLinkConfigWriteResult,
    TcpMode2ConfigReadResult,
    TriggerConfigReadResult,
)
from daq_cli.application.config_models import BoardConfigOptions
from daq_cli.application.telemetry_service import BoardSysmonResult
from daq_cli.domain.tcm import TcmConfig


def format_fields(title: str, fields: list[tuple[str, object]]) -> str:
    lines = [f"===== {title} ====="]
    for key, value in fields:
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


# ---------------------------------------------------------------- board read


def format_board_info(result: BoardInfoResult) -> str:
    return format_fields(
        f"Board Info: {result.device.name}",
        [
            ("name", result.device.name),
            ("ip", result.device.ip),
            ("rbcp_port", result.device.rbcp_port),
            ("tcp_port", result.device.tcp_port),
            ("board_id", result.device.board_id),
            ("role", result.device.role or "-"),
            ("profile", result.source_profile),
        ],
    )


def format_sysmon(result: BoardSysmonResult) -> str:
    snapshot = result.snapshot
    return format_fields(
        f"FPGA Telemetry: {result.device.name}",
        [
            ("temperature_c", f"{snapshot.temperature_c:.1f}"),
            ("vccint_v", f"{snapshot.vccint_v:.3f}"),
            ("vccaux_v", f"{snapshot.vccaux_v:.3f}"),
            ("vccbram_v", f"{snapshot.vccbram_v:.3f}"),
            ("profile", result.source_profile),
        ],
    )


def format_trigger_config(result: TriggerConfigReadResult) -> str:
    return format_fields(
        f"Trigger Config: {result.device.name}",
        [
            ("trigger_mode", result.trigger_mode),
            ("trigger_position", result.trigger_position),
            ("thresholds", ", ".join(str(v) for v in result.thresholds)),
            ("send_start_delay_reg", result.send_start_delay),
            ("timestamp_clean_enabled", result.timestamp_clean_enabled),
            ("ext_trigger_enabled", result.ext_trigger_enabled),
            ("profile", result.source_profile),
        ],
    )


def format_tcp_mode2_config(result: TcpMode2ConfigReadResult) -> str:
    return format_fields(
        f"TCP Mode-2 Config: {result.device.name}",
        [
            ("send_mode", result.send_mode),
            ("integration_pre_samples", result.integration_pre_samples),
            ("integration_post_samples", result.integration_post_samples),
            ("hit_thresholds", ", ".join(str(v) for v in result.hit_thresholds)),
            ("hit_polarities", ", ".join(str(v) for v in result.hit_polarities)),
            ("profile", result.source_profile),
        ],
    )


def _tcm_link_rows(
    *,
    device_name: str,
    mask: int,
    polarity: int,
    debounce: int,
    pulse_width: int,
    enable: bool,
    thresholds: list[int] | None,
    profile: Path,
) -> list[tuple[str, object]]:
    enabled_channels = [channel for channel in range(16) if (mask >> channel) & 0x1]
    rows: list[tuple[str, object]] = [
        ("mask", f"0x{mask:04X} ({len(enabled_channels)} ch)"),
        ("polarity", f"0x{polarity:04X}"),
        ("debounce", f"{debounce} x 5ns = {debounce * 5e-3:.1f} us"),
        ("pulse_width", f"{pulse_width} x 5ns = {pulse_width * 5} ns"),
        ("enable", enable),
    ]
    if thresholds is not None:
        for channel in enabled_channels:
            direction = "neg" if (polarity >> channel) & 0x1 else "pos"
            rows.append(
                (f"thr ch{channel:02d}", f"{thresholds[channel]} ({direction})")
            )
    rows.append(("profile", profile))
    return rows


def format_tcm_link_read(result: TcmLinkConfigReadResult) -> str:
    rows = _tcm_link_rows(
        device_name=result.device.name,
        mask=result.mask,
        polarity=result.polarity,
        debounce=result.debounce,
        pulse_width=result.pulse_width,
        enable=result.enable,
        thresholds=result.thresholds,
        profile=result.source_profile,
    )
    return format_fields(f"TCM Link Config: {result.device.name}", rows)


def format_tcm_link_write(result: TcmLinkConfigWriteResult) -> str:
    rows = _tcm_link_rows(
        device_name=result.device.name,
        mask=result.mask,
        polarity=result.polarity,
        debounce=result.debounce,
        pulse_width=result.pulse_width,
        enable=result.enable,
        thresholds=result.thresholds,
        profile=result.source_profile,
    )
    return format_fields(f"TCM Link Config Written: {result.device.name}", rows)


def format_register_read(result: RegisterReadResult) -> str:
    data = result.data
    lines = [
        f"===== Register 0x{result.address:02X} ({result.device.name}) =====",
        f"length: {len(data)}",
    ]
    for offset in range(0, len(data), 8):
        chunk = data[offset : offset + 8]
        hex_part = " ".join(f"{byte:02X}" for byte in chunk)
        ascii_part = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in chunk)
        lines.append(f"0x{result.address + offset:02X}: {hex_part:<23} {ascii_part}")
    return "\n".join(lines)


# ---------------------------------------------------------------- config form


def board_config_options_from_form(
    *,
    adc_enabled: bool,
    clock_enabled: bool,
    trigger_enabled: bool,
    tcp_mode2_enabled: bool,
    trigger_mode: int,
    trigger_position: int,
    threshold_1: int,
    threshold_2: int,
    threshold_3: int,
    threshold_4: int,
    timestamp_clean_enabled: bool,
    ext_trigger_enabled: bool,
    send_mode: int | None,
) -> BoardConfigOptions:
    return BoardConfigOptions(
        adc_enabled=adc_enabled,
        clock_enabled=clock_enabled,
        trigger_enabled=trigger_enabled,
        tcp_mode2_enabled=tcp_mode2_enabled,
        trigger_thresholds=(threshold_1, threshold_2, threshold_3, threshold_4),
        trigger_mode=trigger_mode,
        trigger_position=trigger_position,
        timestamp_clean_enabled=timestamp_clean_enabled,
        ext_trigger_enabled=ext_trigger_enabled,
        send_mode=send_mode,
    )


def parse_int_field(text: str, field_name: str) -> int:
    """Parse one integer field (decimal or 0x-prefixed hex)."""
    stripped = text.strip()
    if not stripped:
        raise ValueError(f"{field_name} 为空")
    try:
        return int(stripped, 0)
    except ValueError as exc:
        raise ValueError(f"{field_name} 不是有效整数: {stripped!r}") from exc


def mode9_thresholds_from_fields(texts: list[str]) -> list[int]:
    """Parse the 16 per-channel threshold fields, validating the 16-bit range."""
    if len(texts) != 16:
        raise ValueError(f"需要 16 个通道阈值字段，收到 {len(texts)} 个")
    values = [
        parse_int_field(text, f"ch{channel:02d} 阈值")
        for channel, text in enumerate(texts)
    ]
    for channel, value in enumerate(values):
        if value < 0 or value > 0xFFFF:
            raise ValueError(f"ch{channel:02d} 阈值超出范围 0..0xFFFF: {value}")
    return values


def mode9_readback_to_values(
    trigger, tcm, tcp
) -> dict[str, object]:
    """Map service readback results to mode-9 panel form values.

    Text fields map to ``str``, checkboxes to ``bool``; the tab decides how
    to apply each to its widget variables.
    """
    return {
        "model": str(trigger.trigger_mode),
        "position": str(trigger.trigger_position),
        "time_clean": bool(trigger.timestamp_clean_enabled),
        "ext_trigger": bool(trigger.ext_trigger_enabled),
        "start_delay": str(trigger.send_start_delay),
        "thr": [str(value) for value in tcm.thresholds],
        "mask": f"0x{tcm.mask:04X}",
        "polarity": f"0x{tcm.polarity:04X}",
        "debounce": str(tcm.debounce),
        "enable": bool(tcm.enable),
        "pulse_width": str(tcm.pulse_width),
        "send_mode": str(tcp.send_mode),
        "integ_pre": str(tcp.integration_pre_samples),
        "integ_post": str(tcp.integration_post_samples),
    }


def parse_int_list(text: str, count: int, field_name: str) -> list[int]:
    """Parse 1 or ``count`` comma/whitespace separated integers (1 = broadcast)."""
    raw = [part for part in text.replace(",", " ").split() if part]
    if not raw:
        raise ValueError(f"{field_name} 为空")
    values = [int(part, 0) for part in raw]
    if len(values) == 1:
        return values * count
    if len(values) != count:
        raise ValueError(
            f"{field_name} 需要 1 个值（广播）或 {count} 个值，收到 {len(values)} 个"
        )
    return values


# ---------------------------------------------------------------- acquire


def format_single_progress(progress: SingleAcquireProgress) -> str:
    rate = f"{progress.event_rate_hz:.1f}" if progress.event_rate_hz else "-"
    return (
        f"事件 {progress.captured_events}/{progress.requested_events} "
        f"({rate} ev/s)"
    )


def format_single_acquire_result(result: SingleAcquireResult) -> str:
    return format_fields(
        f"Single Acquire: {result.device.name}",
        [
            ("requested_events", result.requested_events),
            ("captured_events", result.captured_events),
            ("send_mode", result.send_mode),
            ("decode_enabled", result.decode_enabled),
            ("decoded_events", result.decoded_events),
            ("decode_errors", result.decode_errors),
            ("json_output_enabled", result.json_output_enabled),
            ("text_output_enabled", result.text_output_enabled),
            ("text_output_events", result.text_output_events),
            ("text_output_files", result.text_output_files),
            ("run_output_dir", result.run_output_dir),
            ("raw_output_dir", result.raw_output_dir),
            ("json_output_dir", result.json_output_dir),
            ("text_output_dir", result.text_output_dir),
            ("log_path", result.log_output_path),
            ("profile", result.source_profile),
        ],
    )


def format_multi_acquire_result(result: MultiAcquireResult) -> str:
    return format_fields(
        f"Multi Acquire: {result.group.name}",
        [
            ("boards", ", ".join(device.name for device in result.devices)),
            ("aggregation_key", result.aggregation_key),
            ("status", result.status),
            ("decoded_complete_events", result.decoded_complete_events),
            ("decoded_partial_events", result.decoded_partial_events),
            ("decode_errors", result.decode_errors),
            ("text_output_complete_events", result.text_output_complete_events),
            ("text_output_partial_events", result.text_output_partial_events),
            ("text_output_files", result.text_output_files),
            ("run_output_dir", result.run_output_dir),
            ("log_path", result.log_path),
            ("profile", result.source_profile),
        ],
    )


# ---------------------------------------------------------------- tcm board


def format_tcm_trigger_read(
    tcm: TcmConfig,
    *,
    source_profile: Path,
    enable: bool,
    mask: int,
    pulse_width: int,
    debounce: int,
    trig_sticky: bool,
    pending: bool,
    wide_pulse_active: bool,
    last_trigger_channels: int,
) -> str:
    enabled_channels = [channel for channel in range(8) if (mask >> channel) & 0x1]
    rows: list[tuple[str, object]] = [
        ("tcm_ip", f"{tcm.ip}:{tcm.rbcp_port}"),
        ("enable", enable),
        ("mask", f"0x{mask:02X} ({len(enabled_channels)} ch)"),
        ("pulse_width", f"{pulse_width} x 50ns = {pulse_width * 50e-3:.1f} us"),
        ("debounce", f"{debounce} x 50ns = {debounce * 50e-3:.1f} us"),
        ("trig_sticky", trig_sticky),
        ("pending", pending),
        ("wide_pulse_active", wide_pulse_active),
        (
            "last_trigger_channels",
            ",".join(
                str(channel)
                for channel in range(8)
                if (last_trigger_channels >> channel) & 0x1
            )
            if last_trigger_channels
            else "-",
        ),
        ("profile", source_profile),
    ]
    return format_fields(f"TCM Trigger Config: {tcm.name}", rows)