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


class OnlineWindow:
    def __init__(self, master: tk.Tk) -> None:
        self.top = tk.Toplevel(master)
        self.top.title("Online SDR")
        self.top.geometry("1200x760")
        self.msg: queue.Queue = queue.Queue()
        self.stop_evt = threading.Event()
        self.worker = None

        self.status = tk.StringVar(value="stopped")
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
        self.waterfall_data = np.full((300, 4096), -120.0, dtype=np.float32)
        self.latest_psd: np.ndarray | None = None
        self.last_draw_ts = 0.0
        self.min_draw_interval_s = 0.12  # ~8 FPS, чтобы GUI не зависал
        self.events_count = 0
        self.last_noise_floor_db = -120.0
        self.last_threshold_db = -100.0

        self._build()
        self._poll()

    def _build(self) -> None:
        frm = ttk.Frame(self.top)
        frm.pack(fill="x", padx=8, pady=8)

        items = [
            ("Источник", self.source_var),
            ("Device args", self.device_args),
            ("Sample rate", self.sr),
            ("Center freq", self.cf),
            ("Bandwidth", self.bw),
            ("Gain", self.gain),
            ("FFT", self.fft),
            ("Threshold", self.th),
            ("Confirm", self.conf),
            ("Block", self.block),
            ("Rows", self.rows),
            ("Min dur, s", self.min_event_duration),
            ("Min BW, Hz", self.min_bandwidth),
            ("Min peak over noise", self.min_peak_over_noise),
            ("Min bins", self.min_bins_width),
        ]
        for i, (label, var) in enumerate(items):
            ttk.Label(frm, text=label).grid(row=i // 4 * 2, column=i % 4, sticky="w")
            if label == "Источник":
                ttk.Combobox(frm, textvariable=var, values=["synthetic", "soapy"], state="readonly").grid(
                    row=i // 4 * 2 + 1, column=i % 4, sticky="ew"
                )
            else:
                ttk.Entry(frm, textvariable=var).grid(row=i // 4 * 2 + 1, column=i % 4, sticky="ew")

        ttk.Checkbutton(frm, text="AGC", variable=self.agc).grid(row=6, column=0, sticky="w")
        ttk.Button(frm, text="Найти SDR", command=self._find).grid(row=6, column=1, sticky="ew")
        ttk.Button(frm, text="Start", command=self._start).grid(row=6, column=2, sticky="ew")
        ttk.Button(frm, text="Stop", command=self._stop).grid(row=6, column=3, sticky="ew")

        self.fig = Figure(figsize=(8, 4))
        self.ax = self.fig.add_subplot(111)
        self.img = self.ax.imshow(
            self.waterfall_data,
            aspect="auto",
            origin="lower",
            cmap="viridis",
            vmin=-100,
            vmax=-20,
            interpolation="nearest",
        )
        self.ax.set_title("Live waterfall (PSD dB)")
        self.ax.set_xlabel("FFT bin")
        self.ax.set_ylabel("Frame")
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.top)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.table = ttk.Treeview(self.top, columns=("n", "t", "dur", "freq", "bw", "peak", "status"), show="headings", height=8)
        for c in ("n", "t", "dur", "freq", "bw", "peak", "status"):
            self.table.heading(c, text=c)
        self.table.pack(fill="x")
        ttk.Label(self.top, textvariable=self.status).pack(anchor="w", padx=8, pady=6)

    def _cfg(self) -> dict:
        gain_text = self.gain.get().strip()
        gain_value = None if gain_text in {"", "auto", "AUTO", "Auto"} else float(gain_text)
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

            devs = SoapySDR.Device.enumerate()
            messagebox.showinfo("SDR", f"Найдено устройств: {len(devs)}\n{devs}")
        except Exception as exc:
            messagebox.showwarning("SDR", f"SoapySDR недоступен: {exc}")

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        cfg = self._cfg()
        self.frames_received = 0
        self.events_count = 0
        self.waterfall_data = np.full((cfg["max_waterfall_rows"], cfg["fft_size"]), -120.0, dtype=np.float32)
        self.stop_evt.clear()
        self.status.set("connecting")
        self.worker = threading.Thread(target=self._run, args=(cfg,), daemon=True)
        self.worker.start()

    def _run(self, cfg: dict) -> None:
        try:
            if cfg["source"] == "synthetic":
                src = SyntheticSDRSource(cfg["sample_rate_hz"], cfg["center_freq_hz"], cfg["block_size"])
            else:
                src = SoapySDRSource(
                    cfg["device_args"],
                    cfg["sample_rate_hz"],
                    cfg["center_freq_hz"],
                    cfg["bandwidth_hz"],
                    cfg["gain_db"],
                    cfg["agc"],
                    cfg["block_size"],
                )
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
        self.status.set("stopping")

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
                    self.table.insert(
                        "",
                        0,
                        values=(
                            event_no,
                            f"{payload.start_time_s:.2f}-{payload.end_time_s:.2f}",
                            f"{payload.duration_s:.3f}",
                            f"{payload.center_freq_hz:.0f}",
                            f"{payload.bandwidth_hz:.0f}",
                            f"{payload.peak_power_db:.1f}",
                            "confirmed",
                        ),
                    )
                    self.events_count = event_no
                elif kind == "done":
                    self.status.set(f"done: {payload['run_dir']}")
                elif kind == "err":
                    self.status.set("error")
                    messagebox.showerror("Online error", payload)
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
        self.canvas.draw_idle()
        self.frames_received += 1
        self.last_draw_ts = now
        self.status.set(
            f"running | frames={self.frames_received} | events={self.events_count} | noise={self.last_noise_floor_db:.1f} dB | threshold={self.last_threshold_db:.1f} dB | psd max={np.max(psd):.1f} dB"
        )
