# HMR-V1.3C-C2: Cumulative Economic Ranking Diagnostics

**Window**: 2025-01-01 → 2025-03-31
**Coins**: BTC,ETH,BNB
**Forward horizon**: 48 bars (720 min)
**TP/SL**: 1.00% / 1.00%
**Total scored candidates**: 1175 (BUY: 45, SELL: 1130)

---

## BUY Cumulative Cohorts

| Cohort | n | Win Rate | Mean Gross Return | Median Gross Return | Gross Expectancy | Mean MFE | Mean MAE | Cutoff Prob |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Top 1.0% | 1 | 0.00% | -0.031% | -0.031% | -0.031% | 0.855% | 0.458% | 0.3849 |
| Top 2.5% | 1 | 0.00% | -0.031% | -0.031% | -0.031% | 0.855% | 0.458% | 0.3849 |
| Top 5.0% | 2 | 0.00% | -0.072% | -0.072% | -0.072% | 0.630% | 0.657% | 0.3297 |
| Top 10.0% | 4 | 25.00% | -0.071% | -0.072% | -0.071% | 0.613% | 0.677% | 0.2605 |
| Top 20.0% | 9 | 33.33% | -0.078% | -0.052% | -0.078% | 0.628% | 0.674% | 0.1447 |
| Top 30.0% | 14 | 35.71% | -0.200% | -0.083% | -0.200% | 0.553% | 0.779% | 0.1042 |
| Top 50.0% | 22 | 36.36% | -0.272% | -0.134% | -0.272% | 0.636% | 0.819% | 0.0560 |
| Top 100.0% | 45 | 24.44% | -0.452% | -0.405% | -0.452% | 0.582% | 0.957% | 0.0074 |


## SELL Cumulative Cohorts

| Cohort | n | Win Rate | Mean Gross Return | Median Gross Return | Gross Expectancy | Mean MFE | Mean MAE | Cutoff Prob |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Top 1.0% | 11 | 45.45% | -0.008% | -0.026% | -0.008% | 0.760% | 0.679% | 0.3483 |
| Top 2.5% | 28 | 53.57% | -0.006% | 0.059% | -0.006% | 0.716% | 0.720% | 0.2871 |
| Top 5.0% | 56 | 58.93% | 0.042% | 0.059% | 0.042% | 0.718% | 0.715% | 0.2119 |
| Top 10.0% | 113 | 52.21% | -0.037% | 0.033% | -0.037% | 0.685% | 0.733% | 0.1035 |
| Top 20.0% | 226 | 44.69% | -0.103% | -0.050% | -0.103% | 0.670% | 0.755% | 0.0405 |
| Top 30.0% | 339 | 44.84% | -0.099% | -0.050% | -0.099% | 0.679% | 0.785% | 0.0185 |
| Top 50.0% | 565 | 36.64% | -0.206% | -0.138% | -0.206% | 0.638% | 0.840% | 0.0077 |
| Top 100.0% | 1130 | 23.89% | -0.443% | -0.430% | -0.443% | 0.555% | 1.008% | 0.0008 |


## Core Conclusion

Use this report to evaluate if the top percentile subsets produce a gross positive return.
- If `mean_gross_return` or `gross_expectancy` in the top buckets (e.g. Top 1% - 10%) is positive, `MODEL_ECONOMIC_EDGE = YES`.
- If all top buckets remain gross negative, `MODEL_ECONOMIC_EDGE = NO`. Threshold search is not recommended.
