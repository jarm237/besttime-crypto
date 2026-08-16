# HMR-V4C-2B Stablecoin Liquidity Feature Audit Report

## Governance Rationale & Verdict Summary

- **Program**: `HMR-V4C-2B`
- **Source**: `defillama_stablecoin_supply`
- **Observation Count**: `210528` (15m bars)
- **Unique Daily Stablecoin States**: `2190` (deduplicated statistical units)
- **Model Training**: `BLOCKED`

### 1. Directional Audit (H5-D)

| Feature | Overall Verdict | Best Horizon | Max Conditioned Spread |
| :--- | :--- | :---: | :---: |
| `SC1_stablecoin_supply_growth_7d` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps |
| `SC2_stablecoin_supply_growth_30d` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps |
| `SC3_net_issuance_7d_normalized` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps |
| `SC4_net_issuance_percentile_90d` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps |

### 2. Volatility Audit (H5-V)

| Feature | Overall Verdict | Best Horizon | Max Spread (Q5-Q1) | Bootstrap P |
| :--- | :--- | :---: | :---: | :---: |
| `SC1_stablecoin_supply_growth_7d` | **REJECT_NO_INFORMATION** | `None` | 39.6070 bps | 0.0% |
| `SC2_stablecoin_supply_growth_30d` | **REJECT_NO_INFORMATION** | `None` | 39.3644 bps | 0.0% |
| `SC3_net_issuance_7d_normalized` | **REJECT_NO_INFORMATION** | `None` | 39.5699 bps | 0.0% |
| `SC4_net_issuance_percentile_90d` | **REJECT_NO_INFORMATION** | `None` | 0.3388 bps | 61.5% |

### 3. Risk State Audit (H5-R)

| Feature | Overall Verdict | Target MAE | RS1 (State Pass) | Baseline EV | Vetoed EV | RS2 (Utility) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `SC1_stablecoin_supply_growth_7d` | **REJECT_NO_INFORMATION** | `7d MAE` | **False** | 26.71 bps | 26.53 bps | **False** |
| `SC3_net_issuance_7d_normalized` | **REJECT_NO_INFORMATION** | `7d MAE` | **False** | 26.71 bps | 26.71 bps | **False** |

## Conclusion & Next Steps

If a feature has been promoted under any information class, it is eligible for strategy-level integration:
- **PROMOTE_DIRECTIONAL_INFORMATION**: Eligible as signal/predictor.
- **PROMOTE_VOLATILITY_INFORMATION**: Eligible for sizing/target width scaling.
- **PROMOTE_RISK_STATE_INFORMATION**: Eligible for regime veto/gating.

Model training remains strictly **BLOCKED**.
