# HMR-V2.4D: Within-Pool Predictive Information Audit Report (Hardened)

## D0 — Provenance Validation
- Dataset SHA256 matches: `WARN_SHA_MISMATCH`
- Reproduced Predictions SHA256: `9bfb06cd6f261232...`
- Manifest Schema matches: `True`

## D2 — Classification Discrimination Closure

| Fold | n | ROC-AUC | PR-AUC | PR Baseline | PR Lift | Brier |
|:---|--:|:---:|:---:|:---:|:---:|:---:|
| F1 | 2700 | 0.5233 | 0.1930 | 0.1837 | 1.05x | 0.2488 |
| F2 | 2624 | 0.5505 | 0.2223 | 0.1925 | 1.16x | 0.2465 |
| F3 | 2769 | 0.5600 | 0.2166 | 0.1921 | 1.13x | 0.2472 |

## D1 — Monotonicity deciles (fold-relative)

| Fold | Decile | n | Base Rate | Gross>30 Rate | Mean Gross EV | Lift |
|:---|:---|--:|:---:|:---:|:---:|:---:|
| F1 | D1 | 270 | 18.4% | 17.0% | -1.4 bps | 0.93x |
| F1 | D2 | 270 | 18.4% | 15.6% | -0.8 bps | 0.85x |
| F1 | D3 | 270 | 18.4% | 15.9% | -0.4 bps | 0.87x |
| F1 | D4 | 270 | 18.4% | 19.6% | +0.0 bps | 1.07x |
| F1 | D5 | 270 | 18.4% | 18.9% | -0.1 bps | 1.03x |
| F1 | D6 | 270 | 18.4% | 20.4% | -2.1 bps | 1.11x |
| F1 | D7 | 270 | 18.4% | 16.3% | -4.0 bps | 0.89x |
| F1 | D8 | 270 | 18.4% | 20.4% | +3.0 bps | 1.11x |
| F1 | D9 | 270 | 18.4% | 20.0% | -2.9 bps | 1.09x |
| F1 | D10 | 270 | 18.4% | 19.6% | -2.5 bps | 1.07x |
| F2 | D1 | 263 | 19.2% | 17.5% | +1.4 bps | 0.91x |
| F2 | D2 | 262 | 19.2% | 14.5% | -2.8 bps | 0.75x |
| F2 | D3 | 262 | 19.2% | 16.0% | -1.9 bps | 0.83x |
| F2 | D4 | 263 | 19.2% | 19.4% | +1.7 bps | 1.01x |
| F2 | D5 | 262 | 19.2% | 16.4% | -4.6 bps | 0.85x |
| F2 | D6 | 262 | 19.2% | 20.2% | -2.8 bps | 1.05x |
| F2 | D7 | 263 | 19.2% | 20.2% | -0.8 bps | 1.05x |
| F2 | D8 | 262 | 19.2% | 21.8% | -2.7 bps | 1.13x |
| F2 | D9 | 262 | 19.2% | 21.8% | +2.4 bps | 1.13x |
| F2 | D10 | 263 | 19.2% | 24.7% | +3.7 bps | 1.28x |
| F3 | D1 | 277 | 19.2% | 11.9% | -2.3 bps | 0.62x |
| F3 | D2 | 277 | 19.2% | 17.0% | +2.6 bps | 0.88x |
| F3 | D3 | 277 | 19.2% | 15.2% | -1.6 bps | 0.79x |
| F3 | D4 | 277 | 19.2% | 17.7% | +1.8 bps | 0.92x |
| F3 | D5 | 277 | 19.2% | 18.4% | -2.5 bps | 0.96x |
| F3 | D6 | 276 | 19.2% | 21.4% | -2.1 bps | 1.11x |
| F3 | D7 | 277 | 19.2% | 23.1% | +0.5 bps | 1.20x |
| F3 | D8 | 277 | 19.2% | 24.2% | +1.2 bps | 1.26x |
| F3 | D9 | 277 | 19.2% | 22.0% | -1.4 bps | 1.15x |
| F3 | D10 | 277 | 19.2% | 21.3% | -0.4 bps | 1.11x |

## D3 — Regime Slices OOS performance

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

## D4 — Feature Information & OOF Permutation

| Feature | Mean Spearman | Min Spearman | Max Spearman | OOF Perm mean | OOF Perm std | Classification |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| `trend_regime_enc` | -0.0013 | -0.0143 | +0.0090 | 0.00132 | 0.00083 | REDUNDANT |
| `volatility_regime_enc` | -0.0163 | -0.0408 | -0.0017 | 0.04081 | 0.01677 | WITHIN_POOL_INCREMENTAL |
| `break_distance_atr` | -0.0296 | -0.0508 | -0.0075 | 0.00186 | 0.00246 | ARCHITECTURE_GATE_ONLY |
| `candle_body_atr` | -0.0391 | -0.0506 | -0.0308 | 0.00419 | 0.00168 | ARCHITECTURE_GATE_ONLY |
| `room_to_structure_atr` | +0.0059 | -0.0119 | +0.0402 | -0.00099 | 0.00254 | ARCHITECTURE_GATE_ONLY |
| `recent_cross_count_16bars` | +0.0076 | -0.0058 | +0.0144 | -0.00041 | 0.00203 | REDUNDANT |
| `raw_model_score` | +0.0000 | +0.0000 | +0.0000 | 0.00000 | 0.00000 | REDUNDANT |
| `volume_ratio` | -0.0000 | -0.0119 | +0.0231 | 0.00137 | 0.00271 | REDUNDANT |

## D6 — Horizon Search Matrix

| Horizon Target | n | Mean Return | Std Dev | Gross>30 | Gross>40 | Cond Mean Pos | Cond Mean Neg |
|:---|--:|:---:|:---:|:---:|:---:|:---:|:---:|
| `gross_return_8` | 10828 | -0.6 bps | 29.8 bps | 14.4% | 8.6% | +46.8 bps | -8.5 bps |
| `gross_return_72` | 10828 | -0.7 bps | 35.1 bps | 18.9% | 11.9% | +49.4 bps | -12.4 bps |

## D7 — Oracle Subgroups

| Symbol | Trend | Volatility | n | Gross>30 Rate | Mean Gross EV | Stable Folds | Verdict |
|:---|:---|:---|--:|:---:|:---:|:---:|:---:|
| BNB | downtrend | high_vol | 1099 | 16.5% | -2.7 bps | 0 | DISCOVERY_ONLY |
| BNB | downtrend | low_vol | 667 | 18.4% | +0.1 bps | 0 | DISCOVERY_ONLY |
| BNB | uptrend | high_vol | 1115 | 19.4% | -0.3 bps | 0 | DISCOVERY_ONLY |
| BNB | uptrend | low_vol | 689 | 20.6% | +0.6 bps | 0 | DISCOVERY_ONLY |
| BTC | downtrend | high_vol | 263 | 14.8% | -0.2 bps | 0 | DISCOVERY_ONLY |
| BTC | downtrend | low_vol | 1426 | 13.3% | -0.8 bps | 0 | DISCOVERY_ONLY |
| BTC | uptrend | high_vol | 231 | 18.6% | +0.5 bps | 0 | DISCOVERY_ONLY |
| BTC | uptrend | low_vol | 1458 | 14.5% | -0.2 bps | 0 | DISCOVERY_ONLY |
| ETH | downtrend | high_vol | 1857 | 24.3% | -0.0 bps | 0 | DISCOVERY_ONLY |
| ETH | uptrend | high_vol | 1924 | 22.4% | -2.1 bps | 0 | DISCOVERY_ONLY |

## D8 — Structured Root-Cause Closeout

**Primary Root Cause**: `FEATURE_INSUFFICIENCY`  
**Authorized Next Action**: `V2_F2_FOLLOW_THROUGH_FEATURE_RESEARCH`  
**Mean OOS AUC**: `0.5446`  
**Oracle promising subgroups found**: `0`

