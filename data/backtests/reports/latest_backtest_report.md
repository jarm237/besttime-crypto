# Institutional Backtesting & Validation Report

**Run ID**: e8202f6a  
**Generated At**: 2026-07-08T22:54:05.120444  

## Strategy Approval Gate Status
Approval Status: **REJECTED**

| Rule | Metric Value | Requirement | Status |
| --- | --- | --- | --- |
| Sharpe Ratio | -10.80 | >=1.0 | ❌ FAIL |
| Profit Factor | 0.00 | >=1.3 | ❌ FAIL |
| Max Drawdown | 89.23% | <=0.1 | ❌ FAIL |
| Total Trades | 688 | >=100 | ✅ PASS |
| Cost Drag | 746.84% | <=0.35 | ❌ FAIL |
| MC Prob of Loss | 100.0% | <=0.25 | ❌ FAIL |
| MC Prob DD > 10% | 100.0% | <=0.2 | ❌ FAIL |
| Profitable Regimes | 0 | >=3 | ❌ FAIL |

## Core Performance Metrics
- **Total Return**: -89.19%
- **Annualized Return**: -47.11%
- **Annual Volatility**: 5.87%
- **Sharpe Ratio**: -10.80
- **Sortino Ratio**: -9.84
- **Max Drawdown**: 89.23%

## Execution & Transaction Cost drag
- **Total Costs Paid**: $9161.57
- **Cost Drag (pct of gross PnL)**: 746.84%
- **Average Fee paid (bps)**: 5.0
- **Average Spread paid (bps)**: 2.0
- **Average Slippage paid (bps)**: 17.2
- **Average Latency (ms)**: 250.0

## Monte Carlo Robustness
- **5th Percentile Return**: -81.81%
- **50th Percentile Return**: -79.42%
- **95th Percentile Return**: -77.00%
- **Risk of Ruin (50% DD)**: 100.0%
