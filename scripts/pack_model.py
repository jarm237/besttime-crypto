"""Simple packaging: export model artifact and minimal metadata into `dist/`.
Generates a tar.gz containing the calibrated model and evaluation report.
"""
import tarfile
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / 'logs'
DIST = BASE / 'dist'
DIST.mkdir(exist_ok=True)

def main():
    model = sorted(LOGS.glob('meta_model_calibrated*.joblib'), key=lambda p: p.stat().st_mtime, reverse=True)
    if not model:
        print('No calibrated model to package')
        return 1
    model = model[0]
    report = LOGS / 'meta_model_eval_results.json'
    out = DIST / f'package_{model.stem}.tar.gz'
    with tarfile.open(out, 'w:gz') as tf:
        tf.add(model, arcname=model.name)
        if report.exists():
            tf.add(report, arcname=report.name)
    print('Packaged:', out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
