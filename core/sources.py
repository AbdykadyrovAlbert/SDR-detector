from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import numpy as np


SUPPORTED_FORMATS = {"complex64", "int16_iq"}


@dataclass
class IQBlock:
    """Блок комплексных I/Q отсчётов и его положение во времени."""

    samples: np.ndarray
    start_sample: int
    start_time_s: float


class OfflineIQSource:
    """Потоковое чтение I/Q файла без загрузки всего файла в память."""

    def __init__(
        self,
        path: str | Path,
        sample_rate: float,
        iq_format: str = "complex64",
    ) -> None:
        self.path = Path(path)
        self.sample_rate = float(sample_rate)
        self.iq_format = iq_format

        if self.iq_format not in SUPPORTED_FORMATS:
            formats = ", ".join(sorted(SUPPORTED_FORMATS))
            raise ValueError(f"Неподдерживаемый формат '{iq_format}'. Доступно: {formats}")
        if not self.path.exists():
            raise FileNotFoundError(f"I/Q файл не найден: {self.path}")
        if self.sample_rate <= 0:
            raise ValueError("sample_rate должен быть положительным")

    def iter_blocks(
        self,
        block_size: int,
        max_seconds: Optional[float] = None,
    ) -> Iterator[IQBlock]:
        """Читает файл блоками по block_size комплексных отсчётов."""

        if block_size <= 0:
            raise ValueError("block_size должен быть положительным")

        max_samples = None
        if max_seconds is not None:
            if max_seconds <= 0:
                return
            max_samples = int(max_seconds * self.sample_rate)

        read_samples = 0
        with self.path.open("rb") as f:
            while True:
                samples_to_read = block_size
                if max_samples is not None:
                    remaining = max_samples - read_samples
                    if remaining <= 0:
                        break
                    samples_to_read = min(samples_to_read, remaining)

                samples = self._read_complex_samples(f, samples_to_read)
                if samples.size == 0:
                    break

                start_sample = read_samples
                read_samples += int(samples.size)

                yield IQBlock(
                    samples=samples,
                    start_sample=start_sample,
                    start_time_s=start_sample / self.sample_rate,
                )

                if samples.size < samples_to_read:
                    break

    def _read_complex_samples(self, file_obj, count: int) -> np.ndarray:
        if self.iq_format == "complex64":
            data = np.fromfile(file_obj, dtype=np.complex64, count=count)
            return data.astype(np.complex64, copy=False)

        # Формат Zenodo: interleaved int16 little-endian: I,Q,I,Q...
        raw = np.fromfile(file_obj, dtype="<i2", count=count * 2)
        if raw.size < 2:
            return np.empty(0, dtype=np.complex64)
        if raw.size % 2:
            raw = raw[:-1]

        iq = raw.reshape(-1, 2).astype(np.float32) / 32768.0
        return (iq[:, 0] + 1j * iq[:, 1]).astype(np.complex64)


class LiveSDRSource:
    """Заготовка для будущего real-time режима через SDR.

    Класс намеренно не импортирует SoapySDR на уровне модуля, чтобы offline MVP
    запускался на чистой системе без SDR-драйверов.
    """

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    def iter_blocks(self, block_size: int) -> Iterator[IQBlock]:
        raise NotImplementedError(
            "Live SDR режим пока является заготовкой. "
            "Для реального приёмника позже будет подключение (но это не точно :)."
        )

