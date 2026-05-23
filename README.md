# SDR UAV Detector

## Offline режим
```bash
python scripts/generate_test_iq.py
python scripts/run_offline.py
```

## Online synthetic режим (без SDR)
```bash
python scripts/run_online_synthetic.py
```

## Online SDR режим (GUI)
```bash
python gui.py
```
В главном окне нажмите **Открыть online-режим SDR**.

## Запуск online-режима с SDRplay RSP1 на Windows
```powershell
cd "ПУТЬ_К_ПРОЕКТУ"
$env:PATH="D:\PothosSDR\bin;$env:PATH"
$env:PYTHONPATH="D:\PothosSDR\lib\python3.9\site-packages;$env:PYTHONPATH"
python -c "import SoapySDR; print(SoapySDR)"
SoapySDRUtil.exe --find="driver=sdrplay"
python scripts/check_sdr.py
python gui.py
```

Требуется:
- SDRplay API 3.15
- PothosSDR
- SoapySDRPlay/SoapySDRPlay3 plugin
- Python должен видеть модуль SoapySDR

## Структура результатов
- `outputs/test_XXX/plots`
- `outputs/test_XXX/reports`
