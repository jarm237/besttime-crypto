"""Check latest evaluation metrics against baseline thresholds.
Exits non-zero if any metric falls below threshold.
Writes `logs/metrics_check_result.json` with details.
"""
import json
from pathlib import Path
LOGS = Path(__file__).resolve().parent.parent / 'logs'
EVAL = LOGS / 'meta_model_eval_results.json'
OUT = LOGS / 'metrics_check_result.json'

# Thresholds (example) - adjust as needed
THRESHOLDS = {
    'roc_auc': 0.70,
    'pr_auc': 0.60,
    'brier': 0.25,  # lower is better
}


def main():
    if not EVAL.exists():
        print('Evaluation results not found:', EVAL)
        return 2
    data = json.loads(EVAL.read_text(encoding='utf-8'))
    failures = {}
    for k, t in THRESHOLDS.items():
        val = data.get(k)
        if val is None:
            failures[k] = {'status': 'missing', 'value': None, 'threshold': t}
            continue
        if k == 'brier':
            ok = val <= t
        else:
            ok = val >= t
        if not ok:
            failures[k] = {'status': 'fail', 'value': val, 'threshold': t}

    result = {'ok': len(failures) == 0, 'failures': failures, 'metrics': data}
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
