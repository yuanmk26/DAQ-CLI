from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from daq_cli.infrastructure.tcp_sent_decode import (
    ADC_LENGTH,
    DecodedTcpSentEvent,
    decode_tcp_sent_file,
    load_capture_info,
    write_decoded_event_json,
)


@dataclass(slots=True)
class DecodeEventResult:
    input_file: Path
    output_file: Path
    send_mode: int
    raw_packet_bytes: int


@dataclass(slots=True)
class DecodeRunResult:
    run_dir: Path
    output_dir: Path
    success_count: int
    failure_count: int
    send_mode: int | None
    decoded_files: list[Path]


class DecodeService:
    def decode_event(
        self,
        event_file: Path | str,
        output_dir: Path | None = None,
        overwrite: bool = False,
    ) -> DecodeEventResult:
        event_path = Path(event_file)
        metadata = self._load_context_metadata_for_event(event_path)
        expected_send_mode = _get_optional_int(metadata, "send_mode")
        adc_length = _get_optional_int(metadata, "adc_length") or ADC_LENGTH
        event = decode_tcp_sent_file(
            event_path,
            expected_send_mode=expected_send_mode,
            adc_length=adc_length,
        )
        target_dir = output_dir or self._default_event_output_dir(event_path)
        target_dir.mkdir(parents=True, exist_ok=True)
        output_path = target_dir / f"{event_path.stem}.json"
        self._ensure_writable_output(output_path, overwrite=overwrite)
        write_decoded_event_json(event, output_path)
        return DecodeEventResult(
            input_file=event_path,
            output_file=output_path,
            send_mode=event.send_mode,
            raw_packet_bytes=event.raw_packet_bytes,
        )

    def decode_run(
        self,
        run_dir: Path | str,
        output_dir: Path | None = None,
        overwrite: bool = False,
        limit: int | None = None,
    ) -> DecodeRunResult:
        run_path = Path(run_dir)
        raw_dir = run_path / "raw"
        if not raw_dir.is_dir():
            raise ValueError(f"Run directory '{run_path}' does not contain a raw/ folder.")
        metadata = self._load_context_metadata_for_run(run_path)
        expected_send_mode = _get_optional_int(metadata, "send_mode")
        adc_length = _get_optional_int(metadata, "adc_length") or ADC_LENGTH
        target_dir = output_dir or (run_path / "decoded")
        target_dir.mkdir(parents=True, exist_ok=True)

        event_files = sorted(raw_dir.glob("event_*.bin"))
        if limit is not None:
            event_files = event_files[:limit]
        if not event_files:
            raise ValueError(f"No event_*.bin files found under '{raw_dir}'.")

        decoded_files: list[Path] = []
        success_count = 0
        for event_file in event_files:
            event = decode_tcp_sent_file(
                event_file,
                expected_send_mode=expected_send_mode,
                adc_length=adc_length,
            )
            output_path = target_dir / f"{event_file.stem}.json"
            self._ensure_writable_output(output_path, overwrite=overwrite)
            write_decoded_event_json(event, output_path)
            decoded_files.append(output_path)
            success_count += 1

        return DecodeRunResult(
            run_dir=run_path,
            output_dir=target_dir,
            success_count=success_count,
            failure_count=0,
            send_mode=expected_send_mode,
            decoded_files=decoded_files,
        )

    def _load_context_metadata_for_event(self, event_path: Path) -> dict[str, str]:
        if event_path.parent.name == "raw":
            capture_info = event_path.parent.parent / "capture_info.txt"
            if capture_info.is_file():
                return load_capture_info(capture_info)
        return {}

    def _load_context_metadata_for_run(self, run_path: Path) -> dict[str, str]:
        capture_info = run_path / "capture_info.txt"
        if capture_info.is_file():
            return load_capture_info(capture_info)
        return {}

    def _default_event_output_dir(self, event_path: Path) -> Path:
        if event_path.parent.name == "raw":
            return event_path.parent.parent / "decoded"
        return event_path.parent / "decoded"

    def _ensure_writable_output(self, output_path: Path, overwrite: bool) -> None:
        if output_path.exists() and not overwrite:
            raise ValueError(
                f"Decoded output '{output_path}' already exists. Pass --overwrite to replace it."
            )


def _get_optional_int(values: dict[str, str], key: str) -> int | None:
    raw = values.get(key)
    if raw is None:
        return None
    return int(raw, 10)
