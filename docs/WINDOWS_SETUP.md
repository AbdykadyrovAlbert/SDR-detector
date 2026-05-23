# Windows 10/11 + SDRplay RSP1

Необходимые компоненты:
- SDRplay API 3.15
- PothosSDR
- SoapySDRPlay3
- Python + зависимости проекта

Команды проверки:
```powershell
$env:PATH="D:\PothosSDR\bin;$env:PATH"
$env:PYTHONPATH="D:\PothosSDR\lib\python3.9\site-packages;$env:PYTHONPATH"
SoapySDRUtil.exe --info
SoapySDRUtil.exe --find
SoapySDRUtil.exe --find="driver=sdrplay"
python -c "import SoapySDR; print(SoapySDR)"
python scripts/check_sdr.py
```

Synthetic режим работает без SoapySDR.
