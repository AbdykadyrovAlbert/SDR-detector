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
        detector = EventDetector(confirm_frames=int(self.cfg["confirm_frames"]), merge_gap_hz=processor.bin_width_hz * 2.0)
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
        logger.finalize()
        png_path = run_ctx["plots_dir"] / "online_sdr_spectrogram.png"
        save_spectrogram(frames, events, png_path, center_freq_hz=self.cfg["center_freq_hz"])
        stop = datetime.now()
        report_cfg = dict(self.cfg)
        report_cfg.update({"start_time": start.isoformat(), "stop_time": stop.isoformat(), "processed_frames": processed, "events_count": len(events)})
        (run_ctx["reports_dir"] / "online_run_config.json").write_text(json.dumps(report_cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"run_dir": run_ctx["run_dir"], "csv": logger.csv_path, "jsonl": logger.jsonl_path, "xlsx": logger.xlsx_path, "png": png_path, "events": len(events)}
