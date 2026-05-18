import sys
from pathlib import Path
PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from core.live import LiveRunner
from core.sources import SyntheticSDRSource


def main() -> int:
    cfg = dict(source='synthetic', device_args='', sample_rate_hz=2_000_000, center_freq_hz=433_920_000, bandwidth_hz=1_536_000, gain_db=30, agc=True, fft_size=4096, threshold_db=12, confirm_frames=3, block_size=4096, max_waterfall_rows=400, max_seconds=6.0)
    src = SyntheticSDRSource(cfg['sample_rate_hz'], cfg['center_freq_hz'], cfg['block_size'])
    out = LiveRunner(PROJECT_DIR, src, cfg).run()
    print('Online synthetic finished')
    for k, v in out.items():
        print(f'{k}: {v}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
