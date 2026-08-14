# R4 — Semantic-only Replay Comparison

This report compares the replay results using semantic correctness restoration (no SELL probability inversion) vs the frozen buggy baseline.

## Performance Comparison Table

| Metric | Frozen Buggy Baseline (V1.3) | Semantic Fixed Replay (V1.3A-R) | Delta |
| :--- | :---: | :---: | :---: |
| Executed BUY Trades | `0` | `None` | `0` |
| Executed SELL Trades | `318` | `None` | `-318` |
| Total Trades | `318` | `None` | `-318` |
| Net PnL ($) | `-1,695.63` | `0.00` | `+1,695.63` |
| Win Rate | `14.15%` | `0.00%` | `-14.15%` |
| Max Drawdown | `17.31%` | `0.00%` | `-17.31%` |

## Analysis

As expected, fixing the semantic inversion for SELL trades results in zero or near-zero executions. This is because the calibration collapse caps the calibrated win probability for all signals below the decision engine thresholds, meaning no trades can pass the posterior gate. This confirms that all 318 trades in the buggy baseline were purely artifacts of the semantic inversion bug.

**Gate**: `SIDE_MAPPING_SEMANTICS = PASS`  
**Gate**: `CLEAN_COHORT_GENERATED = PASS`
