from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from core.live import LiveRunner
from core.sources import SoapySDRSource, SyntheticSDRSource
from main import PROJECT_DIR


class ToolTip:
    def __init__(self, widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip_window = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _event=None) -> None:
        if self.tip_window is not None:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + 20
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify="left", background="#ffffe0", relief="solid", borderwidth=1, wraplength=420)
        label.pack(ipadx=5, ipady=3)

    def hide(self, _event=None) -> None:
        if self.tip_window is not None:
            self.tip_window.destroy()
            self.tip_window = None


class OnlineWindow:
    PRESETS = {
        "FM радио 100 МГц": (100_000_000, 2_000_000, 1_536_000),
        "433.92 МГц": (433_920_000, 2_000_000, 1_536_000),
        "868 МГц": (868_000_000, 2_000_000, 1_536_000),
        "915 МГц": (915_000_000, 2_000_000, 1_536_000),
        "ADS-B 1090 МГц": (1_090_000_000, 2_000_000, 1_536_000),
        "GPS L1 1575.42 МГц": (1_575_420_000, 2_000_000, 1_536_000),
    }

    def __init__(self, master: tk.Tk) -> None:
        self.top = tk.Toplevel(master)
        self.top.title("Онлайн SDR")
        self.top.geometry("1320x840")
        self.msg: queue.Queue = queue.Queue()
        self.stop_evt = threading.Event()
        self.worker = None

        self.status = tk.StringVar(value="Статус: остановлено")
        self.source_var = tk.StringVar(value="synthetic")
        self.device_args = tk.StringVar(value="driver=sdrplay")
        self.sr = tk.StringVar(value="2000000")
        self.cf = tk.StringVar(value="433920000")
        self.bw = tk.StringVar(value="1536000")
        self.gain = tk.StringVar(value="30")
        self.agc = tk.BooleanVar(value=True)
        self.fft = tk.StringVar(value="4096")
        self.th = tk.StringVar(value="12")
        self.conf = tk.StringVar(value="3")
        self.block = tk.StringVar(value="4096")
        self.rows = tk.StringVar(value="300")
        self.min_event_duration = tk.StringVar(value="0.03")
        self.min_bandwidth = tk.StringVar(value="5000")
        self.min_peak_over_noise = tk.StringVar(value="8")
        self.min_bins_width = tk.StringVar(value="3")
        self.preset_var = tk.StringVar(value="433.92 МГц")

        self.frames_received = 0
        self.events_count = 0
        self.last_noise_floor_db = -120.0
        self.last_threshold_db = -100.0
        self.waterfall_data = np.full((300, 4096), -120.0, dtype=np.float32)
        self.latest_psd: np.ndarray | None = None
        self.last_draw_ts = 0.0
        self.min_draw_interval_s = 0.12
        self.device_text = "не определено"

        self._build()
        self._poll()

    def _labeled_entry(self, parent, row, col, label, var, tip):
        lbl = ttk.Label(parent, text=label)
        lbl.grid(row=row, column=col, sticky="w", padx=5, pady=(4, 0))
        ent = ttk.Entry(parent, textvariable=var)
        ent.grid(row=row + 1, column=col, sticky="ew", padx=5, pady=(0, 4))
        ToolTip(lbl, tip)
        ToolTip(ent, tip)
        return ent

    def _build(self) -> None:
        root = ttk.Frame(self.top)
        root.pack(fill="both", expand=True, padx=8, pady=8)

        cfg = ttk.Frame(root)
        cfg.pack(fill="x")

        src_box = ttk.LabelFrame(cfg, text="1) Источник сигнала")
        sdr_box = ttk.LabelFrame(cfg, text="2) Параметры SDR")
        ana_box = ttk.LabelFrame(cfg, text="3) Параметры анализа")
        det_box = ttk.LabelFrame(cfg, text="4) Детекция")
        ctl_box = ttk.LabelFrame(cfg, text="5) Управление")
        for b in (src_box, sdr_box, ana_box, det_box, ctl_box):
            b.pack(fill="x", pady=4)

        for i in range(4):
            sdr_box.columnconfigure(i, weight=1)
            ana_box.columnconfigure(i, weight=1)
            det_box.columnconfigure(i, weight=1)

        ttk.Label(src_box, text="Пресет").grid(row=0, column=0, sticky="w", padx=5, pady=(4, 0))
        preset = ttk.Combobox(src_box, textvariable=self.preset_var, values=list(self.PRESETS), state="readonly")
        preset.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 4))
        preset.bind("<<ComboboxSelected>>", self._apply_preset)
        ToolTip(preset, "Быстрые частотные пресеты для первого запуска.")

        ttk.Label(src_box, text="Источник").grid(row=0, column=1, sticky="w", padx=5, pady=(4, 0))
        src_combo = ttk.Combobox(src_box, textvariable=self.source_var, values=["synthetic", "soapy"], state="readonly")
        src_combo.grid(row=1, column=1, sticky="ew", padx=5, pady=(0, 4))
        ToolTip(src_combo, "synthetic — тестовый сигнал без SDR. soapy — реальный SDR через SoapySDR.")

        self._labeled_entry(src_box, 0, 2, "Аргументы устройства", self.device_args, "Для SDRplay RSP1: driver=sdrplay. Для HackRF: driver=hackrf. Для RTL-SDR: driver=rtlsdr.")
        src_box.columnconfigure(2, weight=1)

        self._labeled_entry(sdr_box, 0, 0, "Частота дискретизации, Гц", self.sr, "Рекомендуемый старт: 2000000.")
        self._labeled_entry(sdr_box, 0, 1, "Центральная частота, Гц", self.cf, "Например 100000000 = 100 МГц, 433920000 = 433.92 МГц.")
        self._labeled_entry(sdr_box, 0, 2, "Полоса приёма, Гц", self.bw, "Обычно не больше sample rate. Старт: 1536000.")
        self._labeled_entry(sdr_box, 0, 3, "Усиление, дБ", self.gain, "Если AGC включен, ручное усиление может игнорироваться.")
        agc = ttk.Checkbutton(sdr_box, text="AGC (автоусиление)", variable=self.agc)
        agc.grid(row=2, column=0, sticky="w", padx=5, pady=4)
        ToolTip(agc, "Автоматическая регулировка усиления.")

        self._labeled_entry(ana_box, 0, 0, "Размер FFT", self.fft, "Больше FFT — выше разрешение, но выше нагрузка. Рекомендуется 4096.")
        self._labeled_entry(ana_box, 0, 1, "Порог детекции, дБ", self.th, "Увеличьте, если слишком много ложных срабатываний.")
        self._labeled_entry(ana_box, 0, 2, "Кадров подтверждения", self.conf, "Сколько кадров подряд нужно для подтверждения события.")
        self._labeled_entry(ana_box, 0, 3, "Размер блока", self.block, "Сколько I/Q отсчётов читается за раз. Старт: 4096.")
        self._labeled_entry(ana_box, 2, 0, "Строк спектрограммы", self.rows, "Длина истории на экране. Больше — больше нагрузка.")

        self._labeled_entry(det_box, 0, 0, "Мин. длительность, с", self.min_event_duration, "События короче этого значения не сохраняются.")
        self._labeled_entry(det_box, 0, 1, "Мин. полоса, Гц", self.min_bandwidth, "Отсекает узкие шумовые пики.")
        self._labeled_entry(det_box, 0, 2, "Мин. пик над шумом, дБ", self.min_peak_over_noise, "Минимальное превышение над шумовым фоном.")
        self._labeled_entry(det_box, 0, 3, "Минимум FFT-бинов", self.min_bins_width, "Минимум соседних бинов выше порога.")

        ttk.Button(ctl_box, text="Найти SDR", command=self._find).pack(side="left", padx=5, pady=5)
        ttk.Button(ctl_box, text="Старт", command=self._start).pack(side="left", padx=5, pady=5)
        ttk.Button(ctl_box, text="Стоп", command=self._stop).pack(side="left", padx=5, pady=5)
        ttk.Button(ctl_box, text="Справка", command=self._show_help).pack(side="left", padx=5, pady=5)

        self.fig = Figure(figsize=(9, 4.8))
        self.ax = self.fig.add_subplot(111)
        self.img = self.ax.imshow(self.waterfall_data, aspect="auto", origin="lower", cmap="viridis", vmin=-100, vmax=-20, interpolation="nearest")
        self.ax.set_title("Спектрограмма в реальном времени (PSD, дБ)")
        self.ax.set_xlabel("Частота, МГц")
        self.ax.set_ylabel("Кадр")
        self.canvas = FigureCanvasTkAgg(self.fig, master=root)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.table = ttk.Treeview(root, columns=("n", "t", "dur", "freq", "bw", "peak", "status"), show="headings", height=8)
        headers = {"n": "№", "t": "Время, с", "dur": "Длительность, с", "freq": "Частота, Гц", "bw": "Полоса, Гц", "peak": "Пик, дБ", "status": "Статус"}
        for c in headers:
            self.table.heading(c, text=headers[c])
        self.table.pack(fill="x", pady=(6, 0))

        ttk.Label(root, text="Wi‑Fi/Bluetooth работают около 2.4 ГГц и выше. SDRplay RSP1 принимает до 2 ГГц.", foreground="#666666").pack(anchor="w")
        ttk.Label(root, textvariable=self.status).pack(anchor="w", pady=4)

        self._apply_preset()

    def _show_help(self) -> None:
        text = (
            "Для проверки реального SDR используйте FM-радио: 100000000 Гц и нажмите Старт.\n"
            "Если видны яркие полосы — приёмник получает эфир.\n\n"
            "SDRplay RSP1 принимает примерно до 2 ГГц. Wi‑Fi/Bluetooth ~2.4 ГГц и выше,\n"
            "поэтому RSP1 их напрямую не принимает.\n\n"
            "Частоты для теста: FM 88–108 МГц, 433.92 МГц, 868/915 МГц, ADS-B 1090 МГц, GPS L1 1575.42 МГц."
        )
        messagebox.showinfo("Справка по онлайн-режиму", text)

    def _apply_preset(self, _event=None) -> None:
        preset = self.PRESETS.get(self.preset_var.get())
        if not preset:
            return
        cf, sr, bw = preset
        self.cf.set(str(cf))
        self.sr.set(str(sr))
        self.bw.set(str(bw))

    def _cfg(self) -> dict:
        gain_text = self.gain.get().strip()
        gain_value = None if gain_text.lower() in {"", "auto"} else float(gain_text)
        return dict(
            source=self.source_var.get(),
            device_args=self.device_args.get(),
            sample_rate_hz=float(self.sr.get()),
            center_freq_hz=float(self.cf.get()),
            bandwidth_hz=float(self.bw.get()),
            gain_db=gain_value,
            agc=bool(self.agc.get()),
            fft_size=int(self.fft.get()),
            threshold_db=float(self.th.get()),
            confirm_frames=int(self.conf.get()),
            block_size=int(self.block.get()),
            max_waterfall_rows=int(self.rows.get()),
            min_event_duration_sec=float(self.min_event_duration.get()),
            min_bandwidth_hz=float(self.min_bandwidth.get()),
            min_peak_over_noise_db=float(self.min_peak_over_noise.get()),
            min_bins_width=int(self.min_bins_width.get()),
            max_seconds=None,
        )

    def _find(self) -> None:
        try:
            import SoapySDR
        except Exception:
            messagebox.showwarning(
                "SDR",
                "Python не видит модуль SoapySDR.\n\nДля real SDR нужны:\n1) SDRplay API 3.15\n2) PothosSDR\n3) SoapySDRPlay3\n4) Корректный PYTHONPATH\n\nПроверьте:\nSoapySDRUtil.exe --find=\"driver=sdrplay\"\npython -c \"import SoapySDR; print(SoapySDR)\"\n\nSynthetic-режим работает без SoapySDR.",
            )
            return

        args_text = self.device_args.get().strip()
        query = {}
        if args_text:
            for part in args_text.split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    query[k.strip()] = v.strip()
        devs = SoapySDR.Device.enumerate(query if query else None)
        if not devs:
            messagebox.showinfo("SDR", "SDR-устройство не найдено. Проверьте подключение, драйверы, SDRplay API, PothosSDR и Device args.")
            return
        lines = [f"Найдено устройств: {len(devs)}\n"]
        for i, d in enumerate(devs, 1):
            lines.append(f"Устройство {i}:")
            lines.append(f"Драйвер: {d.get('driver', '-')}")
            lines.append(f"Название: {d.get('label', d.get('name', '-'))}")
            lines.append(f"Серийный номер: {d.get('serial', '-')}")
            lines.append("")
        self.device_text = devs[0].get("label", devs[0].get("name", "неизвестно"))
        messagebox.showinfo("SDR", "\n".join(lines))

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        cfg = self._cfg()
        self.frames_received = 0
        self.events_count = 0
        self.table.delete(*self.table.get_children())
        self.waterfall_data = np.full((cfg["max_waterfall_rows"], cfg["fft_size"]), -120.0, dtype=np.float32)
        self.stop_evt.clear()
        self.status.set("Статус: подключение...")
        self.worker = threading.Thread(target=self._run, args=(cfg,), daemon=True)
        self.worker.start()

    def _run(self, cfg: dict) -> None:
        try:
            if cfg["source"] == "synthetic":
                src = SyntheticSDRSource(cfg["sample_rate_hz"], cfg["center_freq_hz"], cfg["block_size"])
                self.device_text = "synthetic"
            else:
                src = SoapySDRSource(cfg["device_args"], cfg["sample_rate_hz"], cfg["center_freq_hz"], cfg["bandwidth_hz"], cfg["gain_db"], cfg["agc"], cfg["block_size"])
            runner = LiveRunner(PROJECT_DIR, src, cfg)

            def on_frame(frame):
                self.msg.put(("wf", (frame.psd_db.copy(), frame.noise_floor_db, frame.threshold_db)))

            def on_event(event):
                self.msg.put(("ev", event))

            out = runner.run(on_frame=on_frame, on_event=on_event, stop_flag=self.stop_evt)
            self.msg.put(("done", out))
        except Exception as exc:
            self.msg.put(("err", str(exc)))

    def _stop(self) -> None:
        self.stop_evt.set()
        self.status.set("Статус: остановка...")

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.msg.get_nowait()
                if kind == "wf":
                    psd_raw, noise_floor_db, threshold_db = payload
                    psd = np.asarray(psd_raw, dtype=np.float32)
                    if psd.ndim == 1 and psd.size == self.waterfall_data.shape[1] and np.isfinite(psd).any():
                        self.latest_psd = psd
                        self.last_noise_floor_db = float(noise_floor_db)
                        self.last_threshold_db = float(threshold_db)
                        now = time.perf_counter()
                        if now - self.last_draw_ts >= self.min_draw_interval_s:
                            self._redraw_latest_psd(now)
                elif kind == "ev":
                    event_no = self.events_count + 1
                    self.table.insert("", 0, values=(event_no, f"{payload.start_time_s:.2f}-{payload.end_time_s:.2f}", f"{payload.duration_s:.3f}", f"{payload.center_freq_hz:.0f}", f"{payload.bandwidth_hz:.0f}", f"{payload.peak_power_db:.1f}", "подтверждено"))
                    self.events_count = event_no
                elif kind == "done":
                    self.status.set(f"Статус: завершено | Папка: {payload['run_dir']}")
                elif kind == "err":
                    self.status.set("Статус: ошибка")
                    messagebox.showerror("Ошибка онлайн-режима", str(payload))
        except queue.Empty:
            pass
        if self.latest_psd is not None:
            now = time.perf_counter()
            if now - self.last_draw_ts >= self.min_draw_interval_s:
                self._redraw_latest_psd(now)
        self.top.after(100, self._poll)

    def _redraw_latest_psd(self, now: float) -> None:
        if self.latest_psd is None:
            return
        psd = self.latest_psd
        self.waterfall_data = np.roll(self.waterfall_data, -1, axis=0)
        self.waterfall_data[-1, :] = psd
        low = float(np.nanpercentile(self.waterfall_data, 5))
        high = float(np.nanpercentile(self.waterfall_data, 95))
        if not np.isfinite(low) or not np.isfinite(high) or high - low < 1.0:
            low, high = -100.0, -20.0
        self.img.set_data(self.waterfall_data)
        self.img.set_clim(low, high)

        cf = float(self.cf.get())
        sr = float(self.sr.get())
        left = (cf - sr / 2.0) / 1e6
        right = (cf + sr / 2.0) / 1e6
        self.img.set_extent([left, right, 0, self.waterfall_data.shape[0]])
        self.ax.set_xlabel("Частота, МГц")
        self.canvas.draw_idle()

        self.frames_received += 1
        self.last_draw_ts = now
        peak_bin = int(np.argmax(psd))
        peak_freq_hz = cf - sr / 2.0 + (peak_bin / max(len(psd) - 1, 1)) * sr
        self.status.set(
            f"Статус: поток идёт | Источник: {self.source_var.get()} | Устройство: {self.device_text} | Кадров: {self.frames_received} | Событий: {self.events_count} | Диапазон: {left:.3f}–{right:.3f} МГц | Пик: {peak_freq_hz/1e6:.3f} МГц / {np.max(psd):.1f} дБ | Шум: {self.last_noise_floor_db:.1f} дБ | Порог: {self.last_threshold_db:.1f} дБ"
        )
