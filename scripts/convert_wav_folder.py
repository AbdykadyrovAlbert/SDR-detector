from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from convert_wav_iq_to_bin import convert_wav_to_int16_iq


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "data" / "converted" / "ordinary_signals"


def extract_center_freq_hz(path: Path) -> int | None:
    """Достаёт центральную частоту из имён SDRuno вида *_129535kHz.wav."""

    match = re.search(r"_(\d+)kHz", path.name, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1)) * 1000


def category_from_path(root: Path, wav_path: Path) -> str:
    rel = wav_path.relative_to(root)
    return rel.parts[0] if len(rel.parts) > 1 else "misc"


def output_path_for(root: Path, output_dir: Path, wav_path: Path) -> Path:
    rel = wav_path.relative_to(root)
    if len(rel.parts) == 1:
        return output_dir / "misc" / f"{wav_path.stem}.bin"
    return output_dir / rel.with_suffix(".bin")


def main() -> int:
    parser = argparse.ArgumentParser(description="Пакетная конвертация всех WAV I/Q файлов из папки")
    parser.add_argument("input_dir", help="Папка, где искать WAV-файлы")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Папка для .bin файлов. По умолчанию data/converted/ordinary_signals",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    if not input_dir.exists():
        raise FileNotFoundError(f"Папка не найдена: {input_dir}")

    wav_files = sorted(input_dir.rglob("*.wav"))
    if not wav_files:
        print("WAV-файлы не найдены.")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = output_dir / "metadata.csv"

    rows = []
    for index, wav_path in enumerate(wav_files, start=1):
        out_path = output_path_for(input_dir, output_dir, wav_path)
        print(f"[{index}/{len(wav_files)}] {wav_path}")
        info = convert_wav_to_int16_iq(wav_path, out_path)
        center_freq_hz = extract_center_freq_hz(wav_path)

        row = {
            "category": category_from_path(input_dir, wav_path),
            "input_wav": str(wav_path),
            "output_bin": str(out_path),
            "format": "int16_iq",
            "sample_rate": info["sample_rate"],
            "center_freq_hz": center_freq_hz if center_freq_hz is not None else "",
            "duration_s": f"{info['duration_s']:.6f}",
            "frames": info["frames"],
            "bytes_written": info["bytes_written"],
        }
        rows.append(row)
        print(f"    -> {out_path}")
        if center_freq_hz is not None:
            print(f"    sample_rate={info['sample_rate']}, center_freq={center_freq_hz}")
        else:
            print(f"    sample_rate={info['sample_rate']}, center_freq не найден в имени")

    with metadata_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print("")
    print("Готово.")
    print(f"Сконвертировано WAV-файлов: {len(rows)}")
    print(f"Папка с .bin: {output_dir}")
    print(f"Таблица параметров: {metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
