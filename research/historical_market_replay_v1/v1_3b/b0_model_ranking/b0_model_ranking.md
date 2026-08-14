# HMR-V1.3B-B0: Threshold-Free Model Ranking Diagnostics

**Window**: 2025-01-01 → 2025-03-31
**Coins**: BTC,ETH,BNB
**Forward horizon**: 48 bars (720 min)
**TP/SL for outcome classification**: 1.00% / 1.00%
**Total technical candidates scored**: 1175

---

## ALL (n=1175, wins=281, base_rate=23.91%)

### Discrimination Metrics

| Metric | Raw Model | Calibrated |
| :--- | ---: | ---: |
| ROC-AUC | 0.7318 | 0.6158 |
| PR-AUC | 0.4223 | 0.3529 |
| Brier Score | 0.2124 | 0.2305 |
| Rank Corr (return) | 0.4883 | 0.2309 |

### Raw Probability Distribution
  min=0.0008  p25=0.0030  median=0.0083  p75=0.0308  max=0.4827  mean=0.0375  std=0.0718

### Calibrated Probability Distribution
  min=0.0000  p25=0.0000  median=0.0000  p75=0.0000  max=0.1667  mean=0.0102  std=0.0301

### Forward Return Distribution
  min=-1.000%  p25=-1.000%  median=-0.429%  p75=-0.027%  max=1.000%  mean=-0.443%

### Raw Model Quintile Analysis

| Quintile | Prob Range | N | Win Rate | Mean Gross Return | Mean MFE | Mean MAE |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| Q1 | [0.0008, 0.0023] | 235 | 4.26% | -0.854% | 0.431% | 1.360% |
| Q2 | [0.0023, 0.0053] | 235 | 14.89% | -0.577% | 0.493% | 1.064% |
| Q3 | [0.0053, 0.0122] | 235 | 20.00% | -0.467% | 0.540% | 0.975% |
| Q4 | [0.0124, 0.0435] | 235 | 36.60% | -0.196% | 0.657% | 0.870% |
| Q5 | [0.0435, 0.4827] | 235 | 43.83% | -0.123% | 0.661% | 0.760% |

### Calibrated Quintile Analysis

| Quintile | Prob Range | N | Win Rate | Mean Gross Return | Mean MFE | Mean MAE |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| Q1 | [0.0000, 0.0274] | 1135 | 22.91% | -0.459% | 0.551% | 1.016% |
| Q2 | [0.0534, 0.1667] | 40 | 52.50% | -0.006% | 0.697% | 0.712% |

---

## BUY (n=45, wins=11, base_rate=24.44%)

### Discrimination Metrics

| Metric | Raw Model | Calibrated |
| :--- | ---: | ---: |
| ROC-AUC | 0.6070 | 0.6578 |
| PR-AUC | 0.3367 | 0.3571 |
| Brier Score | 0.2079 | 0.2350 |
| Rank Corr (return) | 0.4041 | 0.3108 |

### Raw Probability Distribution
  min=0.0074  p25=0.0188  median=0.0534  p75=0.1169  max=0.3849  mean=0.0887  std=0.0928

### Calibrated Probability Distribution
  min=0.0000  p25=0.0000  median=0.0274  p75=0.0274  max=0.1667  mean=0.0264  std=0.0405

### Forward Return Distribution
  min=-1.000%  p25=-1.000%  median=-0.405%  p75=-0.031%  max=1.000%  mean=-0.452%

### Raw Model Quintile Analysis

| Quintile | Prob Range | N | Win Rate | Mean Gross Return | Mean MFE | Mean MAE |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| Q1 | [0.0074, 0.0112] | 9 | 22.22% | -0.716% | 0.610% | 1.132% |
| Q2 | [0.0161, 0.0345] | 9 | 11.11% | -0.572% | 0.574% | 1.124% |
| Q3 | [0.0416, 0.0799] | 9 | 11.11% | -0.621% | 0.443% | 0.977% |
| Q4 | [0.0846, 0.1322] | 9 | 44.44% | -0.274% | 0.657% | 0.876% |
| Q5 | [0.1447, 0.3849] | 9 | 33.33% | -0.078% | 0.628% | 0.674% |

### Calibrated Quintile Analysis

| Quintile | Prob Range | N | Win Rate | Mean Gross Return | Mean MFE | Mean MAE |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| Q1 | [0.0000, 0.0000] | 18 | 16.67% | -0.644% | 0.592% | 1.128% |
| Q2 | [0.0141, 0.0274] | 23 | 30.43% | -0.369% | 0.569% | 0.871% |
| Q3 | [0.0728, 0.1667] | 4 | 25.00% | -0.071% | 0.613% | 0.677% |

---

## SELL (n=1130, wins=270, base_rate=23.89%)

### Discrimination Metrics

| Metric | Raw Model | Calibrated |
| :--- | ---: | ---: |
| ROC-AUC | 0.7400 | 0.6282 |
| PR-AUC | 0.4354 | 0.3691 |
| Brier Score | 0.2126 | 0.2304 |
| Rank Corr (return) | 0.4993 | 0.2386 |

### Raw Probability Distribution
  min=0.0008  p25=0.0029  median=0.0077  p75=0.0262  max=0.4827  mean=0.0354  std=0.0701

### Calibrated Probability Distribution
  min=0.0000  p25=0.0000  median=0.0000  p75=0.0000  max=0.1667  mean=0.0095  std=0.0294

### Forward Return Distribution
  min=-1.000%  p25=-1.000%  median=-0.430%  p75=-0.027%  max=1.000%  mean=-0.443%

### Raw Model Quintile Analysis

| Quintile | Prob Range | N | Win Rate | Mean Gross Return | Mean MFE | Mean MAE |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| Q1 | [0.0008, 0.0023] | 226 | 4.42% | -0.863% | 0.432% | 1.370% |
| Q2 | [0.0023, 0.0050] | 226 | 14.16% | -0.582% | 0.485% | 1.070% |
| Q3 | [0.0050, 0.0114] | 226 | 19.47% | -0.464% | 0.531% | 0.975% |
| Q4 | [0.0114, 0.0403] | 226 | 36.73% | -0.203% | 0.658% | 0.869% |
| Q5 | [0.0405, 0.4827] | 226 | 44.69% | -0.103% | 0.670% | 0.755% |

### Calibrated Quintile Analysis

| Quintile | Prob Range | N | Win Rate | Mean Gross Return | Mean MFE | Mean MAE |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| Q1 | [0.0000, 0.1667] | 1130 | 23.89% | -0.443% | 0.555% | 1.008% |

---

## Interpretation Guide

### ROC-AUC
- **> 0.55**: Model has some discriminative ability
- **≈ 0.50**: No better than random — model has NO ranking edge
- **< 0.50**: Model is inversely predictive (worse than random)

### Quintile Pattern
- **Monotonic increase**: Model correctly ranks candidates (edge exists)
- **Flat**: Model has no useful discrimination
- **Inverted**: Model actively selects worse candidates

### Raw vs Calibrated
- If raw ROC-AUC > calibrated ROC-AUC: calibration destroys ranking
- If raw ≈ calibrated: calibration preserves (or doesn't help) ranking
- If calibrated > raw: calibration improves ranking (unusual but possible)

### Brier Score
- Lower is better
- Compare to baseline Brier = base_rate × (1 - base_rate)
- If model Brier > baseline Brier: model is worse than always predicting base rate
