from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np


@dataclass
class SpectrumRegion:
    start_freq_hz: float
    end_freq_hz: float
    center_freq_hz: float
    bandwidth_hz: float
    peak_power_db: float
    mean_power_db: float
    start_bin: int
    end_bin: int


@dataclass
class SpectrumFrame:
    start_time_s: float
    duration_s: float
    freqs_hz: np.ndarray
    psd_db: np.ndarray
    noise_floor_db: float
    threshold_db: float
    regions: List[SpectrumRegion]


class SpectrumProcessor:
    """Оконная FFT-обработка: Hann -> FFT -> PSD -> адаптивный порог."""

    def __init__(
        self,
        sample_rate: float,
        center_freq: float,
        fft_size: int = 4096,
        threshold_db: float = 12.0,
    ) -> None:
        if fft_size <= 0:
            raise ValueError("fft_size должен быть положительным")
        if sample_rate <= 0:
            raise ValueError("sample_rate должен быть положительным")

        self.sample_rate = float(sample_rate)
        self.center_freq = float(center_freq)
        self.fft_size = int(fft_size)
        self.threshold_over_noise_db = float(threshold_db)

        self.window = np.hanning(self.fft_size).astype(np.float32)
        self.window_power = float(np.sum(self.window**2))
        rel_freqs = np.fft.fftshift(np.fft.fftfreq(self.fft_size, d=1.0 / self.sample_rate))
        self.freqs_hz = rel_freqs + self.center_freq
        self.bin_width_hz = self.sample_rate / self.fft_size

    def process_block(self, samples: np.ndarray, start_time_s: float) -> SpectrumFrame | None:
        """Возвращает спектральный кадр или None для слишком короткого блока."""

        if samples.size < self.fft_size:
            return None

        x = samples[: self.fft_size].astype(np.complex64, copy=False)
        windowed = x * self.window
        spectrum = np.fft.fftshift(np.fft.fft(windowed, n=self.fft_size))

        # Нормировка на мощность окна делает уровни сопоставимыми при смене FFT.
        power = (np.abs(spectrum) ** 2) / max(self.window_power, 1e-12)
        psd_db = 10.0 * np.log10(power + 1e-20)

        noise_floor_db = float(np.median(psd_db))
        threshold_db = noise_floor_db + self.threshold_over_noise_db
        regions = self._find_regions(psd_db, threshold_db)

        return SpectrumFrame(
            start_time_s=float(start_time_s),
            duration_s=self.fft_size / self.sample_rate,
            freqs_hz=self.freqs_hz,
            psd_db=psd_db.astype(np.float32),
            noise_floor_db=noise_floor_db,
            threshold_db=float(threshold_db),
            regions=regions,
        )

    def _find_regions(self, psd_db: np.ndarray, threshold_db: float) -> List[SpectrumRegion]:
        mask = psd_db > threshold_db
        if not np.any(mask):
            return []

        regions: List[SpectrumRegion] = []
        indices = np.flatnonzero(mask)
        splits = np.where(np.diff(indices) > 1)[0] + 1

        for group in np.split(indices, splits):
            if group.size == 0:
                continue

            start_bin = int(group[0])
            end_bin = int(group[-1])
            region_psd = psd_db[start_bin : end_bin + 1]
            peak_idx = start_bin + int(np.argmax(region_psd))
            start_freq = float(self.freqs_hz[start_bin])
            end_freq = float(self.freqs_hz[end_bin])

            # Минимальная полоса равна ширине одного FFT-бина.
            bandwidth = max(abs(end_freq - start_freq) + self.bin_width_hz, self.bin_width_hz)

            regions.append(
                SpectrumRegion(
                    start_freq_hz=min(start_freq, end_freq),
                    end_freq_hz=max(start_freq, end_freq),
                    center_freq_hz=float(self.freqs_hz[peak_idx]),
                    bandwidth_hz=float(bandwidth),
                    peak_power_db=float(np.max(region_psd)),
                    mean_power_db=float(np.mean(region_psd)),
                    start_bin=start_bin,
                    end_bin=end_bin,
                )
            )

        return regions

