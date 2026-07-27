# 08 Backtesting And Validation

Status: requires remediation.

## Positive Findings

- `btc_scraper/backtesting` contains config, engine, costs, slippage, latency, walk-forward, purged k-fold, embargo, monte-carlo, stress-test and report builder modules.
- There are many scripts for threshold sweep, hard reject sweep, walk-forward, monte-carlo, stress tests, and report generation.
- Backtesting tests exist by filename.

## Gaps

- `scripts/backtest_eval.py` indentation compile error at line 165 has been fixed.
- Need proof that default fill is next tradable bar or clearly documented execution policy.
- Need runtime/backtest shared strategy logic map.
- Need explicit bias checks for same-bar execution, MTF alignment, label leakage, fees/funding/slippage and intrabar SL/TP ordering.

## Classification

`REQUIRES_REMEDIATION`; compile blocker is closed, but realism/parity proof remains open.
