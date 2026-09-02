# P8 Incident Source Trace — Canonical History Truncation Defect

## Trace Flow

```text
market candle fetch (Binance/CCXT/Storage)
    ↓ (e.g. 100 to 500 completed candles)
candles
    ↓
btc_scraper/analysis/core.py:analyze_market
    ↓ (LINE 871: history = candles[-8:])
analysis["history"]  [TRUNCATED TO 8 CANDLES]
    ↓
AutoTrader / evaluator caller
    ↓
btc_scraper/ml_engine/production_evaluator.py:evaluate_resolved_market
    ↓ (_observation_rows extracts analysis["history"] -> 8 rows)
canonical window creation (8 candles)
    ↓
btc_scraper/ml_engine/evaluation_contracts.py:canonical_entry_readiness_contract
    ↓ (WarmupContract requires max(9, 33, 73, 73) = 73 observations)
readiness evaluation -> WARMING_UP / INSUFFICIENT_CANONICAL_HISTORY
```

## Root Cause Summary
- `btc_scraper/analysis/core.py` at line 871 hardcodes `for c in candles[-8:]:` when populating `analysis["history"]`.
- `btc_scraper/ml_engine/evaluation_contracts.py` defines readiness requirements based on features `return_8`, `return_32`, `return_72`, `abs_move_72`, where `canonical_readiness_minimum_observations()` evaluates to `73`.
- `production_evaluator.py` passes `analysis["history"]` (8 observations) to `WarmupContract.diagnose()`.
- Because `8 < 73` unconditionally, 100% of execution attempts (522/522) fail closed with `INSUFFICIENT_CANONICAL_HISTORY`.

## Evidence
- `R0_INCIDENT_EVIDENCE_FREEZE = PASS`
