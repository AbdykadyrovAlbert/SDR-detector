from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from core.detector import EventDetector
from core.logger import EventLogger
from core.pipeline import DetectionPipeline
from core.processing import SpectrumFrame, SpectrumProcessor
from core.runtime import create_test_output_dirs
from main import save_spectrogram


class LiveRunner:
    def __init__(self, project_dir: Path, source, cfg: Dict[str, object]) -> None:
        self.project_dir = project_dir
        self.source = source
        self.cfg = cfg

    def run(self, on_frame=None, on_event=None, stop_flag=None) -> Dict[str, object]:
        run_ctx = create_test_output_dirs(self.project_dir, root_name="outputs")
        processor = SpectrumProcessor(self.cfg["sample_rate_hz"], self.cfg["center_freq_hz"], self.cfg["fft_size"], self.cfg["threshold_db"])
        detector = EventDetector(
            confirm_frames=int(self.cfg["confirm_frames"]),
            merge_gap_hz=float(self.cfg.get("merge_events_freq_hz", processor.bin_width_hz * 2.0)),
            min_event_duration_sec=float(self.cfg.get("min_event_duration_sec", 0.03)),
            min_bandwidth_hz=float(self.cfg.get("min_bandwidth_hz", 5000.0)),
            min_peak_over_noise_db=float(self.cfg.get("min_peak_over_noise_db", 8.0)),
            min_bins_width=int(self.cfg.get("min_bins_width", 3)),
        )
        pipeline = DetectionPipeline(processor, detector)
        logger = EventLogger(logs_dir=run_ctx["reports_dir"], prefix="online_sdr_events")
        frames: List[SpectrumFrame] = []
        events = []
        start = datetime.now()
        processed = 0
        for block in self.source.iter_blocks(max_seconds=self.cfg.get("max_seconds")):
            if stop_flag and stop_flag.is_set():
                break
            res = pipeline.process_block(block)
            if res.frame is None:
                continue
            processed += 1
            frames.append(res.frame)
            if len(frames) > int(self.cfg.get("max_waterfall_rows", 300)):
                frames.pop(0)
            if on_frame:
                on_frame(res.frame)
            if res.new_events:
                logger.write_events(res.new_events)
                events.extend(res.new_events)
                if on_event:
                    for e in res.new_events:
                        on_event(e)
        tail = pipeline.flush()
        if tail:
            logger.write_events(tail)
            events.extend(tail)
        png_path = run_ctx["plots_dir"] / "online_sdr_spectrogram.png"
        save_spectrogram(frames, events, png_path, center_freq_hz=self.cfg["center_freq_hz"])
        stop = datetime.now()
        report_cfg = dict(self.cfg)
        average_event_duration = (sum(e.duration_s for e in events) / len(events)) if events else 0.0
        average_bandwidth = (sum(e.bandwidth_hz for e in events) / len(events)) if events else 0.0
        max_peak = max((e.peak_power_db for e in events), default=0.0)
        centers = [e.center_freq_hz for e in events]
        freq_range = f"{min(centers):.1f}..{max(centers):.1f}" if centers else ""
        report_cfg.update(
            {
                "start_time": start.isoformat(),
                "stop_time": stop.isoformat(),
                "processed_frames": processed,
                "total_raw_detections": detector.stats["raw_events"],
                "confirmed_events_count": detector.stats["confirmed_events"],
                "rejected_events_count": detector.stats["rejected_events"],
                "events_count": len(events),
                "average_event_duration": average_event_duration,
                "average_bandwidth_hz": average_bandwidth,
                "max_peak_power_db": max_peak,
                "detected_frequency_range_hz": freq_range,
            }
        )
        logger.report_info = report_cfg
        logger.finalize()
        (run_ctx["reports_dir"] / "online_run_config.json").write_text(json.dumps(report_cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"run_dir": run_ctx["run_dir"], "csv": logger.csv_path, "jsonl": logger.jsonl_path, "xlsx": logger.xlsx_path, "png": png_path, "events": len(events)}
