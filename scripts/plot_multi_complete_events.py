"""Plot complete multi-board events, one 16-channel figure per event and board."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from daq_cli.infrastructure.multi_board_decode import (  # noqa: E402
    EVENT_FLAG_COMPLETE,
    MultiBoardAggregatedEventReader,
    build_board_context,
    build_board_packet,
    load_multi_run_metadata,
)
from daq_cli.infrastructure.tcp_sent_decode import decode_tcp_sent_packet  # noqa: E402


def plot_events(run_dir: Path, event_ids: list[int], output_dir: Path) -> list[Path]:
    metadata = load_multi_run_metadata(run_dir)
    board_context = build_board_context(metadata)
    reader = MultiBoardAggregatedEventReader(
        run_dir / "complete_events.dat", event_kind="complete"
    )
    selected = {event.aggregate_seq: event for event in reader.iter_events()
                if event.aggregate_seq in event_ids}
    missing = set(event_ids) - selected.keys()
    if missing:
        raise ValueError(f"Complete event IDs not found: {sorted(missing)}")

    board_ids = sorted(board_context)
    data: dict[int, dict[int, list[list[int]]]] = {board_id: {} for board_id in board_ids}
    for event_id in event_ids:
        event = selected[event_id]
        present = {board.board_id: board for board in event.boards}
        if not event.status_flags & EVENT_FLAG_COMPLETE or set(board_ids) != set(present):
            raise ValueError(f"Event {event_id} does not contain every expected board")
        for board_id in board_ids:
            decoded = decode_tcp_sent_packet(
                build_board_packet(present[board_id]),
                source_file=run_dir / "complete_events.dat",
                adc_length=int(metadata["adc_length"]),
            )
            if any(channel is None for channel in decoded.channels):
                raise ValueError(f"Event {event_id}, board {board_id} lacks channels")
            data[board_id][event_id] = decoded.channels  # type: ignore[assignment]

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for event_id in event_ids:
        for board_id in board_ids:
            name = str(board_context[board_id]["board_name"])
            fig, axes = plt.subplots(4, 4, figsize=(18, 12), sharex=True)
            for channel_id, ax in enumerate(axes.flat):
                samples = data[board_id][event_id][channel_id]
                ax.plot(samples, color="#1565c0", linewidth=0.8)
                ax.set_title(f"CH {channel_id:02d}", loc="left", fontsize=10)
                ax.grid(alpha=0.2)
                ax.tick_params(labelsize=8)
                if channel_id // 4 == 3:
                    ax.set_xlabel("Sample index")
                if channel_id % 4 == 0:
                    ax.set_ylabel("ADC count")
            fig.suptitle(
                f"Complete event ID {event_id} | {name} (board {board_id})",
                fontsize=16,
            )
            fig.tight_layout(rect=(0, 0, 1, 0.96))
            output = output_dir / f"event_{event_id:03d}_board_{board_id:02d}_{name}.png"
            fig.savefig(output, dpi=160)
            plt.close(fig)
            outputs.append(output)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--event-ids", nargs="+", type=int, default=[1, 2, 3],
                        metavar="ID")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if len(set(args.event_ids)) != len(args.event_ids):
        parser.error("--event-ids requires distinct aggregate event IDs")
    output_dir = args.output_dir or args.run_dir / "plots"
    for path in plot_events(args.run_dir, args.event_ids, output_dir):
        print(path)


if __name__ == "__main__":
    main()
