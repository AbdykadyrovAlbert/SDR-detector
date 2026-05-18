# SDR Online Setup

Online режим поддерживает источники `synthetic` и `soapy`.

Рекомендуемые параметры:
- sample_rate_hz = 2000000
- center_freq_hz = 433920000
- bandwidth_hz = 1536000
- fft_size = 4096
- threshold_db = 12
- confirm_frames = 3

Примеры `device_args`:
- `driver=sdrplay`
- `driver=rtlsdr`
- `driver=hackrf`
- `driver=lime`

Для SDRplay RSP1: `driver=sdrplay`.
