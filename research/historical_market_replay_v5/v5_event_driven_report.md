# HMR-V5: Event-Driven Self-Financing Replay Audit Report

> **Timestamp**: `2026-11-01T17:42:57.364494+00:00` | **Taxonomy**: `HISTORICAL_SIMULATION`

## 1. Evidence Taxonomy & Operational Scope
- **Category**: `HISTORICAL_SIMULATION`
- **Scope**: Historical candle-driven simulation of E4 path-aware exits and P4 capacity serialization across 2024-H2 under canonical half-open interval `[2024-07-02, 2025-01-01)` and `EXCLUDE_CROSS_BOUNDARY_OUTCOME`.
- **Explicit Warning**: This audit uses historical backtesting. It does **NOT** constitute observed demo fills or live performance.

## 2. Root Cause of Retracted Flawed Metrics
Previous reports (e.g. Sharpe 126.81, Max Drawdown 0.00%, Total Return +1,116.31%) relied on an unconstrained daily return summation bug in run_p4_replay_metrics: daily_returns[exit_day] += net_trade_pnl * 0.10. Multiple trades closing on the same day artificially compressed daily volatility and accumulated leverage beyond 100%, booking PnL without cash locking, margin tracking, or continuous mark-to-market drawdown.

## 3. Self-Financing Capital Accounting Parameters
- **Initial Capital**: `$10,000.00`
- **Allocation Per Trade**: `25.0%` of available equity
- **Max Concurrent Positions**: `3` (Max 1 per asset)
- **Cost Model**: `5.0 bps` fee + `2.0 bps` slippage per leg (`14.0 bps` roundtrip)
- **Sharpe Annualization**: `sqrt(365)` based on end-of-day daily equity series

## 4. Empirical Historical Replay Results

| Metric | Flawed Historical Claim | True Replay (Control) | True Replay (Treatment S3) | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Executed Trades** | `7,211` | `502` | `0` | Corrected |
| **Win Rate** | `73.2%` | `38.45%` | `0.00%` | Corrected |
| **Profit Factor** | `N/A` | `0.5137` | `0.0000` | Corrected |
| **Total Net PnL** | `+1,116.31%` | `-15.34%` | `0.00%` | **RETRACTED** |
| **Final Equity** | `N/A` | `$8,466.38` | `$10,000.00` | Corrected |
| **Max Drawdown** | `0.00%` | `15.47%` | `0.00%` | **RETRACTED** |
| **Daily Sharpe** | `126.81` | `-10.89` | `0.00` | **RETRACTED** |
| **Expectancy (bps)** | `+26.89 bps` | `-13.14 bps` | `0.00 bps` | Corrected |

## 5. Audit Conclusion
The previous claims of Sharpe 126.81 and 0% Max Drawdown are formally retracted. Under realistic event-driven capital accounting and transaction friction (14 bps roundtrip), the baseline historical strategy suffers negative expectancy during 2024-H2.
