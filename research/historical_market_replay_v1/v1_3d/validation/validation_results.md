# HMR-V1.3D-D5: Out-of-Sample Validation Report

**Candidate Policy Configuration**:
- Gating: raw model probabilities (use_raw_model=True)
- Gating Thresholds: BUY >= 0.50, SELL >= 0.21
- Meta Gating: meta_threshold >= 0.21, min_ev_pct >= -1.000

## Performance Across Epochs

| Window | Dates | Trades | BUY | SELL | Gross PnL ($) | Net PnL ($) | Win Rate | Profit Factor | MaxDD |
| :--- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DISCOVERY | 2025-01-01 → 2025-03-31 | 50 | 5 | 45 | -83.77 | -250.48 | 14.0% | 0.041 | 3.0% |
| VALIDATION | 2025-04-01 → 2025-06-30 | 43 | 5 | 38 | -28.37 | -171.70 | 14.0% | 0.107 | 2.1% |
| UNTOUCHED_TEST | 2025-07-01 → 2025-09-30 | 48 | 10 | 38 | -145.50 | -305.52 | 12.5% | 0.045 | 3.3% |

## Core Conclusion
- **Validation Check**: Check if validation and untouched test windows yield positive net expectancy.
- If performance degrades to significant loss out-of-sample, the frozen candidate is not robust.
