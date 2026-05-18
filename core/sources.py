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



class SyntheticSDRSource:
    """Синтетический live-источник complex64 для теста online-режима."""

    def __init__(self, sample_rate_hz: float, center_freq_hz: float, block_size: int, burst_interval_sec: float = 1.0, burst_duration_sec: float = 0.2, signal_offset_hz: float = 120_000.0, snr_db: float = 18.0) -> None:
        self.sample_rate_hz = float(sample_rate_hz)
        self.center_freq_hz = float(center_freq_hz)
        self.block_size = int(block_size)
        self.burst_interval_sec = float(burst_interval_sec)
        self.burst_duration_sec = float(burst_duration_sec)
        self.signal_offset_hz = float(signal_offset_hz)
        self.snr_db = float(snr_db)

    def iter_blocks(self, max_seconds: Optional[float] = None) -> Iterator[IQBlock]:
        sample_idx = 0
        max_samples = None if max_seconds is None else int(max_seconds * self.sample_rate_hz)
        rng = np.random.default_rng(42)
        while True:
            if max_samples is not None and sample_idx >= max_samples:
                break
            n = self.block_size if max_samples is None else min(self.block_size, max_samples - sample_idx)
            t = (np.arange(n, dtype=np.float32) + sample_idx) / self.sample_rate_hz
            noise = (rng.normal(0, 1, n) + 1j * rng.normal(0, 1, n)).astype(np.complex64)
            noise /= np.sqrt(2.0)

            phase = 2 * np.pi * self.signal_offset_hz * t
            tone = np.exp(1j * phase).astype(np.complex64)
            burst_phase = np.mod(t, self.burst_interval_sec)
            burst_mask = burst_phase < self.burst_duration_sec
            amp = 10 ** (self.snr_db / 20.0)
            samples = noise + tone * burst_mask.astype(np.float32) * amp
            yield IQBlock(samples=samples.astype(np.complex64), start_sample=sample_idx, start_time_s=sample_idx / self.sample_rate_hz)
            sample_idx += n


class SoapySDRSource:
    def __init__(
        self,
        device_args: str,
        sample_rate_hz: float,
        center_freq_hz: float,
        bandwidth_hz: float,
        gain_db: float | None,
        agc: bool,
        block_size: int,
    ) -> None:
        self.device_args = device_args
        self.sample_rate_hz = float(sample_rate_hz)
        self.center_freq_hz = float(center_freq_hz)
        self.bandwidth_hz = float(bandwidth_hz)
        self.gain_db = None if gain_db is None else float(gain_db)
        self.agc = bool(agc)
        self.block_size = int(block_size)

    def _import_soapy(self):
        try:
            import SoapySDR  # type: ignore
            return SoapySDR
        except Exception as exc:
            raise RuntimeError('SoapySDR не установлен. Offline/synthetic режимы доступны без него. Установите SoapySDR и драйвер устройства.') from exc

    def _parse_device_args(self, device_args: str) -> dict:
        if not device_args.strip():
            return {}
        result: dict[str, str] = {}
        for chunk in device_args.split(","):
            part = chunk.strip()
            if not part:
                continue
            if "=" not in part:
                raise RuntimeError(f"Некорректный device_args элемент: '{part}'. Ожидается ключ=значение.")
            key, value = part.split("=", 1)
            result[key.strip()] = value.strip()
        return result

    def iter_blocks(self, max_seconds: Optional[float] = None) -> Iterator[IQBlock]:
        SoapySDR = self._import_soapy()
        dev_kwargs = self._parse_device_args(self.device_args)
        try:
            dev = SoapySDR.Device(dev_kwargs)
        except Exception as exc:
            raise RuntimeError(
                f"Не удалось открыть SDR с device_args='{self.device_args}'. Проверьте драйвер и подключение устройства."
            ) from exc
        rx = SoapySDR.SOAPY_SDR_RX
        ch = 0
        dev.setSampleRate(rx, ch, self.sample_rate_hz)
        dev.setFrequency(rx, ch, self.center_freq_hz)
        if self.bandwidth_hz > 0:
            dev.setBandwidth(rx, ch, self.bandwidth_hz)
        if self.agc:
            dev.setGainMode(rx, ch, True)
        else:
            dev.setGainMode(rx, ch, False)
            if self.gain_db is not None:
                dev.setGain(rx, ch, self.gain_db)
        stream = dev.setupStream(rx, SoapySDR.SOAPY_SDR_CF32)
        dev.activateStream(stream)
        sample_idx = 0
        max_samples = None if max_seconds is None else int(max_seconds * self.sample_rate_hz)
        try:
            while True:
                if max_samples is not None and sample_idx >= max_samples:
                    break
                buff = np.empty(self.block_size, dtype=np.complex64)
                sr = dev.readStream(stream, [buff], len(buff), timeoutUs=200000)
                if sr.ret <= 0:
                    continue
                samples = buff[: sr.ret]
                yield IQBlock(samples=samples, start_sample=sample_idx, start_time_s=sample_idx / self.sample_rate_hz)
                sample_idx += samples.size
        finally:
            dev.deactivateStream(stream)
            dev.closeStream(stream)
