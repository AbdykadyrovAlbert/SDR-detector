# SDR UAV Detector

## Offline mode
Существующий offline режим: обработка I/Q файла, детекция, PNG спектрограмма, CSV/JSONL/XLSX отчет.

## Online synthetic mode
Запуск без SDR:
```bash
python scripts/run_online_synthetic.py
```
Источник `SyntheticSDRSource` генерирует шум + burst сигналы и проверяет online pipeline.

## Online SDR mode
В GUI добавлена кнопка **Открыть online-режим SDR**.
Доступны источники:
- `synthetic`
- `soapy` (реальный SDR через SoapySDR)

Если SoapySDR не установлен, offline и synthetic продолжают работать, а soapy режим покажет понятную ошибку.

## SDR device args examples
- `driver=sdrplay`
- `driver=rtlsdr`
- `driver=hackrf`
- `driver=lime`

## Output structure
Все запуски сохраняются в:
- `outputs/test_XXX/plots`
- `outputs/test_XXX/reports`

Online synthetic/SDR формирует:
- `online_sdr_spectrogram.png`
- `online_sdr_events*.csv/jsonl/xlsx`
- `online_run_config.json`

## Windows 10 notes
См.:
- `docs/WINDOWS_SETUP.md`
- `docs/SDR_ONLINE_SETUP.md`
