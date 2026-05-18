from __future__ import annotations

import math
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from gui_online import OnlineWindow

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DND_AVAILABLE = True
except ImportError:
    DND_FILES = None
    TkinterDnD = None
    DND_AVAILABLE = False

from core.detector import DetectedEvent, EventDetector
from core.logger import EventLogger
from core.processing import SpectrumFrame, SpectrumProcessor
from core.sources import OfflineIQSource
from main import PROJECT_DIR, create_test_output_dirs, format_hz, safe_file_stem, save_spectrogram


PRESETS = {
    "Тест complex64": {
        "format": "complex64",
        "sample_rate": "2000000",
        "center_freq": "2440000000",
        "max_seconds": "0.30",
    },
    "Zenodo 2G": {
        "format": "int16_iq",
        "sample_rate": "120000000",
        "center_freq": "2440000000",
        "max_seconds": "2",
    },
    "Zenodo 5G": {
        "format": "int16_iq",
        "sample_rate": "200000000",
        "center_freq": "5800000000",
        "max_seconds": "2",
    },
}


class DetectorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.online_window = None
        self.root = root
        self.root.title("SDR UAV Detector")
        self.root.geometry("980x720")
        self.root.minsize(860, 620)

        self.messages: queue.Queue = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.running = False

        self.file_var = tk.StringVar(value=str(PROJECT_DIR / "data" / "test_bursty_cf32.iq"))
        self.format_var = tk.StringVar(value="complex64")
        self.sample_rate_var = tk.StringVar(value="2000000")
        self.center_freq_var = tk.StringVar(value="2440000000")
        self.fft_size_var = tk.StringVar(value="4096")
        self.threshold_var = tk.StringVar(value="12")
        self.confirm_var = tk.StringVar(value="3")
        self.max_seconds_var = tk.StringVar(value="0.30")
        self.plot_var = tk.BooleanVar(value=True)
        self.preset_var = tk.StringVar(value="Тест complex64")

        self._build_ui()
        self._poll_messages()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)

        title = ttk.Label(
            self.root,
            text="Обнаружение БПЛА по I/Q файлам SDR",
            font=("Segoe UI", 16, "bold"),
        )
        title.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))

        file_frame = ttk.LabelFrame(self.root, text="Файл I/Q")
        file_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=8)
        file_frame.columnconfigure(0, weight=1)

        self.drop_label = ttk.Label(
            file_frame,
            text="Перетащите .bin/.iq файл сюда или выберите его кнопкой",
            anchor="center",
            relief="ridge",
            padding=16,
        )
        self.drop_label.grid(row=0, column=0, columnspan=3, sticky="ew", padx=10, pady=(10, 8))

        if DND_AVAILABLE:
            self.drop_label.drop_target_register(DND_FILES)
            self.drop_label.dnd_bind("<<Drop>>", self._on_drop)
        else:
            self.drop_label.configure(
                text="Выберите файл кнопкой. Для drag-and-drop установите tkinterdnd2 из requirements.txt."
            )

        ttk.Entry(file_frame, textvariable=self.file_var).grid(row=1, column=0, sticky="ew", padx=(10, 6), pady=(0, 10))
        ttk.Button(file_frame, text="Выбрать файл", command=self._browse_file).grid(
            row=1, column=1, sticky="ew", padx=6, pady=(0, 10)
        )
        ttk.Button(file_frame, text="Тестовый файл", command=self._use_test_file).grid(
            row=1, column=2, sticky="ew", padx=(6, 10), pady=(0, 10)
        )

        settings = ttk.LabelFrame(self.root, text="Параметры обработки")
        settings.grid(row=2, column=0, sticky="ew", padx=16, pady=8)
        for column in range(6):
            settings.columnconfigure(column, weight=1)

        ttk.Label(settings, text="Пресет").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        preset = ttk.Combobox(settings, textvariable=self.preset_var, values=list(PRESETS), state="readonly")
        preset.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        preset.bind("<<ComboboxSelected>>", self._apply_preset)

        ttk.Label(settings, text="Формат").grid(row=0, column=1, sticky="w", padx=10, pady=(10, 2))
        ttk.Combobox(
            settings,
            textvariable=self.format_var,
            values=["complex64", "int16_iq"],
            state="readonly",
        ).grid(row=1, column=1, sticky="ew", padx=10, pady=(0, 10))

        self._add_entry(settings, "Sample rate, Hz", self.sample_rate_var, row=0, column=2)
        self._add_entry(settings, "Center freq, Hz", self.center_freq_var, row=0, column=3)
        self._add_entry(settings, "FFT", self.fft_size_var, row=0, column=4)
        self._add_entry(settings, "Max seconds", self.max_seconds_var, row=0, column=5)

        self._add_entry(settings, "Threshold, dB", self.threshold_var, row=2, column=0)
        self._add_entry(settings, "Confirm frames", self.confirm_var, row=2, column=1)

        ttk.Checkbutton(settings, text="Сохранять PNG-спектрограмму", variable=self.plot_var).grid(
            row=3, column=2, columnspan=2, sticky="w", padx=10, pady=(0, 12)
        )

        ttk.Button(settings, text="Открыть reports", command=lambda: self._open_folder(PROJECT_DIR / "outputs", "reports")).grid(
            row=3, column=4, sticky="ew", padx=10, pady=(0, 12)
        )
        ttk.Button(settings, text="Открыть plots", command=lambda: self._open_folder(PROJECT_DIR / "outputs", "plots")).grid(
            row=3, column=5, sticky="ew", padx=10, pady=(0, 12)
        )

        self.start_button = ttk.Button(settings, text="Запустить обработку", command=self._start_processing)
        self.start_button.grid(row=4, column=4, sticky="ew", padx=10, pady=(0, 12))
        ttk.Button(settings, text="Открыть online-режим SDR", command=self._open_online).grid(row=4, column=5, sticky="ew", padx=10, pady=(0, 12))

        log_frame = ttk.LabelFrame(self.root, text="Журнал выполнения")
        log_frame.grid(row=3, column=0, sticky="nsew", padx=16, pady=(8, 16))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=18, wrap="word", font=("Consolas", 10))
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self.status_var = tk.StringVar(value="Готово к запуску")
        ttk.Label(self.root, textvariable=self.status_var, anchor="w").grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 10))

    def _add_entry(self, parent: ttk.Frame, label: str, variable: tk.StringVar, row: int, column: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=10, pady=(10, 2))
        ttk.Entry(parent, textvariable=variable).grid(row=row + 1, column=column, sticky="ew", padx=10, pady=(0, 10))

    def _apply_preset(self, _event=None) -> None:
        preset = PRESETS.get(self.preset_var.get())
        if not preset:
            return
        self.format_var.set(preset["format"])
        self.sample_rate_var.set(preset["sample_rate"])
        self.center_freq_var.set(preset["center_freq"])
        self.max_seconds_var.set(preset["max_seconds"])

    def _browse_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Выберите I/Q файл",
            initialdir=str(PROJECT_DIR / "data"),
            filetypes=[
                ("I/Q files", "*.bin *.iq *.dat *.cf32 *.ci16"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.file_var.set(path)
            self._guess_format_from_path(Path(path))

    def _use_test_file(self) -> None:
        self.file_var.set(str(PROJECT_DIR / "data" / "test_bursty_cf32.iq"))
        self.preset_var.set("Тест complex64")
        self._apply_preset()

    def _on_drop(self, event) -> None:
        paths = self.root.tk.splitlist(event.data)
        if paths:
            path = Path(paths[0])
            self.file_var.set(str(path))
            self._guess_format_from_path(path)

    def _open_folder(self, folder: Path, subfolder: Optional[str] = None) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        target = folder
        if subfolder in {"reports", "plots"}:
            test_dirs = sorted(
                [entry for entry in folder.iterdir() if entry.is_dir() and entry.name.startswith("test_")],
                key=lambda p: p.name,
            )
            if test_dirs:
                target = test_dirs[-1] / subfolder
                target.mkdir(parents=True, exist_ok=True)

        os.startfile(target)

    def _guess_format_from_path(self, path: Path) -> None:
        name = path.name.lower()
        if name.endswith(".bin") or "ci16" in name:
            self.format_var.set("int16_iq")
        elif "cf32" in name or name.endswith(".iq"):
            self.format_var.set("complex64")

    def _start_processing(self) -> None:
        if self.running:
            return

        try:
            config = self._read_config_from_ui()
        except ValueError as exc:
            messagebox.showerror("Ошибка параметров", str(exc))
            return

        self.running = True
        self.start_button.configure(state="disabled")
        self.status_var.set("Идёт обработка...")
        self.log_text.delete("1.0", "end")

        self.worker = threading.Thread(target=self._process_file_worker, args=(config,), daemon=True)
        self.worker.start()

    def _read_config_from_ui(self) -> dict:
        file_path = Path(self.file_var.get().strip())
        if not file_path.exists():
            raise ValueError(f"Файл не найден: {file_path}")

        max_seconds_text = self.max_seconds_var.get().strip()
        max_seconds = float(max_seconds_text) if max_seconds_text else None

        return {
            "offline": str(file_path),
            "format": self.format_var.get(),
            "sample_rate": float(self.sample_rate_var.get()),
            "center_freq": float(self.center_freq_var.get()),
            "fft_size": int(self.fft_size_var.get()),
            "threshold_db": float(self.threshold_var.get()),
            "confirm_frames": int(self.confirm_var.get()),
            "max_seconds": max_seconds,
            "plot": "auto" if self.plot_var.get() else None,
        }

    def _process_file_worker(self, cfg: dict) -> None:
        try:
            self._run_detection(cfg)
            self.messages.put(("done", None))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def _run_detection(self, cfg: dict) -> None:
        source = OfflineIQSource(cfg["offline"], sample_rate=cfg["sample_rate"], iq_format=cfg["format"])
        processor = SpectrumProcessor(
            sample_rate=cfg["sample_rate"],
            center_freq=cfg["center_freq"],
            fft_size=cfg["fft_size"],
            threshold_db=cfg["threshold_db"],
        )
        detector = EventDetector(confirm_frames=cfg["confirm_frames"], merge_gap_hz=processor.bin_width_hz * 2.0)
        run_ctx = create_test_output_dirs(PROJECT_DIR)
        run_index = int(run_ctx["run_index"])
        logger = EventLogger(
            logs_dir=run_ctx["reports_dir"],
            prefix=safe_file_stem(cfg["offline"]),
            report_info={
                "test_id": f"test_{run_index:03d}",
                "source_file": str(cfg["offline"]),
                "iq_format": cfg["format"],
                "sample_rate_hz": cfg["sample_rate"],
                "center_freq_hz": cfg["center_freq"],
                "fft_size": cfg["fft_size"],
                "threshold_db": cfg["threshold_db"],
                "confirm_frames": cfg["confirm_frames"],
                "max_seconds": cfg["max_seconds"],
            },
        )

        plot_path = None
        if cfg["plot"] is not None:
            plot_path = run_ctx["plots_dir"] / f"{safe_file_stem(cfg['offline'])}.png"
        plot_frames: List[SpectrumFrame] = []
        max_plot_frames = 1000
        plot_stride = 1
        if plot_path is not None and cfg["max_seconds"] is not None:
            estimated_frames = max(1, math.ceil(cfg["max_seconds"] * cfg["sample_rate"] / cfg["fft_size"]))
            plot_stride = max(1, math.ceil(estimated_frames / max_plot_frames))

        events: List[DetectedEvent] = []
        processed_frames = 0

        self.messages.put(("log", "Offline обработка запущена"))
        self.messages.put(("log", f"Папка теста: {run_ctx['run_dir']}"))
        self.messages.put(("log", f"Файл: {source.path}"))
        self.messages.put(
            (
                "log",
                f"Формат: {cfg['format']}, sample_rate={format_hz(cfg['sample_rate'])}, "
                f"center_freq={format_hz(cfg['center_freq'])}",
            )
        )

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
                    self.messages.put(("log", self._format_event(event, len(events))))

            if processed_frames % 500 == 0:
                self.messages.put(
                    (
                        "status",
                        f"Кадров: {processed_frames}, t={frame.start_time_s:.3f} s, "
                        f"noise={frame.noise_floor_db:.1f} dB",
                    )
                )

        tail_events = detector.flush()
        if tail_events:
            logger.write_events(tail_events)
            for event in tail_events:
                events.append(event)
                self.messages.put(("log", self._format_event(event, len(events))))

        logger.finalize()
        saved_plot_paths: List[Path] = []
        if plot_path is not None:
            saved_plot_paths = save_spectrogram(plot_frames, events, plot_path, center_freq_hz=cfg["center_freq"])
            for saved_plot_path in saved_plot_paths:
                self.messages.put(("log", f"PNG спектрограмма: {saved_plot_path}"))

        self.messages.put(("log", ""))
        self.messages.put(("log", f"Готово. Обработано кадров: {processed_frames}"))
        self.messages.put(("log", f"Найдено подтверждённых событий: {len(events)}"))
        self.messages.put(("log", f"CSV журнал: {logger.csv_path}"))
        self.messages.put(("log", f"JSONL журнал: {logger.jsonl_path}"))
        self.messages.put(("log", f"XLSX журнал: {logger.xlsx_path}"))
        self.messages.put(("status", f"Готово. Событий: {len(events)}"))

    def _format_event(self, event: DetectedEvent, index: int) -> str:
        return (
            f"[{index:03d}] EVENT: "
            f"t={event.start_time_s:.6f}-{event.end_time_s:.6f} s, "
            f"dur={event.duration_s:.6f} s, "
            f"fc={format_hz(event.center_freq_hz)}, "
            f"bw={format_hz(event.bandwidth_hz)}, "
            f"peak={event.peak_power_db:.1f} dB"
        )

    def _open_online(self) -> None:
        if self.online_window and self.online_window.top.winfo_exists():
            self.online_window.top.lift(); return
        self.online_window = OnlineWindow(self.root)

    def _poll_messages(self) -> None:
        while True:
            try:
                kind, payload = self.messages.get_nowait()
            except queue.Empty:
                break

            if kind == "log":
                self.log_text.insert("end", str(payload) + "\n")
                self.log_text.see("end")
            elif kind == "status":
                self.status_var.set(str(payload))
            elif kind == "error":
                self.running = False
                self.start_button.configure(state="normal")
                self.status_var.set("Ошибка")
                messagebox.showerror("Ошибка обработки", str(payload))
            elif kind == "done":
                self.running = False
                self.start_button.configure(state="normal")

        self.root.after(100, self._poll_messages)


def create_root() -> tk.Tk:
    if DND_AVAILABLE:
        return TkinterDnD.Tk()
    return tk.Tk()


def main() -> int:
    root = create_root()
    DetectorApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
