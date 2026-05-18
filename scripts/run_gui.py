from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    return subprocess.call([sys.executable, str(PROJECT_DIR / "gui.py")], cwd=PROJECT_DIR)


if __name__ == "__main__":
    raise SystemExit(main())

