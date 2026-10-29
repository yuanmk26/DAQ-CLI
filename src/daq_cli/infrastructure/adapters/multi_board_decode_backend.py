"""Tail-following decode backend for aggregated multi-board runs.

A spawn-process worker that watches ``complete_events.dat`` /
``partial_events.dat`` while the capture is still writing, decoding each event
to JSON and/or text as soon as it lands. It is a pure consumer of the aggregated
files, so it works identically for the native and vendored writers.
"""

from __future__ import annotations

import json
import queue
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from daq_cli.infrastructure.multi_board_decode import (
    MultiBoardDecodeError,
    MultiBoardTailReadState,
    build_board_context,
    event_to_json_dict,
    load_multi_run_metadata,
    read_available_tail_events,
)
from daq_cli.infrastructure.text_event_writer import (
    SegmentedTextEventWriter,
    format_multi_event_text,
)


@dataclass(slots=True)
class DecodeControlMessage:
    kind: str


@dataclass(slots=True)
class DecodeSummary:
    decoded_complete_events: int
    decoded_partial_events: int
    decode_errors: int
    text_output_complete_events: int = 0
    text_output_partial_events: int = 0
    text_output_files: int = 0


@dataclass(slots=True)
class DecodeDrainResult:
    decoded_complete_events: int = 0
    decoded_partial_events: int = 0
    decode_errors: int = 0
    text_output_complete_events: int = 0
    text_output_partial_events: int = 0
    text_output_files: int = 0


def run_multi_board_decode_backend(
    task_queue: Any,
    result_queue: Any,
    run_output_dir: str,
    decoded_output_dir: str,
    decode_json: bool,
    text_output_dir: str,
    text_output_enabled: bool,
    text_max_events_per_file: int,
    text_waveform_layout: str,
) -> None:
    run_dir = Path(run_output_dir)
    output_dir = Path(decoded_output_dir) if decoded_output_dir else None
    complete_output_dir = output_dir / "complete" if output_dir is not None else None
    partial_output_dir = output_dir / "partial" if output_dir is not None else None
    if complete_output_dir is not None:
        complete_output_dir.mkdir(parents=True, exist_ok=True)
    if partial_output_dir is not None:
        partial_output_dir.mkdir(parents=True, exist_ok=True)
    resolved_text_output_dir = Path(text_output_dir) if text_output_dir else None
    complete_text_writer = (
        SegmentedTextEventWriter(
            output_dir=resolved_text_output_dir / "complete",
            max_events_per_file=text_max_events_per_file,
        )
        if text_output_enabled and resolved_text_output_dir is not None
        else None
    )
    partial_text_writer = (
        SegmentedTextEventWriter(
            output_dir=resolved_text_output_dir / "partial",
            max_events_per_file=text_max_events_per_file,
        )
        if text_output_enabled and resolved_text_output_dir is not None
        else None
    )

    decode_errors = 0
    decoded_complete_events = 0
    decoded_partial_events = 0
    text_output_complete_events = 0
    text_output_partial_events = 0
    capture_finished = False
    board_context: dict[int, dict[str, object]] | None = None
    aggregation_key = "unknown"
    complete_state = MultiBoardTailReadState()
    partial_state = MultiBoardTailReadState()
    complete_input_path = run_dir / "complete_events.dat"
    partial_input_path = run_dir / "partial_events.dat"

    try:
        while True:
            while True:
                try:
                    control = task_queue.get_nowait()
                except queue.Empty:
                    break
                if getattr(control, "kind", None) == "capture_finished":
                    capture_finished = True

            if board_context is None:
                try:
                    run_meta = load_multi_run_metadata(run_dir)
                except Exception:
                    if capture_finished:
                        decode_errors += 1
                        break
                    time.sleep(0.05)
                    continue
                board_context = build_board_context(run_meta)
                aggregation_key = str(run_meta.get("aggregation_key", "unknown"))

            made_progress = False
            try:
                complete_batch = read_available_tail_events(
                    path=complete_input_path,
                    event_kind="complete",
                    state=complete_state,
                )
                complete_state = complete_batch.state
                for event in complete_batch.events:
                    payload = event_to_json_dict(
                        event=event,
                        aggregation_key=aggregation_key,
                        board_context=board_context,
                    )
                    if complete_output_dir is not None and decode_json:
                        output_path = (
                            complete_output_dir / f"event_{event.aggregate_seq:05d}.json"
                        )
                        output_path.write_text(
                            json.dumps(payload, indent=2), encoding="utf-8"
                        )
                        decoded_complete_events += 1
                    if complete_text_writer is not None:
                        complete_text_writer.append_event(format_multi_event_text(payload))
                        text_output_complete_events += 1
                    made_progress = True

                partial_batch = read_available_tail_events(
                    path=partial_input_path,
                    event_kind="partial",
                    state=partial_state,
                )
                partial_state = partial_batch.state
                for event in partial_batch.events:
                    payload = event_to_json_dict(
                        event=event,
                        aggregation_key=aggregation_key,
                        board_context=board_context,
                    )
                    if partial_output_dir is not None and decode_json:
                        output_path = (
                            partial_output_dir / f"event_{event.aggregate_seq:05d}.json"
                        )
                        output_path.write_text(
                            json.dumps(payload, indent=2), encoding="utf-8"
                        )
                        decoded_partial_events += 1
                    if partial_text_writer is not None:
                        partial_text_writer.append_event(format_multi_event_text(payload))
                        text_output_partial_events += 1
                    made_progress = True
            except MultiBoardDecodeError:
                decode_errors += 1
                break
            except Exception:
                decode_errors += 1
                break

            if capture_finished and not made_progress:
                break
            if not made_progress:
                time.sleep(0.05)
    finally:
        if complete_text_writer is not None:
            complete_text_writer.close()
        if partial_text_writer is not None:
            partial_text_writer.close()
        try:
            result_queue.put(
                DecodeSummary(
                    decoded_complete_events=decoded_complete_events,
                    decoded_partial_events=decoded_partial_events,
                    decode_errors=decode_errors,
                    text_output_complete_events=text_output_complete_events,
                    text_output_partial_events=text_output_partial_events,
                    text_output_files=(
                        (
                            complete_text_writer.stats.files_created
                            if complete_text_writer is not None
                            else 0
                        )
                        + (
                            partial_text_writer.stats.files_created
                            if partial_text_writer is not None
                            else 0
                        )
                    ),
                )
            )
        except Exception:
            pass


__all__ = [
    "DecodeControlMessage",
    "DecodeDrainResult",
    "DecodeSummary",
    "run_multi_board_decode_backend",
]
