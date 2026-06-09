from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from daq_cli.infrastructure.multi_board_decode import (
    MultiBoardAggregatedEventReader,
    build_board_context,
    event_to_json_dict,
    load_multi_run_metadata,
)


@dataclass(slots=True)
class MultiDecodeRunResult:
    run_dir: Path
    output_dir: Path
    decoded_complete_events: int
    decoded_partial_events: int
    decode_errors: int


class MultiDecodeService:
    def decode_multi_run(
        self,
        run_dir: Path | str,
        output_dir: Path | None = None,
        overwrite: bool = False,
    ) -> MultiDecodeRunResult:
        run_path = Path(run_dir)
        run_meta = load_multi_run_metadata(run_path)
        board_context = build_board_context(run_meta)
        aggregation_key = str(run_meta.get("aggregation_key", "unknown"))
        target_root = output_dir or (run_path / "decoded")
        complete_dir = target_root / "complete"
        partial_dir = target_root / "partial"
        complete_dir.mkdir(parents=True, exist_ok=True)
        partial_dir.mkdir(parents=True, exist_ok=True)

        decoded_complete_events = 0
        decoded_partial_events = 0
        decode_errors = 0

        for event_kind, input_path, output_dir_path in (
            ("complete", run_path / "complete_events.dat", complete_dir),
            ("partial", run_path / "partial_events.dat", partial_dir),
        ):
            if not input_path.is_file():
                continue
            reader = MultiBoardAggregatedEventReader(input_path, event_kind=event_kind)
            for event in reader.iter_events():
                output_path = output_dir_path / f"event_{event.aggregate_seq:05d}.json"
                self._ensure_writable_output(output_path, overwrite=overwrite)
                try:
                    payload = event_to_json_dict(
                        event=event,
                        aggregation_key=aggregation_key,
                        board_context=board_context,
                    )
                except Exception:
                    decode_errors += 1
                    continue
                output_path.write_text(
                    json.dumps(payload, indent=2),
                    encoding="utf-8",
                )
                if event_kind == "complete":
                    decoded_complete_events += 1
                else:
                    decoded_partial_events += 1

        return MultiDecodeRunResult(
            run_dir=run_path,
            output_dir=target_root,
            decoded_complete_events=decoded_complete_events,
            decoded_partial_events=decoded_partial_events,
            decode_errors=decode_errors,
        )

    def _ensure_writable_output(self, output_path: Path, overwrite: bool) -> None:
        if output_path.exists() and not overwrite:
            raise ValueError(
                f"Decoded output '{output_path}' already exists. Pass --overwrite to replace it."
            )
