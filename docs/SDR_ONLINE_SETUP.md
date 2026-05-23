# Онлайн-режим SDR

Online окно полностью русифицировано и содержит подсказки для полей.

## Быстрый тест без SDR
```bash
python scripts/run_online_synthetic.py
```

## Проверка реального SDR через SoapySDR
```powershell
SoapySDRUtil.exe --find="driver=sdrplay"
python -c "import SoapySDR; print(SoapySDR)"
python scripts/check_sdr.py
```

## Рекомендации
- Для первого запуска: sample_rate=2000000, center_freq=100000000 или 433920000.
- Если ложных срабатываний много — увеличьте порог и/или min bins.
