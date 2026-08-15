# HMR-V2.4D: Within-Pool Predictive Information Audit Report

## D2 — Classification Discrimination Closure

| Fold | n | ROC-AUC | PR-AUC | Brier |
|:---|--:|:---:|:---:|:---:|
| F1 | 2700 | 0.5233 | 0.1930 | 0.2488 |
| F2 | 2624 | 0.5505 | 0.2223 | 0.2465 |
| F3 | 2769 | 0.5600 | 0.2166 | 0.2472 |

## D1 — Score Monotonicity Audit (Deciles across Folds)

| Fold | Decile | n | Gross>30 Rate | Mean Gross EV | Profit Factor |
|:---|:---|--:|:---:|:---:|:---:|
| F1 | D1 | 270 | 17.0% | -1.4 bps | 0.89 |
| F1 | D2 | 270 | 15.6% | -0.8 bps | 0.94 |
| F1 | D3 | 270 | 15.9% | -0.4 bps | 0.97 |
| F1 | D4 | 270 | 19.6% | +0.0 bps | 1.00 |
| F1 | D5 | 270 | 18.9% | -0.1 bps | 0.99 |
| F1 | D6 | 270 | 20.4% | -2.1 bps | 0.86 |
| F1 | D7 | 270 | 16.3% | -4.0 bps | 0.76 |
| F1 | D8 | 270 | 20.4% | +3.0 bps | 1.24 |
| F1 | D9 | 270 | 20.0% | -2.9 bps | 0.82 |
| F1 | D10 | 270 | 19.6% | -2.5 bps | 0.85 |
| F2 | D1 | 263 | 17.5% | +1.4 bps | 1.12 |
| F2 | D2 | 262 | 14.5% | -2.8 bps | 0.80 |
| F2 | D3 | 262 | 16.0% | -1.9 bps | 0.86 |
| F2 | D4 | 263 | 19.4% | +1.7 bps | 1.15 |
| F2 | D5 | 262 | 16.4% | -4.6 bps | 0.72 |
| F2 | D6 | 262 | 20.2% | -2.8 bps | 0.83 |
| F2 | D7 | 263 | 20.2% | -0.8 bps | 0.94 |
| F2 | D8 | 262 | 21.8% | -2.7 bps | 0.85 |
| F2 | D9 | 262 | 21.8% | +2.4 bps | 1.18 |
| F2 | D10 | 263 | 24.7% | +3.7 bps | 1.28 |
| F3 | D1 | 277 | 11.9% | -2.3 bps | 0.81 |
| F3 | D2 | 277 | 17.0% | +2.6 bps | 1.24 |
| F3 | D3 | 277 | 15.2% | -1.6 bps | 0.87 |
| F3 | D4 | 277 | 17.7% | +1.8 bps | 1.15 |
| F3 | D5 | 277 | 18.4% | -2.5 bps | 0.85 |
| F3 | D6 | 276 | 21.4% | -2.1 bps | 0.87 |
| F3 | D7 | 277 | 23.1% | +0.5 bps | 1.04 |
| F3 | D8 | 277 | 24.2% | +1.2 bps | 1.08 |
| F3 | D9 | 277 | 22.0% | -1.4 bps | 0.91 |
| F3 | D10 | 277 | 21.3% | -0.4 bps | 0.97 |

## D3 — Regime Slices Performance

| Fold | Dimension | Value | n | Base >30% | Base Mean | OOS AUC | Top 10% EV |
|:---|:---|:---|--:|:---:|:---:|:---:|:---:|
| F1 | trend_regime | downtrend | 1323 | 18.4% | -1.7 bps | 0.532 | -1.4 bps |
| F1 | trend_regime | uptrend | 1377 | 18.4% | -0.6 bps | 0.515 | -5.3 bps |
| F1 | volatility_regime | high_vol | 1644 | 19.7% | -2.1 bps | 0.501 | -3.0 bps |
| F1 | volatility_regime | low_vol | 1056 | 16.3% | +0.3 bps | 0.495 | +2.0 bps |
| F1 | symbol | BNB | 885 | 17.3% | -3.1 bps | 0.448 | -2.4 bps |
| F1 | symbol | BTC | 844 | 14.1% | -0.2 bps | 0.537 | +6.5 bps |
| F1 | symbol | ETH | 971 | 23.1% | -0.2 bps | 0.491 | -7.3 bps |
| F2 | trend_regime | downtrend | 1306 | 18.8% | -0.4 bps | 0.551 | +6.2 bps |
| F2 | trend_regime | uptrend | 1318 | 19.7% | -0.8 bps | 0.550 | +3.2 bps |
| F2 | volatility_regime | high_vol | 1526 | 21.4% | -0.8 bps | 0.529 | +3.8 bps |
| F2 | volatility_regime | low_vol | 1098 | 16.3% | -0.3 bps | 0.503 | +1.1 bps |
| F2 | symbol | BNB | 882 | 18.5% | -0.5 bps | 0.517 | +1.7 bps |
| F2 | symbol | BTC | 831 | 14.7% | -0.0 bps | 0.486 | +2.2 bps |
| F2 | symbol | ETH | 911 | 24.1% | -1.3 bps | 0.517 | +3.3 bps |
| F3 | trend_regime | downtrend | 1421 | 19.0% | +0.2 bps | 0.584 | +1.0 bps |
| F3 | trend_regime | uptrend | 1348 | 19.4% | -1.1 bps | 0.535 | -2.6 bps |
| F3 | volatility_regime | high_vol | 1619 | 22.5% | -0.6 bps | 0.496 | -3.7 bps |
| F3 | volatility_regime | low_vol | 1150 | 14.6% | -0.1 bps | 0.514 | -3.1 bps |
| F3 | symbol | BNB | 885 | 18.9% | +0.4 bps | 0.496 | -4.5 bps |
| F3 | symbol | BTC | 850 | 13.5% | -0.8 bps | 0.536 | +0.9 bps |
| F3 | symbol | ETH | 1034 | 24.2% | -0.7 bps | 0.517 | +0.9 bps |

## D4 — Univariate Feature Correlation (Spearman ρ vs @72 Return)

| Feature | Spearman Correlation | Classification |
|:---|:---:|:---:|
| `trend_regime_enc` | -0.0003 | REDUNDANT / NO_SIGNAL |
| `volatility_regime_enc` | -0.0135 | REDUNDANT / NO_SIGNAL |
| `break_distance_atr` | -0.0315 | ARCHITECTURE_GATE_ONLY |
| `candle_body_atr` | -0.0374 | ARCHITECTURE_GATE_ONLY |
| `room_to_structure_atr` | -0.0037 | ARCHITECTURE_GATE_ONLY |
| `recent_cross_count_16bars` | +nan | REDUNDANT / NO_SIGNAL |
| `raw_model_score` | +nan | REDUNDANT / NO_SIGNAL |
| `volume_ratio` | +0.0028 | REDUNDANT / NO_SIGNAL |

## D6 — Horizon Search Matrix

| Target Column | n | Mean Return | Std Dev | Gross>30 Rate |
|:---|--:|:---:|:---:|:---:|
| `gross_return_72` | 10828 | -0.7 bps | 35.1 bps | 18.9% |
| `gross_return_8` | 10828 | -0.6 bps | 29.8 bps | 14.4% |

## D7 — Oracle Subgroup Analysis (n >= 150)

| Symbol | Trend | Volatility | n | Gross>30 Rate | Mean Gross EV | Profit Factor |
|:---|:---|:---|--:|:---:|:---:|:---:|
| BNB | downtrend | high_vol | 1099 | 16.5% | -2.7 bps | 0.82 |
| BNB | downtrend | low_vol | 667 | 18.4% | +0.1 bps | 1.00 |
| BNB | uptrend | high_vol | 1115 | 19.4% | -0.3 bps | 0.98 |
| BNB | uptrend | low_vol | 689 | 20.6% | +0.6 bps | 1.04 |
| BTC | downtrend | high_vol | 263 | 14.8% | -0.2 bps | 0.99 |
| BTC | downtrend | low_vol | 1426 | 13.3% | -0.8 bps | 0.93 |
| BTC | uptrend | high_vol | 231 | 18.6% | +0.5 bps | 1.04 |
| BTC | uptrend | low_vol | 1458 | 14.5% | -0.2 bps | 0.98 |
| ETH | downtrend | high_vol | 1857 | 24.3% | -0.0 bps | 1.00 |
| ETH | uptrend | high_vol | 1924 | 22.4% | -2.1 bps | 0.88 |

## Audit Verdict & Decision Closure

**Case Confirmed**: `CASE A — CURRENT FEATURE FAMILY HAS NO RANKING INFORMATION`

> The mean ROC-AUC is only **0.545** (barely above random guess). 
Current context variables do not contain predictive signal inside the compressed pool.
We must bypass regime training and move directly to follow-through volatility expansion features.
