# HMR-V2-G1.4: Compression Feature Redundancy Audit

## 1. Spearman Correlation Matrix

| Feature | break_dist | body_atr | ema_dist | cross16 | room | vol_ratio | slope50 |
|:--------|:----------:|:--------:|:--------:|:-------:|:----:|:---------:|:-------:|
| `break_dist` | +1.00 | +0.84 | -0.68 | -0.04 | -0.74 | +0.02 | -0.17 |
| `body_atr` | +0.84 | +1.00 | -0.61 | +0.00 | -0.67 | +0.01 | -0.12 |
| `ema_dist` | -0.68 | -0.61 | +1.00 | -0.00 | +0.41 | -0.05 | +0.17 |
| `cross16` | -0.04 | +0.00 | -0.00 | +1.00 | -0.03 | -0.01 | +0.09 |
| `room` | -0.74 | -0.67 | +0.41 | -0.03 | +1.00 | +0.02 | +0.09 |
| `vol_ratio` | +0.02 | +0.01 | -0.05 | -0.01 | +0.02 | +1.00 | -0.02 |
| `slope50` | -0.17 | -0.12 | +0.17 | +0.09 | +0.09 | -0.02 | +1.00 |

> Values near ±1.0 indicate redundant proxies; values near 0 indicate independent information.


## 2. Conditional Economic Tables (break_distance_atr Q1 × other features)

**Tight-break region** (`break_distance_atr` ≤ bottom 20%): n=224, Mean=-0.00 bps, Gross>30=21.4%

### Within tight-break: `candle_body_atr` quintile split
| Q | Range | n | Mean @72 | >30% | >40% | Net+ |
|:-:|:------|--:|---------:|-----:|-----:|-----:|
| 1 | 0.0002–0.0447 | 44 | +4.18 | 27.3% | 20.4% | 38.6% |
| 2 | 0.0460–0.1059 | 44 | +1.18 | 20.4% | 18.2% | 25.0% |
| 3 | 0.1069–0.1622 | 44 | +6.62 | 29.5% | 15.9% | 36.4% |
| 4 | 0.1622–0.2314 | 44 | +0.05 | 18.2% | 11.4% | 36.4% |
| 5 | 0.2333–0.4677 | 48 | -11.02 | 12.5% | 6.2% | 27.1% |

### Within tight-break: `ema9_ema21_distance` quintile split
| Q | Range | n | Mean @72 | >30% | >40% | Net+ |
|:-:|:------|--:|---------:|-----:|-----:|-----:|
| 1 | -8.1378–-4.0002 | 44 | -1.31 | 22.7% | 13.6% | 36.4% |
| 2 | -3.9892–-2.6289 | 44 | -1.52 | 18.2% | 11.4% | 29.5% |
| 3 | -2.6200–-1.6759 | 44 | -4.39 | 18.2% | 13.6% | 29.5% |
| 4 | -1.6572–-0.8894 | 44 | +3.69 | 27.3% | 13.6% | 34.1% |
| 5 | -0.8848–-0.0041 | 48 | +3.23 | 20.8% | 18.8% | 33.3% |

### Within tight-break: `recent_cross_count_16bars` quintile split
| Q | Range | n | Mean @72 | >30% | >40% | Net+ |
|:-:|:------|--:|---------:|-----:|-----:|-----:|
| 1 | 3.0000–6.0000 | 44 | +1.05 | 20.4% | 15.9% | 36.4% |
| 2 | 6.0000–8.0000 | 44 | -1.13 | 25.0% | 20.4% | 29.5% |
| 3 | 8.0000–8.0000 | 44 | +4.03 | 18.2% | 13.6% | 29.5% |
| 4 | 8.0000–10.0000 | 44 | +5.42 | 25.0% | 15.9% | 43.2% |
| 5 | 10.0000–14.0000 | 48 | -8.59 | 18.8% | 6.2% | 25.0% |

### Within tight-break: `room_to_structure_bps` quintile split
| Q | Range | n | Mean @72 | >30% | >40% | Net+ |
|:-:|:------|--:|---------:|-----:|-----:|-----:|
| 1 | 27.9573–50.3833 | 44 | -2.30 | 20.4% | 11.4% | 31.8% |
| 2 | 50.4880–57.7095 | 44 | +1.11 | 13.6% | 9.1% | 29.5% |
| 3 | 58.1494–67.5373 | 44 | +4.81 | 20.4% | 15.9% | 31.8% |
| 4 | 67.8345–79.5986 | 44 | -9.67 | 13.6% | 9.1% | 25.0% |
| 5 | 79.9685–135.9690 | 48 | +5.54 | 37.5% | 25.0% | 43.8% |

### Within tight-break: `volume_ratio` quintile split
| Q | Range | n | Mean @72 | >30% | >40% | Net+ |
|:-:|:------|--:|---------:|-----:|-----:|-----:|
| 1 | 0.0160–0.4152 | 44 | +10.29 | 31.8% | 25.0% | 40.9% |
| 2 | 0.4204–0.8259 | 44 | -5.90 | 11.4% | 9.1% | 20.4% |
| 3 | 0.8275–1.1071 | 44 | -3.77 | 22.7% | 18.2% | 31.8% |
| 4 | 1.1254–1.4916 | 44 | +1.28 | 20.4% | 11.4% | 29.5% |
| 5 | 1.5053–2.4441 | 48 | -1.74 | 20.8% | 8.3% | 39.6% |


## 3. Per-Symbol Stability (break_distance_atr tight-break)

| Symbol | Baseline n | Baseline Gross>30 | Tight-break n | Tight-break Gross>30 | Delta |
|:-------|:----------:|:-----------------:|:-------------:|:--------------------:|:-----:|
| BNB | 345 | 9.0% | 72 | 13.9% | +4.9% |
| BTC | 405 | 8.6% | 74 | 24.3% | +15.7% |
| ETH | 367 | 9.5% | 78 | 25.6% | +16.1% |

## 4. Per-Side Stability (break_distance_atr tight-break)

| Side | Baseline n | Baseline Gross>30 | Tight-break n | Tight-break Gross>30 | Delta |
|:-----|:----------:|:-----------------:|:-------------:|:--------------------:|:-----:|
| BUY | 18 | 22.2% | 14 | 21.4% | -0.8% |
| SELL | 1099 | 8.8% | 210 | 21.4% | +12.6% |

## 5. Whipsaw Monotonicity Test (recent_cross_count_16bars)

| Q | Cross-count range | n | Mean @72 | Gross>30 | Gross>40 | Net+ |
|:-:|:------------------|--:|---------:|:--------:|:--------:|:----:|
| 1 | 2.0–6.0 | 223 | -20.18 | 10.8% | 6.3% | 18.4% |
| 2 | 6.0–8.0 | 223 | -22.36 | 6.7% | 4.9% | 15.2% |
| 3 | 8.0–9.0 | 223 | -18.25 | 10.3% | 6.3% | 17.9% |
| 4 | 9.0–10.0 | 223 | -22.78 | 9.0% | 4.5% | 17.5% |
| 5 | 10.0–14.0 | 225 | -25.57 | 8.4% | 4.4% | 15.1% |

Kendall-τ = -0.400, p = 0.483  

**Verdict**: `WHIPSAW_PLAUSIBLE_NOT_PRIMARY`

> τ < −0.3 with p < 0.10 → monotone decline → WHIPSAW_CONTEXT_CONFIRMED  

> otherwise → OVEREXTENSION_CONTEXT primary, whipsaw plausible


## 6. Feature Redundancy Summary

| Feature | Independent of break_dist? | Adds edge inside tight-break region? |
|:--------|:---------------------------:|:------------------------------------:|
| `candle_body_atr` | NO (ρ=+0.84) | YES (spread=17.0%) |
| `ema9_ema21_distance` | NO (ρ=-0.68) | YES (spread=9.1%) |
| `recent_cross_count_16bars` | YES (ρ=-0.04) | NO (spread=6.8%) |
| `room_to_structure_bps` | NO (ρ=-0.74) | YES (spread=23.9%) |
| `volume_ratio` | YES (ρ=+0.02) | YES (spread=20.5%) |
