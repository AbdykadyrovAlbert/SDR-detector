from __future__ import annotations

from pathlib import Path

import numpy as np


PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"


def add_burst(
    signal: np.ndarray,
    sample_rate: float,
    freq_offset_hz: float,
    start_s: float,
    end_s: float,
    amplitude: float,
) -> None:
    """Добавляет в массив короткий комплексный burst на заданном смещении частоты."""

    start = int(start_s * sample_rate)
    end = int(end_s * sample_rate)
    n = np.arange(end - start, dtype=np.float32)

    envelope = np.hanning(end - start).astype(np.float32)
    tone = np.exp(2j * np.pi * freq_offset_hz * n / sample_rate).astype(np.complex64)
    signal[start:end] += amplitude * envelope * tone


def save_int16_iq(path: Path, samples: np.ndarray) -> None:
    real = np.clip(np.real(samples), -0.98, 0.98)
    imag = np.clip(np.imag(samples), -0.98, 0.98)
    interleaved = np.empty(samples.size * 2, dtype="<i2")
    interleaved[0::2] = np.round(real * 32767).astype("<i2")
    interleaved[1::2] = np.round(imag * 32767).astype("<i2")
    interleaved.tofile(path)


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    sample_rate = 2_000_000
    center_freq = 2_440_000_000
    duration_s = 0.30
    rng = np.random.default_rng(42)

    sample_count = int(sample_rate * duration_s)
    noise = 0.035 * (
        rng.standard_normal(sample_count).astype(np.float32)
        + 1j * rng.standard_normal(sample_count).astype(np.float32)
    )
    samples = noise.astype(np.complex64)

    add_burst(samples, sample_rate, freq_offset_hz=250_000, start_s=0.055, end_s=0.105, amplitude=0.45)
    add_burst(samples, sample_rate, freq_offset_hz=-420_000, start_s=0.170, end_s=0.245, amplitude=0.38)

    cf32_path = DATA_DIR / "test_bursty_cf32.iq"
    ci16_path = DATA_DIR / "test_bursty_ci16.iq"
    samples.astype(np.complex64).tofile(cf32_path)
    save_int16_iq(ci16_path, samples)

    print("Тестовые I/Q файлы созданы")
    print(f"complex64: {cf32_path}")
    print(f"int16_iq:  {ci16_path}")
    print(f"sample_rate={sample_rate} Hz, center_freq={center_freq} Hz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
