# HMR-V1.3B: Diagnostic Ablation Results Matrix

| Scenario | Trades | BUY | SELL | Gross PnL ($) | Net PnL ($) | Win Rate | Profit Factor | MaxDD |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CURRENT_CLEAN | 0 | 0 | 0 | — | — | — | — | — |
| TECHNICAL_ONLY | 379 | 40 | 339 | -803.12 | -1,975.81 | 12.66% | 0.054 | 20.17% |
| NO_CALIBRATION | 0 | 0 | 0 | — | — | — | — | — |
| NO_META | 0 | 0 | 0 | — | — | — | — | — |
| TECHNICAL_LONG_ONLY | 37 | 37 | 0 | -80.12 | -203.35 | 13.51% | 0.051 | 2.32% |
| TECHNICAL_SHORT_ONLY | 329 | 0 | 329 | -717.14 | -1,743.94 | 13.68% | 0.060 | 17.86% |
| NO_CALIB_LONG_ONLY | 0 | 0 | 0 | — | — | — | — | — |
| NO_CALIB_SHORT_ONLY | 0 | 0 | 0 | — | — | — | — | — |

## Exit Decomposition Metrics

| Scenario | BAD_ENTRY | COST_DESTROYED | EDGE_NOT_CAPTURED | GOOD_CAPTURE | Mean MFE | Mean MAE | Capture Ratio |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CURRENT_CLEAN | — | — | — | — | — | — | — |
| TECHNICAL_ONLY | 265 | 66 | 0 | 48 | 0.72% | -0.79% | -41686.81% |
| NO_CALIBRATION | — | — | — | — | — | — | — |
| NO_META | — | — | — | — | — | — | — |
| TECHNICAL_LONG_ONLY | 24 | 8 | 0 | 5 | 0.75% | -0.78% | -41148.88% |
| TECHNICAL_SHORT_ONLY | 224 | 60 | 0 | 45 | 0.75% | -0.82% | -37793.56% |
| NO_CALIB_LONG_ONLY | — | — | — | — | — | — | — |
| NO_CALIB_SHORT_ONLY | — | — | — | — | — | — | — |
