import sys
from pathlib import Path
PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

def main() -> int:
    try:
        import SoapySDR  # type: ignore
    except Exception:
        print('SoapySDR не установлен. Это нормально для offline/synthetic режимов.')
        return 0

    print('SoapySDR импортирован:', SoapySDR)
    try:
        devs = SoapySDR.Device.enumerate()
        print('Найдено устройств:', len(devs))
        for idx, dev in enumerate(devs, start=1):
            print(f'[{idx}] {dev}')
    except Exception as exc:
        print('Не удалось выполнить enumerate:', exc)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
