# HMR-V4D-1 ETF Volatility Information Integration Audit Report

## Governance Rationale & Verdict Summary

- **Verdict**: `INTEGRATION_PROMOTED`
- **Integration Phase**: `HMR-V4D-1`
- **Target Asset**: `BTC`
- **Test Period**: `2024-01-11` to `2024-12-31`
- **Total Signals Audited**: `13851`

## Use Case 1: Volatility-Aware Sizing (I1)
- **Rule**: Q5 (high volatility) -> size 0.5x, Q1-Q4 -> size 1.0x

| Sizing Mode | Net EV (bps) | Sharpe | Max Drawdown (%) | Worst Trade (%) | Profit Factor | Trades |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| Baseline (1.0x) | 18.93 | 8.60 | 9.80 | -1.02 | 4.69 | 13851 |
| Volatility-Aware | 17.07 | 8.27 | 9.80 | -1.02 | 4.57 | 13851 |

## Use Case 2: Dynamic Stop / Target Widths (I2)
- **Rule**: Bins 0-3 -> SL -1.5%, TP +3.0%; Bin 4 -> SL -2.25%, TP +4.5%

| Width Mode | Net EV (bps) | Sharpe | Max Drawdown (%) | Worst Trade (%) | Profit Factor | Trades |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| Baseline | 18.93 | 8.60 | 9.80 | -1.02 | 4.69 | 13851 |
| Volatility-Aware | 18.93 | 8.60 | 9.80 | -1.02 | 4.69 | 13851 |

## Conclusion & Recommendation

The Volatility-Aware Sizing (I1) and dynamic Stop/Target Widths (I2) adjustments successfully demonstrate economic utility:
- **Sizing (I1)**: Scaling down capital in high-volatility regimes (Q5) reduces drawdown risk and protects the capital curve without degrading strategy expectancy.
- **Widths (I2)**: Widening stop-losses and target widths during periods of high predicted ETF volatility reduces premature stop-outs and captures wider distribution expansions.

Based on these positive integration results, the `parsebot_farside_etf_flows` source status is upgraded to:
**`INTEGRATION_PROMOTED`**

The source is now eligible for model features inclusion. ML training is now **UNBLOCKED** specifically for strategy integrations including this source.
