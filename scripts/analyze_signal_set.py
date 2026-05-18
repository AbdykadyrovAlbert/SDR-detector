from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Dict, Iterable, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from core.detector import DetectedEvent, EventDetector
from core.processing import SpectrumProcessor
from core.sources import OfflineIQSource


UAV_DIR = PROJECT_DIR / "data" / "БПЛА сигнал"
ORDINARY_METADATA = PROJECT_DIR / "data" / "converted" / "ordinary_signals" / "metadata.csv"
RESULTS_DIR = PROJECT_DIR / "results" / "analysis"


def load_ordinary_signals() -> List[dict]:
    if not ORDINARY_METADATA.exists():
        return []

    rows = []
    with ORDINARY_METADATA.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            output_bin = Path(row["output_bin"])
            if not output_bin.exists():
                continue
            rows.append(
                {
                    "label": "ordinary",
                    "category": row["category"],
                    "path": output_bin,
                    "format": row["format"],
                    "sample_rate": float(row["sample_rate"]),
                    "center_freq": float(row["center_freq_hz"]) if row["center_freq_hz"] else 0.0,
                }
            )
    return rows


def load_uav_signals() -> List[dict]:
    if not UAV_DIR.exists():
        return []

    rows = []
    for path in sorted(UAV_DIR.glob("*.bin")):
        sample_rate = 200_000_000 if "5G" in path.name.upper() else 120_000_000
        center_freq = 5_800_000_000 if "5G" in path.name.upper() else 2_440_000_000
        rows.append(
            {
                "label": "uav",
                "category": "uav_5g" if "5G" in path.name.upper() else "uav_2g",
                "path": path,
                "format": "int16_iq",
                "sample_rate": float(sample_rate),
                "center_freq": float(center_freq),
            }
        )
    return rows


def file_duration_s(path: Path, iq_format: str, sample_rate: float) -> float:
    bytes_per_sample = 8 if iq_format == "complex64" else 4
    return path.stat().st_size / bytes_per_sample / sample_rate


def analyze_one_signal(signal: dict, fft_size: int, threshold_db: float, confirm_frames: int, max_seconds: float) -> dict:
    source = OfflineIQSource(signal["path"], sample_rate=signal["sample_rate"], iq_format=signal["format"])
    processor = SpectrumProcessor(
        sample_rate=signal["sample_rate"],
        center_freq=signal["center_freq"],
        fft_size=fft_size,
        threshold_db=threshold_db,
    )
    detector = EventDetector(confirm_frames=confirm_frames, merge_gap_hz=processor.bin_width_hz * 2.0)

    total_frames = 0
    frames_with_regions = 0
    total_regions = 0
    noise_values: List[float] = []
    peak_values: List[float] = []
    events: List[DetectedEvent] = []

    for block in source.iter_blocks(fft_size, max_seconds=max_seconds):
        frame = processor.process_block(block.samples, block.start_time_s)
        if frame is None:
            continue

        total_frames += 1
        noise_values.append(frame.noise_floor_db)
        total_regions += len(frame.regions)
        if frame.regions:
            frames_with_regions += 1
            peak_values.extend(region.peak_power_db for region in frame.regions)

        new_events = detector.update(frame)
        events.extend(new_events)

    events.extend(detector.flush())
    analyzed_seconds = min(max_seconds, file_duration_s(signal["path"], signal["format"], signal["sample_rate"]))

    durations = [event.duration_s for event in events]
    bandwidths = [event.bandwidth_hz for event in events]
    event_peaks = [event.peak_power_db for event in events]
    event_means = [event.mean_power_db for event in events]
    centers = [event.center_freq_hz for event in events]
    occupied_time = sum(durations)
    freq_span = max(centers) - min(centers) if len(centers) >= 2 else 0.0

    return {
        "label": signal["label"],
        "category": signal["category"],
        "file": signal["path"].name,
        "path": str(signal["path"]),
        "format": signal["format"],
        "sample_rate": signal["sample_rate"],
        "center_freq": signal["center_freq"],
        "file_duration_s": file_duration_s(signal["path"], signal["format"], signal["sample_rate"]),
        "analyzed_seconds": analyzed_seconds,
        "fft_size": fft_size,
        "threshold_db": threshold_db,
        "confirm_frames": confirm_frames,
        "frame_time_s": fft_size / signal["sample_rate"],
        "total_frames": total_frames,
        "frames_with_regions": frames_with_regions,
        "frames_with_regions_ratio": safe_div(frames_with_regions, total_frames),
        "candidate_regions_total": total_regions,
        "candidate_regions_per_s": safe_div(total_regions, analyzed_seconds),
        "events_count": len(events),
        "events_per_s": safe_div(len(events), analyzed_seconds),
        "event_time_occupancy": min(safe_div(occupied_time, analyzed_seconds), 1.0),
        "median_event_duration_ms": stat_or_zero(durations, median) * 1000.0,
        "mean_event_duration_ms": stat_or_zero(durations, mean) * 1000.0,
        "median_bandwidth_hz": stat_or_zero(bandwidths, median),
        "mean_bandwidth_hz": stat_or_zero(bandwidths, mean),
        "max_bandwidth_hz": max(bandwidths) if bandwidths else 0.0,
        "freq_span_hz": freq_span,
        "median_peak_power_db": stat_or_zero(event_peaks, median),
        "median_mean_power_db": stat_or_zero(event_means, median),
        "median_noise_floor_db": stat_or_zero(noise_values, median),
        "median_region_peak_db": stat_or_zero(peak_values, median),
    }


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def stat_or_zero(values: Iterable[float], fn) -> float:
    values = list(values)
    return float(fn(values)) if values else 0.0


def write_csv(path: Path, rows: List[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, rows: List[dict]) -> None:
    ordinary = [row for row in rows if row["label"] == "ordinary"]
    uav = [row for row in rows if row["label"] == "uav"]

    lines = []
    lines.append("Сводка анализа сигналов")
    lines.append("")
    lines.append(f"Обычных сигналов: {len(ordinary)}")
    lines.append(f"БПЛА сигналов: {len(uav)}")
    lines.append("")
    for metric in [
        "events_per_s",
        "event_time_occupancy",
        "frames_with_regions_ratio",
        "median_bandwidth_hz",
        "freq_span_hz",
        "median_event_duration_ms",
    ]:
        lines.append(metric)
        lines.append(f"  ordinary median: {group_median(ordinary, metric):.6g}")
        lines.append(f"  uav median:      {group_median(uav, metric):.6g}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def group_median(rows: List[dict], metric: str) -> float:
    values = [float(row[metric]) for row in rows]
    return float(median(values)) if values else 0.0


def plot_metric_boxplot(path: Path, rows: List[dict], metric: str, title: str) -> None:
    ordinary = [float(row[metric]) for row in rows if row["label"] == "ordinary"]
    uav = [float(row[metric]) for row in rows if row["label"] == "uav"]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.boxplot([ordinary, uav], labels=["ordinary", "uav"], showmeans=True)
    ax.set_title(title)
    ax.set_ylabel(metric)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Сравнительный анализ обычных сигналов и сигналов БПЛА")
    parser.add_argument("--max-seconds", type=float, default=1.0, help="Сколько секунд каждого файла анализировать")
    parser.add_argument("--fft-size", type=int, default=4096)
    parser.add_argument("--threshold-db", type=float, default=12.0)
    parser.add_argument("--confirm-frames", type=int, default=3)
    args = parser.parse_args()

    signals = load_ordinary_signals() + load_uav_signals()
    if not signals:
        print("Сигналы для анализа не найдены.")
        return 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = RESULTS_DIR / f"signal_set_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for index, signal in enumerate(signals, start=1):
        print(f"[{index}/{len(signals)}] {signal['label']} | {signal['category']} | {signal['path'].name}")
        row = analyze_one_signal(
            signal,
            fft_size=args.fft_size,
            threshold_db=args.threshold_db,
            confirm_frames=args.confirm_frames,
            max_seconds=args.max_seconds,
        )
        rows.append(row)
        print(
            f"    events={row['events_count']}, events/s={row['events_per_s']:.3f}, "
            f"occupancy={row['event_time_occupancy']:.3f}, median_bw={row['median_bandwidth_hz']:.1f} Hz"
        )

    csv_path = out_dir / "signal_features.csv"
    summary_path = out_dir / "summary.txt"
    write_csv(csv_path, rows)
    write_summary(summary_path, rows)
    plot_metric_boxplot(out_dir / "events_per_s.png", rows, "events_per_s", "Event density")
    plot_metric_boxplot(out_dir / "bandwidth_hz.png", rows, "median_bandwidth_hz", "Median event bandwidth")
    plot_metric_boxplot(out_dir / "occupancy.png", rows, "event_time_occupancy", "Time occupancy")

    print("")
    print("Готово.")
    print(f"CSV с признаками: {csv_path}")
    print(f"Сводка: {summary_path}")
    print(f"Графики: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
