from __future__ import annotations

from pathlib import Path
from typing import Dict


def create_test_output_dirs(base_dir: Path, root_name: str = "outputs") -> Dict[str, object]:
    root = base_dir / root_name
    root.mkdir(parents=True, exist_ok=True)
    max_idx = 0
    for entry in root.iterdir():
        if entry.is_dir() and entry.name.startswith("test_"):
            s = entry.name[5:]
            if s.isdigit():
                max_idx = max(max_idx, int(s))
    idx = max_idx + 1
    run_dir = root / f"test_{idx:03d}"
    plots_dir = run_dir / "plots"
    reports_dir = run_dir / "reports"
    plots_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    return {"run_index": idx, "run_dir": run_dir, "plots_dir": plots_dir, "reports_dir": reports_dir}
