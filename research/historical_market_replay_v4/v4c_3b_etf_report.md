# HMR-V4C-3B ETF / Institutional Flows Feature Audit Report

## Governance Rationale & Verdict Summary

- **Program**: `HMR-V4C-3B`
- **Source**: `parsebot_farside_etf_flows`
- **Observation Count**: `210528` (15m bars)
- **Unique Daily Publication States**: `2190` (deduplicated publication units)
- **Eligible States Period B**: `546`
- **Eligible States Period C**: `552`
- **Model Training**: `BLOCKED`

## Contemporaneous Contamination Audit

| Correlation Metric | Value |
| :--- | :---: |
| `corr_flow_btc_same_trade_day_return` | -0.0392 |
| `corr_flow_btc_prev_24h_return` | -0.0721 |
| `corr_flow_btc_future_24h_return` | 0.0078 |
| `corr_flow_btc_future_72h_return` | 0.0475 |
| `corr_flow_btc_future_7d_return` | 0.1224 |

### 1. Directional Audit (H5-D)

| Feature | Overall Verdict | Best Horizon | Max Conditioned Spread | Spillover (ETH/BNB) |
| :--- | :--- | :---: | :---: | :---: |
| `ETF1_total_net_flow_usd` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps | ETH: unsupported, BNB: supported |
| `ETF2_ex_gbtc_net_flow_usd` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps | ETH: unsupported, BNB: supported |
| `ETF3_net_flow_as_pct_aum` | **REJECT_FEATURE_PROVENANCE** | `None` | N/A | N/A |
| `ETF4_rolling_flow_zscore_20d` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps | ETH: supported, BNB: supported |
| `ETF5_cumulative_net_flow_5d` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps | ETH: unsupported, BNB: supported |

### 2. Volatility Audit (H5-V)

| Feature | Overall Verdict | Best Horizon | Max Spread (Q5-Q1) | Bootstrap P |
| :--- | :--- | :---: | :---: | :---: |
| `ETF1_total_net_flow_usd` | **REJECT_NO_INFORMATION** | `None` | 0.2369 bps | 69.0% |
| `ETF2_ex_gbtc_net_flow_usd` | **PROMOTE_VOLATILITY_INFORMATION** | `72h` | 0.9108 bps | 100.0% |
| `ETF3_net_flow_as_pct_aum` | **REJECT_FEATURE_PROVENANCE** | `None` | N/A | N/A |
| `ETF4_rolling_flow_zscore_20d` | **REJECT_NO_INFORMATION** | `None` | -0.1152 bps | 25.0% |
| `ETF5_cumulative_net_flow_5d` | **REJECT_NO_INFORMATION** | `None` | 0.1941 bps | 66.5% |

### 3. Risk State Audit (H5-R)

| Feature | Overall Verdict | Target MAE | RS1 (State Pass) | Baseline EV | Vetoed EV | RS2 (Utility) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `ETF1_total_net_flow_usd` | **REJECT_NO_INFORMATION** | `7d MAE` | **False** | 18.84 bps | 20.68 bps | **True** |
| `ETF2_ex_gbtc_net_flow_usd` | **REJECT_NO_INFORMATION** | `7d MAE` | **False** | 18.84 bps | 20.46 bps | **True** |

## Conclusion & Next Steps

If a feature has been promoted, it can be integrated into the trading framework under status **`INFORMATION_SOURCE_PROMOTED`**:
- **PROMOTE_BTC_DIRECTIONAL_INFORMATION**: Eligible for directional signal scaling.
- **PROMOTE_VOLATILITY_INFORMATION**: Eligible for sizing/target width scaling.
- **PROMOTE_BTC_RISK_STATE_INFORMATION**: Eligible for regime long-veto gating.

Model training remains strictly **BLOCKED**.
