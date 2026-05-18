# Windows 10 Setup

- Offline и synthetic online работают без SoapySDR.
- Для SDRplay RSP1 нужны: SDRplay API, SoapySDR, SoapySDRPlay3, python bindings SoapySDR.

Проверка:
- `SoapySDRUtil.exe --info`
- `SoapySDRUtil.exe --find`
- `SoapySDRUtil.exe --find="driver=sdrplay"`
- `SoapySDRUtil.exe --probe="driver=sdrplay"`
- `python -c "import SoapySDR; print(SoapySDR)"`
