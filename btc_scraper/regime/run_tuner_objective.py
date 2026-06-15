"""
Run grid search tuner with a specific objective and save results to logs/multiplier_tuning_objective.json
Usage: .venv/bin/python -m btc_scraper.run_tuner_objective
"""
import json
import os
from btc_scraper.regime.tune_multipliers import _load_log, extract_records, grid_search

BASE = os.path.dirname(__file__)
OUT = os.path.join(BASE, "..", "logs", "multiplier_tuning_objective.json")


def main(objective='winrate_times_avgpnl', penalty=1.0):
    records = extract_records(_load_log())
    regimes = sorted(set((r.get('regime') or 'UNKNOWN') for r in records))
    grid_vals = [round(0.25 + i * 0.05, 2) for i in range(16)]
    top, total = grid_search(records, regimes, grid_vals, top_n=20, objective=objective, penalty=penalty)
    out = {'objective': objective, 'penalty': penalty, 'regimes': regimes, 'top': []}
    for score, mm in top:
        out['top'].append({'score': round(score,4), 'multipliers': mm})
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2)
    print('Wrote', OUT)

if __name__ == '__main__':
    main()
