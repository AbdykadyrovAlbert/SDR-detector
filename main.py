from __future__ import annotations

import argparse
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_DIR / ".matplotlib"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from core.config import load_simple_yaml
from core.detector import DetectedEvent, EventDetector
from core.logger import EventLogger
from core.processing import SpectrumFrame, SpectrumProcessor
from core.sources import OfflineIQSource, SUPPORTED_FORMATS

MAX_EVENTS_PER_PNG = 300


DEFAULTS: Dict[str, Any] = {
    "fft_size": 4096,
    "threshold_db": 12.0,
    "confirm_frames": 3,
    "max_seconds": None,
    "plot": None,
}

CONFIG_KEYS = {
    "offline",
    "format",
    "sample_rate",
    "center_freq",
    "fft_size",
    "threshold_db",
    "confirm_frames",
    "max_seconds",
    "plot",
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MVP обнаружения БПЛА по I/Q данным SDR: FFT, PSD, адаптивный порог, журнал событий."
    )
    parser.add_argument(
        "--config",
        default=str(PROJECT_DIR / "config.yaml"),
        help="Путь к config.yaml. По умолчанию используется config.yaml в корне проекта.",
    )
    parser.add_argument("--offline", help="Путь к I/Q файлу для offline-обработки")
    parser.add_argument("--format", choices=sorted(SUPPORTED_FORMATS), help="Формат I/Q файла")
    parser.add_argument("--sample-rate", type=float, help="Частота дискретизации, Гц")
    parser.add_argument("--center-freq", type=float, help="Центральная частота, Гц")
    parser.add_argument("--fft-size", type=int, help="Размер FFT, по умолчанию 4096")
    parser.add_argument("--threshold-db", type=float, help="Порог над шумовым фоном, дБ")
    parser.add_argument("--confirm-frames", type=int, help="Число кадров подряд для подтверждения события")
    parser.add_argument("--max-seconds", type=float, help="Сколько секунд файла обработать")
    parser.add_argument(
        "--plot",
        nargs="?",
        const="auto",
        help="Сохранить спектрограмму PNG. Можно указать путь или оставить без значения.",
    )
    parser.add_argument("--no-plot", action="store_true", help="Отключить PNG, даже если в config.yaml plot: true")
    return parser


def build_runtime_config(args: argparse.Namespace) -> Dict[str, Any]:
    config_path = Path(args.config)
    file_config = load_simple_yaml(config_path)
    unknown_keys = sorted(set(file_config) - CONFIG_KEYS)
    if unknown_keys:
        print(f"Предупреждение: неизвестные ключи config.yaml будут проигнорированы: {', '.join(unknown_keys)}")

    runtime = dict(DEFAULTS)
    runtime.update({key: value for key, value in file_config.items() if key in CONFIG_KEYS})

    cli_values = vars(args)
    for key in CONFIG_KEYS:
        value = cli_values.get(key)
        if value is not None:
            runtime[key] = value

    if isinstance(runtime.get("plot"), bool):
        runtime["plot"] = "auto" if runtime["plot"] else None
    if args.no_plot:
        runtime["plot"] = None

    missing = [key for key in ("offline", "format", "sample_rate", "center_freq") if runtime.get(key) is None]
    if missing:
        missing_text = ", ".join(f"--{key.replace('_', '-')}" for key in missing)
        raise SystemExit(f"Не хватает обязательных параметров: {missing_text}. Укажите их в CLI или config.yaml.")

    if runtime["format"] not in SUPPORTED_FORMATS:
        raise SystemExit(f"Неподдерживаемый формат: {runtime['format']}")

    return runtime


def format_hz(value: float) -> str:
    abs_value = abs(value)
    if abs_value >= 1e9:
        return f"{value / 1e9:.6f} GHz"
    if abs_value >= 1e6:
        return f"{value / 1e6:.3f} MHz"
    if abs_value >= 1e3:
        return f"{value / 1e3:.3f} kHz"
    return f"{value:.1f} Hz"


def print_event(event: DetectedEvent, index: int) -> None:
    print(
        f"[{index:03d}] EVENT: "
        f"t={event.start_time_s:.6f}-{event.end_time_s:.6f} s, "
        f"dur={event.duration_s:.6f} s, "
        f"fc={format_hz(event.center_freq_hz)}, "
        f"bw={format_hz(event.bandwidth_hz)}, "
        f"peak={event.peak_power_db:.1f} dB, mean={event.mean_power_db:.1f} dB"
    )


def safe_file_stem(path: str | Path) -> str:
    stem = Path(path).stem.strip()
    safe = "".join(char if char.isalnum() or char in ("-", "_", ".") else "_" for char in stem)
    return safe or "iq_file"


def resolve_plot_path(plot_arg: Optional[str], source_path: str | Path) -> Optional[Path]:
    if plot_arg is None:
        return None
    if plot_arg != "auto":
        return Path(plot_arg)

    results_dir = PROJECT_DIR / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    return results_dir / f"{safe_file_stem(source_path)}.png"


def numbered_png_path(base_path: Path, page_index: int) -> Path:
    if page_index == 0:
        return base_path
    return base_path.with_name(f"{base_path.stem}_{page_index + 1}{base_path.suffix}")


def save_spectrogram(
    frames: List[SpectrumFrame],
    events: List[DetectedEvent],
    path: Path,
    center_freq_hz: float,
) -> List[Path]:
    """Сохраняет waterfall PNG и разбивает разметку событий по 300 на файл."""

    if not frames:
        print("Спектрограмма не сохранена: нет обработанных кадров.")
        return []

    path.parent.mkdir(parents=True, exist_ok=True)
    psd = np.stack([frame.psd_db for frame in frames], axis=0)
    freqs_mhz = (frames[0].freqs_hz - center_freq_hz) / 1e6
    frame_duration_s = frames[0].duration_s
    times_s = np.array([frame.start_time_s for frame in frames])

    vmin, vmax = np.percentile(psd, [5, 99])
    time_min = float(times_s[0])
    time_max = float(times_s[-1] + frame_duration_s)
    extent = [float(freqs_mhz[0]), float(freqs_mhz[-1]), time_max, time_min]

    event_pages = [
        events[start : start + MAX_EVENTS_PER_PNG]
        for start in range(0, len(events), MAX_EVENTS_PER_PNG)
    ] or [[]]

    saved_paths: List[Path] = []
    for page_index, page_events in enumerate(event_pages):
        output_path = numbered_png_path(path, page_index)
        first_event_number = page_index * MAX_EVENTS_PER_PNG + 1

        fig, ax = plt.subplots(figsize=(13, 8))
        image = ax.imshow(psd, aspect="auto", cmap="viridis", extent=extent, vmin=vmin, vmax=vmax)
        fig.colorbar(image, ax=ax, label="PSD, dB")

        ax.set_xlabel("Offset from center frequency, MHz")
        ax.set_ylabel("Time, s")
        ax.set_title(f"Spectrogram, center frequency {format_hz(center_freq_hz)}")

        visible_events = 0
        for local_index, event in enumerate(page_events):
            global_index = first_event_number + local_index
            if event.end_time_s < time_min or event.start_time_s > time_max:
                continue

            bandwidth_hz = max(event.bandwidth_hz, abs(frames[0].freqs_hz[1] - frames[0].freqs_hz[0]))
            x0 = (event.center_freq_hz - bandwidth_hz / 2.0 - center_freq_hz) / 1e6
            width = bandwidth_hz / 1e6
            y0 = max(event.start_time_s, time_min)
            height = min(event.end_time_s, time_max) - y0
            if height <= 0:
                continue

            rect = Rectangle(
                (x0, y0),
                width,
                height,
                linewidth=1.6,
                edgecolor="white",
                facecolor="none",
            )
            ax.add_patch(rect)
            ax.text(
                x0,
                y0,
                f"#{global_index}",
                color="white",
                fontsize=8,
                weight="bold",
                va="bottom",
                ha="left",
                bbox={"facecolor": "black", "alpha": 0.45, "pad": 1.5, "edgecolor": "none"},
            )
            visible_events += 1

        page_text = f"Events on PNG: {len(page_events)} / total: {len(events)}"
        if len(event_pages) > 1:
            page_text += f" | part {page_index + 1}/{len(event_pages)}"
        if visible_events != len(page_events):
            page_text += f" | visible: {visible_events}"
        ax.text(
            0.01,
            0.99,
            page_text,
            transform=ax.transAxes,
            color="white",
            fontsize=9,
            va="top",
            ha="left",
            bbox={"facecolor": "black", "alpha": 0.45, "pad": 3, "edgecolor": "none"},
        )

        plt.tight_layout()
        plt.savefig(output_path, dpi=150)
        plt.close(fig)
        saved_paths.append(output_path)
        print(f"Спектрограмма сохранена: {output_path}")

    return saved_paths


def main() -> int:
    args = build_arg_parser().parse_args()
    cfg = build_runtime_config(args)

    source = OfflineIQSource(cfg["offline"], sample_rate=cfg["sample_rate"], iq_format=cfg["format"])
    processor = SpectrumProcessor(
        sample_rate=cfg["sample_rate"],
        center_freq=cfg["center_freq"],
        fft_size=cfg["fft_size"],
        threshold_db=cfg["threshold_db"],
    )
    detector = EventDetector(confirm_frames=cfg["confirm_frames"], merge_gap_hz=processor.bin_width_hz * 2.0)
    logger = EventLogger(logs_dir=PROJECT_DIR / "logs", prefix=safe_file_stem(cfg["offline"]))

    plot_path = resolve_plot_path(cfg["plot"], cfg["offline"])
    plot_frames: List[SpectrumFrame] = []
    max_plot_frames = 1000
    plot_stride = 1
    if plot_path is not None and cfg["max_seconds"] is not None:
        estimated_frames = max(1, math.ceil(cfg["max_seconds"] * cfg["sample_rate"] / cfg["fft_size"]))
        plot_stride = max(1, math.ceil(estimated_frames / max_plot_frames))

    print("Offline обработка запущена")
    print(f"Файл: {source.path}")
    print(f"Формат: {cfg['format']}, sample_rate={format_hz(cfg['sample_rate'])}, center_freq={format_hz(cfg['center_freq'])}")
    print(f"FFT={cfg['fft_size']}, threshold={cfg['threshold_db']:.1f} dB, confirm_frames={cfg['confirm_frames']}")
    if args.config:
        print(f"Config: {Path(args.config)}")

    events: List[DetectedEvent] = []
    processed_frames = 0

    for block in source.iter_blocks(cfg["fft_size"], max_seconds=cfg["max_seconds"]):
        frame = processor.process_block(block.samples, block.start_time_s)
        if frame is None:
            continue

        processed_frames += 1
        if plot_path is not None and len(plot_frames) < max_plot_frames and processed_frames % plot_stride == 0:
            plot_frames.append(frame)

        new_events = detector.update(frame)
        if new_events:
            logger.write_events(new_events)
            for event in new_events:
                events.append(event)
                print_event(event, len(events))

        if processed_frames % 1000 == 0:
            print(
                f"Кадров: {processed_frames}, t={frame.start_time_s:.3f} s, "
                f"noise={frame.noise_floor_db:.1f} dB, regions={len(frame.regions)}"
            )

    tail_events = detector.flush()
    if tail_events:
        logger.write_events(tail_events)
        for event in tail_events:
            events.append(event)
            print_event(event, len(events))

    logger.finalize()
    saved_plot_paths: List[Path] = []
    if plot_path is not None:
        saved_plot_paths = save_spectrogram(plot_frames, events, plot_path, center_freq_hz=cfg["center_freq"])

    print("")
    print(f"Готово. Обработано кадров: {processed_frames}")
    print(f"Найдено подтверждённых событий: {len(events)}")
    print(f"CSV журнал: {logger.csv_path}")
    print(f"JSONL журнал: {logger.jsonl_path}")
    print(f"XLSX журнал: {logger.xlsx_path}")
    for saved_plot_path in saved_plot_paths:
        print(f"PNG спектрограмма: {saved_plot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
