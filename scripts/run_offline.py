from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    iq_path = PROJECT_DIR / "data" / "test_bursty_cf32.iq"
    if not iq_path.exists():
        print("Тестовый файл не найден. Сначала выполните:")
        print("python scripts/generate_test_iq.py")
        return 1

    cmd = [
        sys.executable,
        str(PROJECT_DIR / "main.py"),
        "--offline",
        str(iq_path),
        "--format",
        "complex64",
        "--sample-rate",
        "2000000",
        "--center-freq",
        "2440000000",
        "--fft-size",
        "4096",
        "--threshold-db",
        "12",
        "--confirm-frames",
        "3",
        "--max-seconds",
        "0.30",
        "--plot",
    ]
    return subprocess.call(cmd, cwd=PROJECT_DIR)


if __name__ == "__main__":
    raise SystemExit(main())

