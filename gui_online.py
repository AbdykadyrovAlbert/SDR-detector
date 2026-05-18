from __future__ import annotations

import queue
import threading
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
        self.msg = queue.Queue()
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
        self._build()
        self._poll()

    def _build(self):
        frm = ttk.Frame(self.top); frm.pack(fill="x", padx=8, pady=8)
        for i,(lbl,var) in enumerate([("Источник",self.source_var),("Device args",self.device_args),("Sample rate",self.sr),("Center freq",self.cf),("Bandwidth",self.bw),("Gain",self.gain),("FFT",self.fft),("Threshold",self.th),("Confirm",self.conf),("Block",self.block),("Rows",self.rows)]):
            ttk.Label(frm,text=lbl).grid(row=i//4*2,column=i%4,sticky='w')
            if lbl=="Источник": ttk.Combobox(frm,textvariable=var,values=["synthetic","soapy"],state="readonly").grid(row=i//4*2+1,column=i%4,sticky='ew')
            else: ttk.Entry(frm,textvariable=var).grid(row=i//4*2+1,column=i%4,sticky='ew')
        ttk.Checkbutton(frm,text='AGC',variable=self.agc).grid(row=6,column=0,sticky='w')
        ttk.Button(frm,text='Найти SDR',command=self._find).grid(row=6,column=1,sticky='ew')
        ttk.Button(frm,text='Start',command=self._start).grid(row=6,column=2,sticky='ew')
        ttk.Button(frm,text='Stop',command=self._stop).grid(row=6,column=3,sticky='ew')

        self.fig = Figure(figsize=(8,4)); self.ax=self.fig.add_subplot(111)
        self.img = self.ax.imshow(np.zeros((10,10)), aspect='auto', origin='lower')
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.top); self.canvas.get_tk_widget().pack(fill='both', expand=True)
        self.table = ttk.Treeview(self.top, columns=("t","freq","peak"), show='headings', height=8)
        for c in ("t","freq","peak"): self.table.heading(c,text=c)
        self.table.pack(fill='x')
        ttk.Label(self.top, textvariable=self.status).pack(anchor='w', padx=8,pady=6)

    def _cfg(self):
        return dict(source=self.source_var.get(), device_args=self.device_args.get(), sample_rate_hz=float(self.sr.get()), center_freq_hz=float(self.cf.get()), bandwidth_hz=float(self.bw.get()), gain_db=float(self.gain.get()), agc=bool(self.agc.get()), fft_size=int(self.fft.get()), threshold_db=float(self.th.get()), confirm_frames=int(self.conf.get()), block_size=int(self.block.get()), max_waterfall_rows=int(self.rows.get()), max_seconds=None)

    def _find(self):
        try:
            import SoapySDR
            devs = SoapySDR.Device.enumerate()
            messagebox.showinfo("SDR", f"Найдено устройств: {len(devs)}\n{devs}")
        except Exception as exc:
            messagebox.showwarning("SDR", f"SoapySDR недоступен: {exc}")

    def _start(self):
        if self.worker and self.worker.is_alive(): return
        cfg=self._cfg(); self.stop_evt.clear(); self.status.set('connecting')
        self.worker=threading.Thread(target=self._run,args=(cfg,),daemon=True); self.worker.start()

    def _run(self,cfg):
        try:
            src = SyntheticSDRSource(cfg['sample_rate_hz'],cfg['center_freq_hz'],cfg['block_size']) if cfg['source']=='synthetic' else SoapySDRSource(cfg['device_args'],cfg['sample_rate_hz'],cfg['center_freq_hz'],cfg['bandwidth_hz'],cfg['gain_db'],cfg['agc'],cfg['block_size'])
            runner=LiveRunner(PROJECT_DIR,src,cfg)
            wf=[]
            def on_frame(frame):
                wf.append(frame.psd_db)
                if len(wf)>cfg['max_waterfall_rows']: wf.pop(0)
                self.msg.put(('wf', np.array(wf, dtype=np.float32)))
            def on_event(e): self.msg.put(('ev', e))
            out=runner.run(on_frame=on_frame,on_event=on_event,stop_flag=self.stop_evt)
            self.msg.put(('done', out))
        except Exception as exc:
            self.msg.put(('err',str(exc)))

    def _stop(self): self.stop_evt.set(); self.status.set('stopping')

    def _poll(self):
        try:
            while True:
                k,v=self.msg.get_nowait()
                if k=='wf': self.img.set_data(v); self.canvas.draw_idle(); self.status.set('running')
                elif k=='ev': self.table.insert('',0,values=(f"{v.start_time_s:.2f}-{v.end_time_s:.2f}", f"{v.center_freq_hz:.0f}", f"{v.peak_power_db:.1f}"))
                elif k=='done': self.status.set(f"done: {v['run_dir']}")
                elif k=='err': self.status.set('error'); messagebox.showerror('Online error',v)
        except queue.Empty:
            pass
        self.top.after(120,self._poll)
