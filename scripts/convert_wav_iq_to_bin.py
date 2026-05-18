from __future__ import annotations

import argparse
import shutil
import wave
from pathlib import Path

import numpy as np


def convert_wav_to_int16_iq(input_path: Path, output_path: Path, chunk_frames: int = 1_000_000) -> dict:
    """Потоковая конвертация stereo 16-bit WAV I/Q в raw int16_iq .bin."""

    if not input_path.exists():
        raise FileNotFoundError(f"Файл не найден: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(input_path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.getnframes()
        duration = frames / sample_rate

        if channels != 2:
            raise ValueError("Ожидался stereo WAV: левый канал = I, правый канал = Q")

        if sample_width != 2:
            raise ValueError("Ожидался 16-битный WAV")

        with output_path.open("wb") as out:
            while True:
                raw = wav.readframes(chunk_frames)
                if not raw:
                    break
                out.write(raw)

    return {
        "input_path": str(input_path),
        "output_path": str(output_path),
        "channels": channels,
        "bits": sample_width * 8,
        "sample_rate": sample_rate,
        "frames": frames,
        "duration_s": duration,
        "bytes_written": output_path.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Конвертация SDR WAV I/Q в raw int16_iq .bin")
    parser.add_argument("input_wav", help="Путь к WAV I/Q файлу")
    parser.add_argument("output_bin", help="Куда сохранить raw int16_iq .bin")
    args = parser.parse_args()

    input_path = Path(args.input_wav)
    output_path = Path(args.output_bin)

    with wave.open(str(input_path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.getnframes()
        duration = frames / sample_rate

        print("Информация о WAV-файле:")
        print(f"    Каналов: {channels}")
        print(f"    Размер отсчёта: {sample_width * 8} бит")
        print(f"    Частота дискретизации: {sample_rate} Гц")
        print(f"    Количество кадров: {frames}")
        print(f"    Длительность: {duration:.3f} с")

    info = convert_wav_to_int16_iq(input_path, output_path)

    print("")
    print("Конвертация завершена.")
    print(f"Raw int16_iq файл сохранён: {info['output_path']}")
    print("")
    print("Для запуска main.py используй:")
    print(f"    --format int16_iq")
    print(f"    --sample-rate {sample_rate}")
    print("    --center-freq 88110000")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
