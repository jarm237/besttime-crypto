# HMR-V4B-2B-r1 Perpetual Spot Premium Historical Information Audit Report

## Governance Contract Status

- **Program**: `HMR-V4B-2B-r1`
- **Source**: `binance_premium_index_klines`
- **Information Family**: `PERP_PREMIUM_DISLOCATION`
- **Provenance**: `MARKET_OBSERVED`
- **Provenance Gate**: `PASS`
- **Model Training**: `BLOCKED`

## Feature Verdicts Summaries

| Feature | Verdict | Best Horizon | Max Observed Spread | Horizon of Max | Economic Floor Ratio |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `perp_premium_level` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.6740 bps | `48h` | 3.37% |
| `perp_premium_change_4h` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.4974 bps | `8h` | 4.97% |
| `perp_premium_change_24h` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.5810 bps | `18h` | 3.87% |
| `perp_premium_percentile_30d` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | -1.2048 bps | `48h` | 6.02% |

## Detailed Horizons Gates Report
### Feature: `perp_premium_level`

| Horizon | Economic | Support | Funding Redundancy | Endogenous Proxy | Asset Robust. | Monthly Stab. | Bootstrap CI | Tail Domination |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `8h` | **FAIL** | **PASS** | **FAIL** | **PASS** | **FAIL** | **FAIL** | **FAIL** | **PASS** |
| `18h` | **FAIL** | **PASS** | **FAIL** | **PASS** | **PASS** | **FAIL** | **FAIL** | **FAIL** |
| `48h` | **FAIL** | **PASS** | **FAIL** | **PASS** | **FAIL** | **FAIL** | **FAIL** | **PASS** |

### Feature: `perp_premium_change_4h`

| Horizon | Economic | Support | Funding Redundancy | Endogenous Proxy | Asset Robust. | Monthly Stab. | Bootstrap CI | Tail Domination |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `8h` | **FAIL** | **PASS** | **FAIL** | **PASS** | **PASS** | **PASS** | **FAIL** | **PASS** |
| `18h` | **FAIL** | **PASS** | **FAIL** | **PASS** | **FAIL** | **FAIL** | **FAIL** | **PASS** |
| `48h` | **FAIL** | **PASS** | **FAIL** | **PASS** | **PASS** | **FAIL** | **FAIL** | **PASS** |

### Feature: `perp_premium_change_24h`

| Horizon | Economic | Support | Funding Redundancy | Endogenous Proxy | Asset Robust. | Monthly Stab. | Bootstrap CI | Tail Domination |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `8h` | **FAIL** | **PASS** | **FAIL** | **PASS** | **FAIL** | **PASS** | **FAIL** | **PASS** |
| `18h` | **FAIL** | **PASS** | **FAIL** | **PASS** | **FAIL** | **FAIL** | **FAIL** | **PASS** |
| `48h` | **FAIL** | **PASS** | **FAIL** | **PASS** | **PASS** | **PASS** | **FAIL** | **PASS** |

### Feature: `perp_premium_percentile_30d`

| Horizon | Economic | Support | Funding Redundancy | Endogenous Proxy | Asset Robust. | Monthly Stab. | Bootstrap CI | Tail Domination |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `8h` | **FAIL** | **PASS** | **FAIL** | **FAIL** | **FAIL** | **FAIL** | **FAIL** | **PASS** |
| `18h` | **FAIL** | **PASS** | **FAIL** | **PASS** | **FAIL** | **FAIL** | **FAIL** | **PASS** |
| `48h` | **FAIL** | **PASS** | **FAIL** | **PASS** | **PASS** | **FAIL** | **FAIL** | **PASS** |

