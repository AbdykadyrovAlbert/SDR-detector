from __future__ import annotations

from dataclasses import dataclass
from typing import List

from core.detector import DetectedEvent, EventDetector
from core.processing import SpectrumFrame, SpectrumProcessor
from core.sources import IQBlock


@dataclass
class PipelineStepResult:
    frame: SpectrumFrame | None
    new_events: List[DetectedEvent]


class DetectionPipeline:
    def __init__(self, processor: SpectrumProcessor, detector: EventDetector) -> None:
        self.processor = processor
        self.detector = detector

    def process_block(self, block: IQBlock) -> PipelineStepResult:
        frame = self.processor.process_block(block.samples, block.start_time_s)
        if frame is None:
            return PipelineStepResult(frame=None, new_events=[])
        return PipelineStepResult(frame=frame, new_events=self.detector.update(frame))

    def flush(self) -> List[DetectedEvent]:
        return self.detector.flush()
