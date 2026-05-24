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
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + 18
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify="left", background="#ffffe0", relief="solid", borderwidth=1, wraplength=380)
        label.pack(ipadx=5, ipady=3)

    def hide(self, _event=None) -> None:
        if self.tip_window is not None:
            self.tip_window.destroy()
            self.tip_window = None


class OnlineWindow:
    def __init__(self, master: tk.Tk) -> None:
        self.top = tk.Toplevel(master)
        self.top.title("Онлайн SDR")
        self.top.geometry("1200x800")
        self.top.minsize(1000, 700)

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

        self.frames_received = 0
        self.events_count = 0
        self.last_noise_floor_db = -120.0
        self.last_threshold_db = -100.0
        self.waterfall_data = np.full((300, 4096), -120.0, dtype=np.float32)
        self.latest_psd: np.ndarray | None = None
        self.last_draw_ts = 0.0
        self.min_draw_interval_s = 0.12
        self.device_text = "—"
        self.last_event_text = "—"
        self._setup_styles()

        self._build()
        self._poll()

    def _labeled_entry(self, parent, row: int, col: int, label: str, var, tip: str):
        lbl = ttk.Label(parent, text=label)
        lbl.grid(row=row, column=col, sticky="w", padx=4, pady=(2, 0))
        ent = ttk.Entry(parent, textvariable=var, width=13)
        ent.grid(row=row + 1, column=col, sticky="ew", padx=4, pady=(0, 2))
        ToolTip(lbl, tip)
        ToolTip(ent, tip)
        return ent

    def _build(self) -> None:
        main_container = ttk.Frame(self.top)
        main_container.pack(fill="both", expand=True)

        self.scroll_canvas = tk.Canvas(main_container, highlightthickness=0)
        self.v_scroll = ttk.Scrollbar(main_container, orient="vertical", command=self.scroll_canvas.yview)
        self.scroll_canvas.configure(yscrollcommand=self.v_scroll.set)
        self.v_scroll.pack(side="right", fill="y")
        self.scroll_canvas.pack(side="left", fill="both", expand=True)

        self.scrollable_frame = ttk.Frame(self.scroll_canvas)
        self.canvas_window = self.scroll_canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        self.scrollable_frame.bind("<Configure>", self._on_frame_configure)
        self.scroll_canvas.bind("<Configure>", self._on_canvas_configure)
        self.scroll_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        root = ttk.Frame(self.scrollable_frame, padding=8)
        root.pack(fill="both", expand=True)

        settings_box = ttk.LabelFrame(root, text="Настройки", padding=6)
        settings_box.pack(fill="x", pady=(0, 4))
        for c in range(10):
            settings_box.columnconfigure(c, weight=1)

        ttk.Label(settings_box, text="Источник").grid(row=0, column=0, sticky="w", padx=4, pady=(2, 0))
        src_combo = ttk.Combobox(settings_box, textvariable=self.source_var, values=["synthetic", "soapy"], state="readonly", width=12)
        src_combo.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 2))
        ToolTip(src_combo, "synthetic — тестовый сигнал без SDR; soapy — реальный SDR через SoapySDR.")

        self._labeled_entry(settings_box, 0, 1, "Аргументы устройства", self.device_args, "Для SDRplay RSP1: driver=sdrplay.")
        ttk.Button(settings_box, text="Найти SDR", command=self._find).grid(row=1, column=2, sticky="ew", padx=4, pady=(0, 2))

        self._labeled_entry(settings_box, 2, 0, "Частота дискретизации, Гц", self.sr, "Рекомендуемый старт: 2000000.")
        self._labeled_entry(settings_box, 2, 1, "Центральная частота, Гц", self.cf, "Например 100000000 = 100 МГц.")
        self._labeled_entry(settings_box, 2, 2, "Полоса приёма, Гц", self.bw, "Обычно не больше sample rate.")
        self._labeled_entry(settings_box, 2, 3, "Усиление, дБ", self.gain, "Если AGC включен, ручное усиление может игнорироваться.")
        agc = ttk.Checkbutton(settings_box, text="AGC", variable=self.agc)
        agc.grid(row=3, column=4, sticky="w", padx=4, pady=(0, 2))
        ToolTip(agc, "Автоматическая регулировка усиления.")
        self._labeled_entry(settings_box, 4, 0, "Размер FFT", self.fft, "Рекомендуется 4096.")
        self._labeled_entry(settings_box, 4, 1, "Порог детекции, дБ", self.th, "Выше порог — меньше ложных срабатываний.")
        self._labeled_entry(settings_box, 4, 2, "Кадров подтверждения", self.conf, "Кадров подряд для подтверждения.")
        self._labeled_entry(settings_box, 4, 3, "Размер блока", self.block, "Размер блока I/Q.")
        self._labeled_entry(settings_box, 4, 4, "Строк спектрограммы", self.rows, "Строки истории waterfall.")
        self._labeled_entry(settings_box, 4, 5, "Мин. длительность, с", self.min_event_duration, "События короче отбрасываются.")
        self._labeled_entry(settings_box, 4, 6, "Мин. полоса, Гц", self.min_bandwidth, "Отсекает узкие пики.")
        self._labeled_entry(settings_box, 4, 7, "Мин. пик над шумом, дБ", self.min_peak_over_noise, "Минимальный пик над шумом.")
        self._labeled_entry(settings_box, 4, 8, "Минимум FFT-бинов", self.min_bins_width, "Минимум соседних бинов.")

        controls = ttk.Frame(settings_box)
        controls.grid(row=5, column=6, columnspan=4, sticky="e", padx=4)
        ttk.Button(controls, text="Найти SDR", command=self._find).pack(side="left", padx=3)
        ttk.Button(controls, text="Старт", command=self._start).pack(side="left", padx=3)
        ttk.Button(controls, text="Стоп", command=self._stop).pack(side="left", padx=3)
        ttk.Button(controls, text="Сбросить спектрограмму", command=self._reset_waterfall).pack(side="left", padx=3)

        status_frame = ttk.LabelFrame(root, text="Состояние и события", padding=6)
        status_frame.pack(fill="x", pady=(0, 4))
        self.status_info = tk.StringVar(value="Состояние: остановлено\nУстройство: —\nИсточник: synthetic\nКадров: 0\nСобытий: 0\nДиапазон: —\nТекущий пик: —\nПоследнее событие: —")
        ttk.Label(status_frame, textvariable=self.status_info, justify="left").pack(anchor="w")
        ttk.Label(status_frame, textvariable=self.status).pack(anchor="w", pady=(2, 0))

        self.fig = Figure(figsize=(9, 3.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.img = self.ax.imshow(self.waterfall_data, aspect="auto", origin="lower", cmap="viridis", vmin=-100, vmax=-20, interpolation="nearest")
        self.ax.set_title("Спектрограмма в реальном времени (PSD, дБ)")
        self.ax.set_xlabel("Частота, МГц")
        self.ax.set_ylabel("Кадр")
        plot_frame = ttk.LabelFrame(root, text="Спектрограмма", padding=4)
        plot_frame.pack(fill="both", expand=True, pady=(0, 4))
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        events_frame = ttk.LabelFrame(root, text="Обнаруженные события", padding=4)
        events_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(events_frame, columns=("n", "t", "dur", "freq", "bw", "peak", "status"), show="headings", height=10)
        headers = {"n": "№", "t": "Время, с", "dur": "Длительность, с", "freq": "Частота, МГц", "bw": "Полоса, кГц", "peak": "Пик, дБ", "status": "Статус"}
        widths = {"n": 45, "t": 160, "dur": 120, "freq": 130, "bw": 120, "peak": 90, "status": 120}
        for c in headers:
            self.table.heading(c, text=headers[c])
            self.table.column(c, width=widths[c], anchor="center")
        t_scroll = ttk.Scrollbar(events_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=t_scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        t_scroll.pack(side="right", fill="y")

        self._apply_preset()

    def _on_frame_configure(self, _event=None) -> None:
        self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self.scroll_canvas.itemconfigure(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event) -> None:
        self.scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def soapy_kwargs_to_dict(self, obj) -> dict:
        try:
            return {str(k): str(v) for k, v in dict(obj).items()}
        except Exception:
            pass
        result = {}
        try:
            for k in obj.keys():
                try:
                    result[str(k)] = str(obj[k])
                except Exception:
                    result[str(k)] = "-"
            return result
        except Exception:
            pass
        try:
            for k, v in obj.items():
                result[str(k)] = str(v)
            return result
        except Exception:
            pass
        return {"raw": str(obj)}

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
            messagebox.showwarning("SDR", "Python не видит модуль SoapySDR. Synthetic-режим работает без SoapySDR.")
            return

        query = {}
        args_text = self.device_args.get().strip()
        if args_text:
            for part in args_text.split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    query[k.strip()] = v.strip()
        raw_devices = SoapySDR.Device.enumerate(query if query else None)
        devices = [self.soapy_kwargs_to_dict(d) for d in raw_devices]
        if not devices:
            messagebox.showinfo("SDR", "SDR-устройство не найдено.\nПроверьте подключение, драйверы, SDRplay API, PothosSDR и поле «Аргументы устройства».")
            return
        lines = [f"Найдено устройств: {len(devices)}\n"]
        for i, d in enumerate(devices, 1):
            lines.append(f"Устройство {i}:")
            lines.append(f"Драйвер: {d.get('driver', '-')}")
            lines.append(f"Название: {d.get('label', d.get('name', '-'))}")
            lines.append(f"Серийный номер: {d.get('serial', '-')}")
            lines.append("")
        self.device_text = devices[0].get("label", devices[0].get("name", "неизвестно"))
        messagebox.showinfo("SDR", "\n".join(lines))

    def _reset_waterfall(self) -> None:
        rows = int(self.rows.get())
        fft_size = int(self.fft.get())
        self.waterfall_data = np.full((rows, fft_size), -120.0, dtype=np.float32)
        self.latest_psd = None
        self.events_count = 0
        self.last_event_text = "—"
        self.table.delete(*self.table.get_children())
        self.img.set_data(self.waterfall_data)
        self.img.set_clim(-100, -20)
        self.canvas.draw_idle()
        if self.worker and self.worker.is_alive():
            self.status.set("Статус: спектрограмма сброшена, поток продолжается")
        else:
            self.status.set("Статус: спектрограмма сброшена")

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        cfg = self._cfg()
        self.frames_received = 0
        self.events_count = 0
        self.last_event_text = "—"
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
                    freq_mhz = payload.center_freq_hz / 1e6
                    bw_khz = payload.bandwidth_hz / 1e3
                    self.table.insert("", 0, values=(event_no, f"{payload.start_time_s:.2f}-{payload.end_time_s:.2f}", f"{payload.duration_s:.3f}", f"{freq_mhz:.3f}", f"{bw_khz:.1f}", f"{payload.peak_power_db:.1f}", "подтв."))
                    self.events_count = event_no
                    self.last_event_text = f"{freq_mhz:.3f} МГц, {payload.duration_s:.2f} с, {bw_khz:.1f} кГц, {payload.peak_power_db:.1f} дБ"
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
        peak_mhz = peak_freq_hz / 1e6

        self.status_info.set(
            f"Состояние: поток идёт\n"
            f"Устройство: {self.device_text}\n"
            f"Источник: {self.source_var.get()}\n"
            f"Кадров: {self.frames_received}\n"
            f"Событий: {self.events_count}\n"
            f"Диапазон: {left:.3f}–{right:.3f} МГц\n"
            f"Текущий пик: {peak_mhz:.3f} МГц / {np.max(psd):.1f} дБ\n"
            f"Последнее событие: {self.last_event_text}"
        )
        self.status.set(
            f"Статус: поток идёт | Устройство: {self.device_text} | Кадров: {self.frames_received} | Событий: {self.events_count} | Диапазон: {left:.3f}–{right:.3f} МГц"
        )
    def _setup_styles(self) -> None:
        style = ttk.Style(self.top)
        style.configure("TLabel", font=("Segoe UI", 11))
        style.configure("TButton", font=("Segoe UI", 11))
        style.configure("TEntry", font=("Segoe UI", 11))
        style.configure("TCombobox", font=("Segoe UI", 11))
        style.configure("TLabelframe.Label", font=("Segoe UI", 11, "bold"))
        style.configure("Treeview", font=("Segoe UI", 10), rowheight=24)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
