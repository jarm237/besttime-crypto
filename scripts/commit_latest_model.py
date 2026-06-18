"""
Helper to commit the latest calibrated model and report.
Usage:
  AUTO_COMMIT=1 python scripts/periodic_recalibration.py  # auto-commit inside
Or use this script to manually commit latest artifacts.
"""
import os
import sys
from pathlib import Path
import subprocess

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / 'logs'


def find_latest(prefix='meta_model_calibrated'):
    files = sorted(LOGS.glob(f"{prefix}*.joblib"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def main():
    f = find_latest()
    if not f:
        print('No calibrated model artifact found')
        return 1
    report = sorted(LOGS.glob('recalibration_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    report_f = report[0] if report else None
    try:
        subprocess.run(['git', 'add', str(f), str(report_f) if report_f else ''], check=True)
        subprocess.run(['git', 'commit', '-m', f'Add calibrated model {f.name}'], check=True)
        subprocess.run(['git', 'push'], check=True)
        print('Committed and pushed', f)
    except Exception as e:
        print('Git commit failed:', e)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
