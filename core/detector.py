from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List

from .processing import SpectrumFrame, SpectrumRegion


@dataclass
class DetectedEvent:
    start_time_s: float
    end_time_s: float
    duration_s: float
    center_freq_hz: float
    bandwidth_hz: float
    peak_power_db: float
    mean_power_db: float


@dataclass
class _Track:
    start_time_s: float
    end_time_s: float
    min_freq_hz: float
    max_freq_hz: float
    sum_center_freq_hz: float
    sum_mean_power_db: float
    peak_power_db: float
    frames: int
    confirmed: bool = False
    updated: bool = True


class EventDetector:
    """Подтверждает события, если превышение держится несколько кадров подряд."""

    def __init__(
        self,
        confirm_frames: int = 3,
        merge_gap_hz: float | None = None,
        min_event_duration_sec: float = 0.0,
        min_bandwidth_hz: float = 0.0,
        min_peak_over_noise_db: float = 0.0,
        min_bins_width: int = 1,
    ) -> None:
        self.confirm_frames = max(1, int(confirm_frames))
        self.merge_gap_hz = merge_gap_hz
        self.min_event_duration_sec = float(min_event_duration_sec)
        self.min_bandwidth_hz = float(min_bandwidth_hz)
        self.min_peak_over_noise_db = float(min_peak_over_noise_db)
        self.min_bins_width = max(1, int(min_bins_width))
        self._tracks: List[_Track] = []
        self.stats: Dict[str, int] = {"raw_regions": 0, "raw_events": 0, "confirmed_events": 0, "rejected_events": 0}

    def update(self, frame: SpectrumFrame) -> List[DetectedEvent]:
        """Обновляет активные треки и возвращает завершённые подтверждённые события."""

        candidates = self._merge_close_regions(frame.regions)
        filtered_candidates = []
        for region in candidates:
            bins_width = region.end_bin - region.start_bin + 1
            if bins_width < self.min_bins_width:
                continue
            if region.bandwidth_hz < self.min_bandwidth_hz:
                continue
            if (region.peak_power_db - frame.noise_floor_db) < self.min_peak_over_noise_db:
                continue
            filtered_candidates.append(region)
        self.stats["raw_regions"] += len(candidates)
        candidates = filtered_candidates
        for track in self._tracks:
            track.updated = False

        for region in candidates:
            track = self._find_matching_track(region)
            if track is None:
                self._tracks.append(
                    _Track(
                        start_time_s=frame.start_time_s,
                        end_time_s=frame.start_time_s + frame.duration_s,
                        min_freq_hz=region.start_freq_hz,
                        max_freq_hz=region.end_freq_hz,
                        sum_center_freq_hz=region.center_freq_hz,
                        sum_mean_power_db=region.mean_power_db,
                        peak_power_db=region.peak_power_db,
                        frames=1,
                        confirmed=self.confirm_frames <= 1,
                    )
                )
                continue

            track.end_time_s = frame.start_time_s + frame.duration_s
            track.min_freq_hz = min(track.min_freq_hz, region.start_freq_hz)
            track.max_freq_hz = max(track.max_freq_hz, region.end_freq_hz)
            track.sum_center_freq_hz += region.center_freq_hz
            track.sum_mean_power_db += region.mean_power_db
            track.peak_power_db = max(track.peak_power_db, region.peak_power_db)
            track.frames += 1
            track.updated = True
            if track.frames >= self.confirm_frames:
                track.confirmed = True

        finished: List[DetectedEvent] = []
        still_active: List[_Track] = []
        for track in self._tracks:
            if track.updated:
                still_active.append(track)
            elif track.confirmed:
                self.stats["raw_events"] += 1
                event = self._track_to_event(track)
                if self._accept_event(event):
                    finished.append(event)
                    self.stats["confirmed_events"] += 1
                else:
                    self.stats["rejected_events"] += 1

        self._tracks = still_active
        return finished

    def flush(self) -> List[DetectedEvent]:
        """Завершает все подтверждённые события в конце файла."""

        events: List[DetectedEvent] = []
        for track in self._tracks:
            if not track.confirmed:
                continue
            self.stats["raw_events"] += 1
            event = self._track_to_event(track)
            if self._accept_event(event):
                events.append(event)
                self.stats["confirmed_events"] += 1
            else:
                self.stats["rejected_events"] += 1
        self._tracks.clear()
        return events

    def _accept_event(self, event: DetectedEvent) -> bool:
        if event.duration_s < self.min_event_duration_sec:
            return False
        if event.bandwidth_hz <= 0 or event.bandwidth_hz < self.min_bandwidth_hz:
            return False
        return True

    def _merge_close_regions(self, regions: List[SpectrumRegion]) -> List[SpectrumRegion]:
        if not regions:
            return []

        sorted_regions = sorted(regions, key=lambda r: r.start_freq_hz)
        default_gap = 0.0
        if len(sorted_regions) > 1:
            default_gap = max(r.bandwidth_hz for r in sorted_regions) * 0.25
        gap_hz = self.merge_gap_hz if self.merge_gap_hz is not None else default_gap

        merged: List[SpectrumRegion] = []
        current = sorted_regions[0]
        for region in sorted_regions[1:]:
            if region.start_freq_hz <= current.end_freq_hz + gap_hz:
                current = self._combine_regions(current, region)
            else:
                merged.append(current)
                current = region
        merged.append(current)
        return merged

    def _combine_regions(self, a: SpectrumRegion, b: SpectrumRegion) -> SpectrumRegion:
        peak_region = a if a.peak_power_db >= b.peak_power_db else b
        start_freq = min(a.start_freq_hz, b.start_freq_hz)
        end_freq = max(a.end_freq_hz, b.end_freq_hz)
        return SpectrumRegion(
            start_freq_hz=start_freq,
            end_freq_hz=end_freq,
            center_freq_hz=peak_region.center_freq_hz,
            bandwidth_hz=end_freq - start_freq,
            peak_power_db=max(a.peak_power_db, b.peak_power_db),
            mean_power_db=(a.mean_power_db + b.mean_power_db) / 2.0,
            start_bin=min(a.start_bin, b.start_bin),
            end_bin=max(a.end_bin, b.end_bin),
        )

    def _find_matching_track(self, region: SpectrumRegion) -> _Track | None:
        for track in self._tracks:
            overlap = region.start_freq_hz <= track.max_freq_hz and region.end_freq_hz >= track.min_freq_hz
            close_center = abs(region.center_freq_hz - self._track_center(track)) <= max(
                region.bandwidth_hz,
                track.max_freq_hz - track.min_freq_hz,
            )
            if overlap or close_center:
                return track
        return None

    def _track_center(self, track: _Track) -> float:
        return track.sum_center_freq_hz / max(track.frames, 1)

    def _track_to_event(self, track: _Track) -> DetectedEvent:
        duration = max(track.end_time_s - track.start_time_s, 0.0)
        return DetectedEvent(
            start_time_s=track.start_time_s,
            end_time_s=track.end_time_s,
            duration_s=duration,
            center_freq_hz=self._track_center(track),
            bandwidth_hz=max(track.max_freq_hz - track.min_freq_hz, 0.0),
            peak_power_db=track.peak_power_db,
            mean_power_db=track.sum_mean_power_db / max(track.frames, 1),
        )


def event_to_dict(event: DetectedEvent) -> Dict[str, float]:
    return asdict(event)
