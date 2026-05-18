# SDR UAV Detector

MVP для дипломной работы: система обнаружения сигналов БПЛА по I/Q данным SDR в offline-режиме.

Конвейер обработки:

`I/Q данные -> блоки -> окно Hann -> FFT -> PSD -> медианный шумовой фон -> адаптивный порог -> превышения -> подтверждение по кадрам -> журнал событий`

Live-режим через SDR пока оставлен как заготовка в `core/sources.py` и не требует установки SoapySDR.

## Установка

```powershell
cd "D:\project VS code\SDR code\sdr_uav_detector"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Запуск GUI

Самый простой способ для Windows:

```text
start_gui.bat
```

Или из PowerShell:

```powershell
cd "D:\project VS code\SDR code\sdr_uav_detector"
.\.venv\Scripts\python.exe gui.py
```

В окне можно выбрать файл кнопкой или перетащить `.bin` / `.iq` файл в верхнюю область. Для drag-and-drop используется `tkinterdnd2`.

## Конфигурационный файл

В корне проекта есть `config.yaml`. Он позволяет запускать обработку без длинной команды:

```powershell
python main.py
```

Пример:

```yaml
offline: data/test_bursty_cf32.iq
format: complex64
sample_rate: 2000000
center_freq: 2440000000
fft_size: 4096
threshold_db: 12
confirm_frames: 3
max_seconds: 0.30
plot: true
```

CLI-параметры имеют приоритет над `config.yaml`.

## Генерация тестового сигнала

```powershell
python scripts\generate_test_iq.py
```

Будут созданы:

- `data/test_bursty_cf32.iq` в формате `complex64`;
- `data/test_bursty_ci16.iq` в формате `int16_iq`.

## Быстрый тест

```powershell
python scripts\run_offline.py
```

## Ручной запуск test complex64

```powershell
python main.py --offline data\test_bursty_cf32.iq --format complex64 --sample-rate 2000000 --center-freq 2440000000 --max-seconds 0.30 --plot
```

## Ручной запуск test int16_iq

```powershell
python main.py --offline data\test_bursty_ci16.iq --format int16_iq --sample-rate 2000000 --center-freq 2440000000 --max-seconds 0.30 --plot
```

## Запуск Zenodo 2G

Для файлов диапазона 2G:

- `sample_rate = 120000000`
- `center_freq = 2440000000`

```powershell
python main.py --offline data\DJI_inspire_2_2G.bin --format int16_iq --sample-rate 120000000 --center-freq 2440000000 --max-seconds 2 --plot
```

## Запуск Zenodo 5G

Для файлов диапазона 5G:

- `sample_rate = 200000000`
- `center_freq = 5800000000`

```powershell
python main.py --offline data\DJI_inspire_2_5G.bin --format int16_iq --sample-rate 200000000 --center-freq 5800000000 --max-seconds 2 --plot
```

## Результаты

Журналы событий сохраняются в `logs/`:

- CSV в UTF-8;
- JSONL в UTF-8;
- XLSX с отдельными колонками для всех параметров события.

Колонки XLSX:

- `start_time_s`;
- `end_time_s`;
- `duration_s`;
- `center_freq_hz`;
- `bandwidth_hz`;
- `peak_power_db`;
- `mean_power_db`.

PNG-спектрограммы сохраняются в `results/`.

Имя PNG теперь берётся из имени обрабатываемого файла:

- `test_bursty_cf32.iq` -> `results/test_bursty_cf32.png`;
- `DJI_inspire_2_2G.bin` -> `results/DJI_inspire_2_2G.png`.

Если событий больше 300, PNG разбивается на несколько файлов:

- `DJI_inspire_2_2G.png`;
- `DJI_inspire_2_2G_2.png`;
- `DJI_inspire_2_2G_3.png`.

На одном PNG отображается не больше 300 событий.

## Форматы I/Q

Поддерживаются два формата:

- `complex64`: комплексные числа NumPy `complex64`, удобно для собственных тестов.
- `int16_iq`: interleaved I/Q, signed int16 little-endian: `I,Q,I,Q...`; используется для файлов датасета Zenodo.

