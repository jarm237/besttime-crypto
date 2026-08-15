# HMR-V1.3E-E2: Discrimination Matrix

Input: `research/historical_market_replay_v1/v1_3e/e1_candidates.parquet` — 1175 candidates


## SELL (n=1130)

| Target | ROC-AUC | PR-AUC | Spearman | TopQ WR | TopQ Return |
|--------|--------:|-------:|---------:|--------:|------------:|
| profitable_1bar | n/a | n/a | +0.010 | 0.0% | +0.0000% |
| profitable_4bar | 0.6726 | 0.4322 | +0.401 | 45.1% | -0.0489% |
| profitable_8bar | 0.7054 | 0.4166 | +0.442 | 43.4% | -0.0686% |
| profitable_16bar | 0.6935 | 0.4314 | +0.394 | 44.7% | -0.0532% |
| tp_before_sl_1pct | 0.6371 | 0.0578 | n/a | 4.0% | n/a |
| lifecycle_profitable_gross | 0.6826 | 0.4505 | +0.388 | 48.2% | -0.0326% |
| lifecycle_profitable_net | 0.6852 | 0.2576 | +0.388 | 25.7% | -0.1906% |

## BUY (n=45)

| Target | ROC-AUC | PR-AUC | Spearman | TopQ WR | TopQ Return |
|--------|--------:|-------:|---------:|--------:|------------:|
| profitable_1bar | n/a | n/a | +0.148 | 0.0% | +0.0000% |
| profitable_4bar | 0.6050 | 0.4815 | +0.262 | 44.4% | +0.0027% |
| profitable_8bar | 0.3867 | 0.3465 | -0.067 | 22.2% | -0.1062% |
| profitable_16bar | 0.6451 | 0.3414 | +0.149 | 44.4% | -0.0684% |
| tp_before_sl_1pct | 0.6136 | 0.0556 | n/a | 0.0% | n/a |
| lifecycle_profitable_gross | 0.5971 | 0.3177 | +0.188 | 33.3% | -0.0783% |
| lifecycle_profitable_net | 0.6220 | 0.1811 | +0.188 | 22.2% | -0.2363% |
