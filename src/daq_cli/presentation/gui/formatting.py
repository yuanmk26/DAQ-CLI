"""Pure formatting helpers for the GUI console.

Everything here is free of tkinter so it can be unit tested without a
display. It mirrors the semantic content of ``presentation/console/printers``
as plain "field: value" text, plus form-value helpers for building service
parameters.
"""

from __future__ import annotations

from pathlib import Path

from daq_cli.application.acquire_options import default_output_base_dir, resolve_outputs_config
from daq_cli.application.acquire_service import (
    MultiAcquireResult,
    SingleAcquireResult,
    SingleAcquireProgress,
)
from daq_cli.infrastructure.tcm_link_calibration import suggested_threshold_for
from daq_cli.application.output_config import (
    AcquireOutputsConfig,
    OutputTargetConfig,
    TextOutputConfig,
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


def resolve_mode9_thresholds(
    thr_texts: list[str], offset_texts: list[str], baselines: list[int] | None
) -> list[int]:
    """Resolve per-channel thresholds, offset entry taking priority.

    Each channel has an absolute threshold field and an optional offset
    field (baseline + offset, e.g. "-100").  A non-empty offset is used
    when the calibration baselines are available; otherwise the absolute
    field wins.  Empty offset fields fall back to the absolute field.
    """
    if len(thr_texts) != 16 or len(offset_texts) != 16:
        raise ValueError("需要 16 个通道阈值与偏移字段")
    if baselines is not None and len(baselines) != 16:
        raise ValueError("基线列表需要 16 个值")
    values: list[int] = []
    for channel, (thr_text, offset_text) in enumerate(zip(thr_texts, offset_texts)):
        if offset_text.strip() and baselines is not None:
            offset = parse_int_field(offset_text, f"ch{channel:02d} 偏移")
            value = baselines[channel] + offset
            if value < 0 or value > 0xFFFF:
                raise ValueError(
                    f"ch{channel:02d} 基线{baselines[channel]}{offset:+d} "
                    f"超出范围 0..0xFFFF: {value}"
                )
            values.append(value)
        else:
            values.append(parse_int_field(thr_text, f"ch{channel:02d} 阈值"))
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


# ---------------------------------------------------------------- storage


def effective_output_dir(
    gui_entry: str | None, profile_dir: object
) -> Path | None:
    """Per-type parent directory: GUI entry > profile dir > None (default leaf)."""
    if gui_entry and gui_entry.strip():
        return Path(gui_entry.strip())
    if profile_dir is not None:
        return Path(str(profile_dir))
    return None


def merge_outputs_config(
    profile,
    page: str,
    *,
    raw_enabled: bool,
    text_enabled: bool,
    log_enabled: bool,
    raw_dir: str | None = None,
    text_dir: str | None = None,
    log_dir: str | None = None,
) -> AcquireOutputsConfig:
    """Build capture outputs from GUI switches + storage entries, honoring
    the profile's per-type directories and text parameters.

    Per-type parent directory resolution:
    GUI entry > profile outputs.<type>.dir > default leaf inside the run dir.
    """
    configured = profile.defaults.get(f"acquire_{page}")
    outputs = resolve_outputs_config(
        acquire_defaults=configured if isinstance(configured, dict) else {},
        default_log_enabled=page == "multi",
    )
    return AcquireOutputsConfig(
        raw=OutputTargetConfig(
            enabled=raw_enabled,
            dir=effective_output_dir(raw_dir, outputs.raw.dir),
        ),
        json=OutputTargetConfig(enabled=False),
        text=TextOutputConfig(
            enabled=text_enabled,
            dir=effective_output_dir(text_dir, outputs.text.dir),
            max_events_per_file=outputs.text.max_events_per_file,
            waveform_layout=outputs.text.waveform_layout,
        ),
        log=OutputTargetConfig(
            enabled=log_enabled,
            dir=effective_output_dir(log_dir, outputs.log.dir),
        ),
    )


# ---------------------------------------------------------------- calibration


def format_tcm_link_calibration(result) -> str:
    """Plain-text rendering of a TCM link calibration result (baseline only)."""
    calibration = result.calibration
    lines = [
        f"===== TCM Link Calibration: {calibration.device_name} =====",
        f"frames: {calibration.frames}  duration: {calibration.duration_s:.1f}s",
        f"ch | samples | baseline | sigma | dir | peak",
    ]
    for channel in calibration.channels:
        lines.append(
            f"{channel.channel:02d} | {channel.samples:7d} | {channel.baseline:8d} | "
            f"{channel.sigma:5.1f} | {channel.direction:+3d} | {channel.peak_dev:4d}"
        )
    lines.append(f"original send_mode restored: {result.original_send_mode}")
    lines.append(
        "已把 基线 ± 偏移量 填入各通道阈值（按当前极性：正极性=基线+偏移，"
        "负极性=基线-偏移）。确认后点「应用全部并回读验证」。"
    )
    return "\n".join(lines)


def calibration_to_form_values(
    calibration, offset: int, polarity_mask: int
) -> list[str]:
    """Threshold strings per channel: baseline +/- the user offset,
    direction decided by the polarity mask bits."""
    thresholds = [
        str(suggested_threshold_for(channel, offset, polarity_mask))
        for channel in calibration.channels
    ]
    return thresholds


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
            ("storage_mode", getattr(result, "storage_mode", "aggregate")),
            ("aggregate_output", getattr(result, "aggregate_output_path", None)),
            ("aggregate_index", getattr(result, "aggregate_index_path", None)),
            ("rate_csv", getattr(result, "rate_csv_path", None)),
            ("run_meta", getattr(result, "run_meta_path", None)),
            (
                "rate_interval_s",
                getattr(result, "rate_interval_s", 1.0),
            ),
            ("run_output_dir", result.run_output_dir),
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
    coincidence_enabled: bool = False,
    grp_count: int = 0,
    coinc_window: int = 0,
    coinc_timeout_sticky: bool = False,
    collected_count: int = 0,
    collecting: bool = False,
    grp_ok: int = 0,
    group_masks: tuple[int, int, int, int] = (0, 0, 0, 0),
    group_n: tuple[int, int, int, int] = (0, 0, 0, 0),
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
        ("coincidence_enabled", coincidence_enabled),
        ("coinc_groups", grp_count if grp_count else "default 2"),
        (
            "coinc_window",
            f"{coinc_window} x 50ns = {coinc_window * 50e-3:.1f} us"
            if coinc_window
            else "default 4 (200ns)",
        ),
    ]
    if coincidence_enabled:
        for index in range(4):
            rows.append((f"grp{index}_mask", f"0x{group_masks[index]:02X}"))
        rows.append(("grp_n", ",".join(str(value) for value in group_n)))
        rows.append(("collecting", collecting))
        rows.append(("grp_ok", f"0x{grp_ok:01X}"))
        rows.append(("coinc_timeout_sticky", coinc_timeout_sticky))
        rows.append(("collected_count", collected_count))
    rows.append(("profile", source_profile))
    return format_fields(f"TCM Trigger Config: {tcm.name}", rows)