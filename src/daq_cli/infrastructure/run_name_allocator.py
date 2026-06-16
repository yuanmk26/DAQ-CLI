from __future__ import annotations

import re
from pathlib import Path


def allocate_next_run_dir(base_dir: Path, prefix: str) -> Path:
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)$")
    max_suffix = 0
    for path in base_dir.iterdir():
        if not path.is_dir():
            continue
        match = pattern.match(path.name)
        if match is None:
            continue
        max_suffix = max(max_suffix, int(match.group(1)))

    next_suffix = max_suffix + 1
    while True:
        run_dir = base_dir / f"{prefix}_{next_suffix:05d}"
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
            return run_dir
        except FileExistsError:
            next_suffix += 1
