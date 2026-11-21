from rich.console import Console
from rich.table import Table

from daq_cli.application.acquire_service import MultiAcquireResult, SingleAcquireResult
from daq_cli.application.board_service import (
    BoardConfigResult,
    BoardConfigSummaryResult,
    BoardInfoResult,
    RegisterReadResult,
    SendModeSetResult,
    TcmLinkCalibrationResult,
    TcmLinkConfigReadResult,
    TcmLinkConfigWriteResult,
    TcpMode2ConfigReadResult,
    TriggerConfigReadResult,
)
from daq_cli.infrastructure.tcm_link_calibration import suggested_threshold_for
from daq_cli.application.tcm_service import (
    TcmTriggerConfigReadResult,
    TcmTriggerConfigWriteResult,
)
from daq_cli.application.telemetry_service import BoardSysmonResult

console = Console()


def print_board_info(info: BoardInfoResult) -> None:
    table = Table(title=f"Board Info: {info.device.name}")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("name", info.device.name)
    table.add_row("ip", info.device.ip)
    table.add_row("rbcp_port", str(info.device.rbcp_port))
    table.add_row("tcp_port", str(info.device.tcp_port))
    table.add_row("board_id", str(info.device.board_id))
    table.add_row("role", info.device.role or "-")
    table.add_row("profile", str(info.source_profile))
    console.print(table)


def print_board_sysmon(result: BoardSysmonResult) -> None:
    table = Table(title=f"Board Sysmon: {result.device.name}")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("temperature_c", f"{result.snapshot.temperature_c:.2f}")
    table.add_row("vccint_v", f"{result.snapshot.vccint_v:.3f}")
    table.add_row("vccaux_v", f"{result.snapshot.vccaux_v:.3f}")
    table.add_row("vccbram_v", f"{result.snapshot.vccbram_v:.3f}")
    table.add_row("profile", str(result.source_profile))

    console.print(table)


def print_board_config_result(result: BoardConfigResult) -> None:
    status = "OK" if result.success else "FAILED"
    table = Table(title=f"Board Config: {result.device.name}")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("status", status)
    table.add_row("adc_enabled", str(result.adc_enabled))
    table.add_row("clock_enabled", str(result.clock_enabled))
    table.add_row("trigger_enabled", str(result.trigger_enabled))
    table.add_row("tcp_mode2_enabled", str(result.tcp_mode2_enabled))
    table.add_row(
        "trigger_thresholds",
        ", ".join(str(value) for value in result.trigger_thresholds),
    )
    table.add_row("trigger_mode", str(result.trigger_mode))
    table.add_row("trigger_position", str(result.trigger_position))
    table.add_row("timestamp_clean_enabled", str(result.timestamp_clean_enabled))
    table.add_row("ext_trigger_enabled", str(result.ext_trigger_enabled))
    table.add_row(
        "requested_send_mode",
        "-" if result.requested_send_mode is None else str(result.requested_send_mode),
    )
    table.add_row(
        "effective_send_mode",
        "-" if result.effective_send_mode is None else str(result.effective_send_mode),
    )
    table.add_row("send_start_delay_us", f"{result.send_start_delay_us}")
    table.add_row("profile", str(result.source_profile))
    console.print(table)

    if result.log_output.strip():
        console.print(result.log_output.rstrip())


def print_single_acquire_result(result: SingleAcquireResult) -> None:
    table = Table(title=f"Single Acquire: {result.device.name}")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("requested_events", str(result.requested_events))
    table.add_row("captured_events", str(result.captured_events or "-"))
    table.add_row("send_mode", str(result.send_mode))
    table.add_row(
        "storage_mode", str(getattr(result, "storage_mode", "legacy"))
    )
    table.add_row(
        "aggregate_output",
        str(getattr(result, "aggregate_output_path", None) or "-"),
    )
    table.add_row(
        "aggregate_index",
        str(getattr(result, "aggregate_index_path", None) or "-"),
    )
    table.add_row(
        "rate_csv", str(getattr(result, "rate_csv_path", None) or "-")
    )
    table.add_row(
        "run_meta", str(getattr(result, "run_meta_path", None) or "-")
    )
    table.add_row(
        "rate_interval_s", f"{getattr(result, 'rate_interval_s', 1.0)}"
    )
    table.add_row("decode_enabled", str(result.decode_enabled))
    table.add_row("raw_output_dir", str(getattr(result, "raw_output_dir", None) or "-"))
    table.add_row(
        "json_output_enabled",
        str(getattr(result, "json_output_enabled", result.decode_enabled)),
    )
    table.add_row(
        "json_output_dir",
        str(getattr(result, "json_output_dir", result.decoded_output_dir) or "-"),
    )
    table.add_row(
        "decoded_output_dir",
        str(result.decoded_output_dir or "-"),
    )
    table.add_row(
        "decoded_events",
        "-" if result.decoded_events is None else str(result.decoded_events),
    )
    table.add_row("decode_errors", str(result.decode_errors))
    table.add_row(
        "log_output_path",
        str(getattr(result, "log_output_path", None) or "-"),
    )
    table.add_row("text_output_enabled", str(getattr(result, "text_output_enabled", False)))
    table.add_row("text_output_dir", str(getattr(result, "text_output_dir", None) or "-"))
    table.add_row("text_output_events", str(getattr(result, "text_output_events", 0)))
    table.add_row("text_output_files", str(getattr(result, "text_output_files", 0)))
    table.add_row("watch_enabled", str(result.watch_enabled))
    table.add_row(
        "watch_every",
        "-" if result.watch_every is None else str(result.watch_every),
    )
    table.add_row("watched_frames", str(result.watched_frames))
    table.add_row("timeout_s", f"{result.tcp_timeout_s}")
    table.add_row("output_base_dir", str(result.output_base_dir))
    table.add_row("run_output_dir", str(result.run_output_dir or "-"))
    table.add_row("profile", str(result.source_profile))
    console.print(table)

    if result.log_output.strip():
        console.print(result.log_output.rstrip())


def print_multi_acquire_result(result: MultiAcquireResult) -> None:
    table = Table(title=f"Multi Acquire: {result.group.name}")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("devices", ", ".join(device.name for device in result.devices))
    table.add_row("aggregation_key", result.aggregation_key)
    table.add_row(
        "timestamp_match_window_ticks",
        str(result.timestamp_match_window_ticks),
    )
    table.add_row("timeout_s", f"{result.tcp_timeout_s}")
    table.add_row("allow_start_without_ack", str(result.allow_start_without_ack))
    table.add_row("decode_enabled", str(result.decode_enabled))
    table.add_row("raw_output_dir", str(getattr(result, "raw_output_dir", None) or "-"))
    table.add_row(
        "json_output_enabled",
        str(getattr(result, "json_output_enabled", result.decode_enabled)),
    )
    table.add_row(
        "json_output_dir",
        str(getattr(result, "json_output_dir", result.decoded_output_dir) or "-"),
    )
    table.add_row("decoded_output_dir", str(result.decoded_output_dir or "-"))
    table.add_row("decoded_complete_events", str(result.decoded_complete_events))
    table.add_row("decoded_partial_events", str(result.decoded_partial_events))
    table.add_row("decode_errors", str(result.decode_errors))
    table.add_row("text_output_enabled", str(getattr(result, "text_output_enabled", False)))
    table.add_row("text_output_dir", str(getattr(result, "text_output_dir", None) or "-"))
    table.add_row(
        "text_output_complete_events",
        str(getattr(result, "text_output_complete_events", 0)),
    )
    table.add_row(
        "text_output_partial_events",
        str(getattr(result, "text_output_partial_events", 0)),
    )
    table.add_row("text_output_files", str(getattr(result, "text_output_files", 0)))
    table.add_row("watch_waveforms", str(result.watch_waveforms))
    table.add_row(
        "watch_every",
        "-" if result.watch_every is None else str(result.watch_every),
    )
    table.add_row(
        "stop_capture_on_watch_close",
        str(result.stop_capture_on_watch_close),
    )
    table.add_row("watched_frames", str(result.watched_frames))
    table.add_row("status", result.status or "-")
    table.add_row("output_base_dir", str(result.output_base_dir))
    table.add_row("run_output_dir", str(result.run_output_dir or "-"))
    table.add_row("config_path", str(result.config_path))
    table.add_row("meta_path", str(result.meta_path or "-"))
    table.add_row("log_path", str(result.log_path or "-"))
    table.add_row("log_output_dir", str(getattr(result, "log_output_dir", None) or "-"))
    table.add_row("profile", str(result.source_profile))
    console.print(table)


def print_register_read_result(result: RegisterReadResult) -> None:
    table = Table(title=f"Register Read: {result.device.name}")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    hex_bytes = " ".join(f"{byte:02X}" for byte in result.data)
    table.add_row("address", f"0x{result.address:08X}")
    table.add_row("length", str(len(result.data)))
    table.add_row("hex", hex_bytes or "-")
    table.add_row("profile", str(result.source_profile))
    console.print(table)


def print_trigger_config_read_result(result: TriggerConfigReadResult) -> None:
    table = Table(title=f"Trigger Config: {result.device.name}")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("trigger_mode", str(result.trigger_mode))
    table.add_row("trigger_position", str(result.trigger_position))
    table.add_row("thresholds", ", ".join(str(value) for value in result.thresholds))
    table.add_row("send_start_delay_reg", str(result.send_start_delay))
    table.add_row("timestamp_clean_enabled", str(result.timestamp_clean_enabled))
    table.add_row("ext_trigger_enabled", str(result.ext_trigger_enabled))
    table.add_row("profile", str(result.source_profile))
    console.print(table)


def print_tcp_mode2_config_read_result(result: TcpMode2ConfigReadResult) -> None:
    table = Table(title=f"TCP Mode-2 Config: {result.device.name}")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("send_mode", str(result.send_mode))
    table.add_row("integration_pre_samples", str(result.integration_pre_samples))
    table.add_row("integration_post_samples", str(result.integration_post_samples))
    table.add_row(
        "hit_thresholds",
        ", ".join(str(value) for value in result.hit_thresholds),
    )
    table.add_row(
        "hit_polarities",
        ", ".join(str(value) for value in result.hit_polarities),
    )
    table.add_row("profile", str(result.source_profile))
    console.print(table)


def _tcm_link_table(result: TcmLinkConfigReadResult) -> Table:
    table = Table(title=f"TCM Link Config: {result.device.name}")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    enabled_channels = [
        channel
        for channel in range(16)
        if (result.mask >> channel) & 0x1
    ]
    table.add_row("mask", f"0x{result.mask:04X} ({len(enabled_channels)} ch)")
    table.add_row("polarity", f"0x{result.polarity:04X}")
    table.add_row(
        "debounce",
        f"{result.debounce} x 5ns = {result.debounce * 5e-3:.1f} us",
    )
    table.add_row("pulse_width", f"{result.pulse_width} x 5ns = {result.pulse_width * 5} ns")
    table.add_row("enable", str(result.enable))
    if enabled_channels:
        for channel in enabled_channels:
            polarity = "neg" if (result.polarity >> channel) & 0x1 else "pos"
            table.add_row(
                f"thr ch{channel:02d}",
                f"{result.thresholds[channel]} ({polarity})",
            )
    table.add_row("profile", str(result.source_profile))
    return table


def print_tcm_link_config_read_result(result: TcmLinkConfigReadResult) -> None:
    console.print(_tcm_link_table(result))


def print_tcm_link_config_write_result(result: TcmLinkConfigWriteResult) -> None:
    table = Table(title=f"TCM Link Config Written: {result.device.name}")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    enabled_channels = [
        channel
        for channel in range(16)
        if (result.mask >> channel) & 0x1
    ]
    table.add_row("mask", f"0x{result.mask:04X} ({len(enabled_channels)} ch)")
    table.add_row("polarity", f"0x{result.polarity:04X}")
    table.add_row(
        "debounce",
        f"{result.debounce} x 5ns = {result.debounce * 5e-3:.1f} us",
    )
    table.add_row("pulse_width", f"{result.pulse_width} x 5ns = {result.pulse_width * 5} ns")
    table.add_row("enable", str(result.enable))
    for channel in enabled_channels:
        polarity = "neg" if (result.polarity >> channel) & 0x1 else "pos"
        table.add_row(
            f"thr ch{channel:02d}",
            f"{result.thresholds[channel]} ({polarity})",
        )
    table.add_row("profile", str(result.source_profile))
    console.print(table)


def _tcm_trigger_table(result: TcmTriggerConfigReadResult) -> Table:
    table = Table(title=f"TCM Trigger Config: {result.tcm.name}")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    enabled_channels = [
        channel
        for channel in range(8)
        if (result.mask >> channel) & 0x1
    ]
    table.add_row("tcm_ip", f"{result.tcm.ip}:{result.tcm.rbcp_port}")
    table.add_row("enable", str(result.enable))
    table.add_row("mask", f"0x{result.mask:02X} ({len(enabled_channels)} ch)")
    table.add_row(
        "pulse_width",
        f"{result.pulse_width} x 50ns = {result.pulse_width * 50e-3:.1f} us",
    )
    table.add_row(
        "debounce",
        f"{result.debounce} x 50ns = {result.debounce * 50e-3:.1f} us",
    )
    table.add_row("trig_sticky", str(result.trig_sticky))
    table.add_row("pending", str(result.pending))
    table.add_row("wide_pulse_active", str(result.wide_pulse_active))
    if result.last_trigger_channels:
        channels = [
            str(channel)
            for channel in range(8)
            if (result.last_trigger_channels >> channel) & 0x1
        ]
        table.add_row("last_trigger_channels", ",".join(channels))
    # coincidence (v3)
    table.add_row("coincidence_enabled", str(result.coincidence_enabled))
    table.add_row(
        "coinc_groups",
        str(result.grp_count) if result.grp_count else "default 2",
    )
    table.add_row(
        "coinc_window",
        f"{result.coinc_window} x 50ns = {result.coinc_window * 50e-3:.1f} us"
        if result.coinc_window
        else "default 4 (200ns)",
    )
    if result.coincidence_enabled:
        for index in range(4):
            table.add_row(
                f"grp{index}_mask",
                f"0x{result.group_masks[index]:02X}",
            )
        table.add_row(
            "grp_n",
            ",".join(str(value) for value in result.group_n),
        )
        table.add_row("collecting", str(result.collecting))
        table.add_row("grp_ok", f"0x{result.grp_ok:01X}")
        table.add_row("coinc_timeout_sticky", str(result.coinc_timeout_sticky))
        table.add_row("collected_count", str(result.collected_count))
    table.add_row("profile", str(result.source_profile))
    return table


def print_tcm_trigger_config_read_result(result: TcmTriggerConfigReadResult) -> None:
    console.print(_tcm_trigger_table(result))


def print_tcm_trigger_config_write_result(
    result: TcmTriggerConfigWriteResult,
) -> None:
    table = Table(title=f"TCM Trigger Config Written: {result.tcm.name}")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    enabled_channels = [
        channel
        for channel in range(8)
        if (result.mask >> channel) & 0x1
    ]
    table.add_row("tcm_ip", f"{result.tcm.ip}:{result.tcm.rbcp_port}")
    table.add_row("enable", str(result.enable))
    table.add_row("mask", f"0x{result.mask:02X} ({len(enabled_channels)} ch)")
    table.add_row(
        "pulse_width",
        f"{result.pulse_width} x 50ns = {result.pulse_width * 50e-3:.1f} us",
    )
    table.add_row(
        "debounce",
        f"{result.debounce} x 50ns = {result.debounce * 50e-3:.1f} us",
    )
    table.add_row("profile", str(result.source_profile))
    console.print(table)


def print_tcm_link_calibration_result(
    result: TcmLinkCalibrationResult,
    offset: int = 100,
    polarity_mask: int = 0,
) -> None:
    calibration = result.calibration
    table = Table(
        title=f"TCM Link Calibration: {result.device.name} "
        f"({calibration.frames} frames / {calibration.duration_s:.1f}s)"
    )
    table.add_column("ch", style="cyan", no_wrap=True)
    table.add_column("samples", justify="right")
    table.add_column("baseline", justify="right")
    table.add_column("sigma", justify="right")
    table.add_column("dir", justify="right")
    table.add_column("peak", justify="right")
    table.add_column(f"thr (base±{offset})", justify="right")
    for channel in calibration.channels:
        suggested = suggested_threshold_for(channel, offset, polarity_mask)
        table.add_row(
            f"ch{channel.channel:02d}",
            str(channel.samples),
            str(channel.baseline),
            f"{channel.sigma:.1f}",
            f"{channel.direction:+d}",
            str(channel.peak_dev),
            str(suggested),
        )
    console.print(table)
    console.print(
        f"original send_mode restored: {result.original_send_mode}\n"
        f"suggested threshold = baseline ± offset(={offset}) by polarity mask "
        f"0x{polarity_mask:04X} (1 = neg → baseline-offset)\n"
        f"apply with: daq board tcm-link-config {result.device.name} "
        f"--thr <16 values> --polarity 0x{polarity_mask:04X}"
    )


def print_send_mode_set_result(result: SendModeSetResult) -> None:
    table = Table(title=f"Send Mode Set: {result.device.name}")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("requested_send_mode", str(result.requested_send_mode))
    table.add_row("effective_send_mode", str(result.effective_send_mode))
    table.add_row("profile", str(result.source_profile))
    console.print(table)


def print_board_config_summary_result(result: BoardConfigSummaryResult) -> None:
    trigger_table = Table(title=f"Config Summary: {result.device.name} / Trigger")
    trigger_table.add_column("Field", style="cyan", no_wrap=True)
    trigger_table.add_column("Value", style="white")
    trigger_table.add_row("trigger_mode", str(result.trigger.trigger_mode))
    trigger_table.add_row("trigger_position", str(result.trigger.trigger_position))
    trigger_table.add_row(
        "thresholds",
        ", ".join(str(value) for value in result.trigger.thresholds),
    )
    trigger_table.add_row(
        "send_start_delay_reg", str(result.trigger.send_start_delay)
    )
    trigger_table.add_row(
        "timestamp_clean_enabled", str(result.trigger.timestamp_clean_enabled)
    )
    trigger_table.add_row(
        "ext_trigger_enabled", str(result.trigger.ext_trigger_enabled)
    )

    tcp_table = Table(title=f"Config Summary: {result.device.name} / TCP Mode-2")
    tcp_table.add_column("Field", style="cyan", no_wrap=True)
    tcp_table.add_column("Value", style="white")
    tcp_table.add_row("send_mode", str(result.tcp_mode2.send_mode))
    tcp_table.add_row(
        "integration_pre_samples", str(result.tcp_mode2.integration_pre_samples)
    )
    tcp_table.add_row(
        "integration_post_samples", str(result.tcp_mode2.integration_post_samples)
    )
    tcp_table.add_row(
        "hit_thresholds",
        ", ".join(str(value) for value in result.tcp_mode2.hit_thresholds),
    )
    tcp_table.add_row(
        "hit_polarities",
        ", ".join(str(value) for value in result.tcp_mode2.hit_polarities),
    )
    tcp_table.add_row("profile", str(result.source_profile))

    console.print(trigger_table)
    console.print(tcp_table)
