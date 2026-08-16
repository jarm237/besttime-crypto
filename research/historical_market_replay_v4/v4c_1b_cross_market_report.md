# HMR-V4C-1B Cross-Market Risk Regime Audit Report

## Governance Rationale & Verdict Summary

- **Program**: `HMR-V4C-1B`
- **Source**: `cross_market_risk_regime`
- **Observation Count**: `210528` (15m bars)
- **Unique Daily Macro States**: `2193` (deduplicated statistical units)
- **Model Training**: `BLOCKED`

### 1. Directional Audit (H5-D)

| Feature | Overall Verdict | Best Horizon | Max Conditioned Spread |
| :--- | :--- | :---: | :---: |
| `CM1_VIX_percentile_60d` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps |
| `CM2_VIX_change_5d` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps |
| `CM3_SPX_return_5d` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps |
| `CM4_DXY_return_5d` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps |
| `CM5_US10Y_change_5d` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps |

### 2. Volatility Audit (H5-V)

| Feature | Overall Verdict | Best Horizon | Max Spread (Q5-Q1) | Bootstrap P |
| :--- | :--- | :---: | :---: | :---: |
| `vix_close` | **REJECT_NO_INFORMATION** | `None` | -0.0263 bps | 53.0% |
| `CM1_VIX_percentile_60d` | **REJECT_NO_INFORMATION** | `None` | 0.0640 bps | 48.5% |
| `CM2_VIX_change_5d` | **REJECT_NO_INFORMATION** | `None` | 1.2280 bps | 82.0% |
| `spx_rv_30d` | **REJECT_NO_INFORMATION** | `None` | 0.7346 bps | 57.5% |

### 3. Risk State Audit (H5-R)

| Feature | Overall Verdict | Target MAE | RS1 (State Pass) | Baseline EV | Vetoed EV | RS2 (Utility) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `vix_close` | **REJECT_NO_INFORMATION** | `18h MAE` | **False** | 23.18 bps | 22.96 bps | **False** |
| `CM4_DXY_return_5d` | **REJECT_NO_INFORMATION** | `18h MAE` | **False** | 23.18 bps | 24.38 bps | **True** |

## Conclusion & Next Steps

If a feature has been promoted under any information class, it is eligible for strategy-level integration:
- **PROMOTE_DIRECTIONAL_INFORMATION**: Eligible as signal/predictor.
- **PROMOTE_VOLATILITY_INFORMATION**: Eligible for sizing/target width scaling.
- **PROMOTE_RISK_STATE_INFORMATION**: Eligible for regime veto/gating.

Model training remains strictly **BLOCKED**.
