# HMR-V4B-4B Aggressive Trade Flow Feature Audit Report

## Governance Rationale & Verdict Summary

- **Program**: `HMR-V4B-4B`
- **Source**: `binance_um_trade_flow`
- **Information Family**: `MICROSTRUCTURE_FLOW`
- **Provenance Status**: `MARKET_OBSERVED`
- **Model Training**: `BLOCKED`

### Overall Feature Verdicts Table

| Feature | Overall Verdict | Best Horizon | Max Conditioned Spread |
| :--- | :--- | :---: | :---: |
| `TF1_taker_imbalance_15m` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps |
| `TF2_taker_imbalance_1h` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps |
| `TF3_signed_notional_zscore` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps |
| `TF4_aggressive_volume_percentile_30d` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps |
| `TF5_flow_acceleration_1h` | **REJECT_NO_ECONOMIC_INFORMATION** | `None` | 0.0000 bps |

## Detailed Horizon Gates Status

### Feature: `TF1_taker_imbalance_15m`

| Horizon | Raw Spread | R1 (Period) | R2 (Breadth) | R3 (Boot. P) | R4 (Months) | R5 (Winsor.) | Incremental | Verdict |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `8h` | 0.73 bps | **PASS** | **PASS** | 95.5% | 8/12 | 0.73 bps | 0.00 bps | **REJECT_NO_ECONOMIC_INFORMATION** |
| `18h` | 0.55 bps | **FAIL** | **PASS** | 91.0% | 8/12 | 0.55 bps | 0.00 bps | **REJECT_NO_ECONOMIC_INFORMATION** |
| `48h` | 0.13 bps | **FAIL** | **PASS** | 62.0% | 6/12 | 0.13 bps | 0.00 bps | **REJECT_NO_ECONOMIC_INFORMATION** |

### Feature: `TF2_taker_imbalance_1h`

| Horizon | Raw Spread | R1 (Period) | R2 (Breadth) | R3 (Boot. P) | R4 (Months) | R5 (Winsor.) | Incremental | Verdict |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `8h` | -0.25 bps | **FAIL** | **FAIL** | 31.0% | 6/12 | -0.25 bps | 0.00 bps | **REJECT_NO_ECONOMIC_INFORMATION** |
| `18h` | 0.17 bps | **FAIL** | **FAIL** | 69.5% | 9/12 | 0.17 bps | 0.00 bps | **REJECT_NO_ECONOMIC_INFORMATION** |
| `48h` | 1.02 bps | **FAIL** | **PASS** | 90.5% | 9/12 | 1.03 bps | 0.00 bps | **REJECT_NO_ECONOMIC_INFORMATION** |

### Feature: `TF3_signed_notional_zscore`

| Horizon | Raw Spread | R1 (Period) | R2 (Breadth) | R3 (Boot. P) | R4 (Months) | R5 (Winsor.) | Incremental | Verdict |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `8h` | 1.11 bps | **PASS** | **PASS** | 100.0% | 9/12 | 1.10 bps | 0.00 bps | **REJECT_NO_ECONOMIC_INFORMATION** |
| `18h` | 1.05 bps | **PASS** | **PASS** | 100.0% | 8/12 | 1.04 bps | 0.00 bps | **REJECT_NO_ECONOMIC_INFORMATION** |
| `48h` | -0.45 bps | **FAIL** | **FAIL** | 22.5% | 5/12 | -0.45 bps | 0.00 bps | **REJECT_NO_ECONOMIC_INFORMATION** |

### Feature: `TF4_aggressive_volume_percentile_30d`

| Horizon | Raw Spread | R1 (Period) | R2 (Breadth) | R3 (Boot. P) | R4 (Months) | R5 (Winsor.) | Incremental | Verdict |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `8h` | 0.24 bps | **FAIL** | **PASS** | 59.5% | 5/12 | 0.24 bps | 0.00 bps | **REJECT_NO_ECONOMIC_INFORMATION** |
| `18h` | 0.39 bps | **FAIL** | **PASS** | 60.5% | 5/12 | 0.39 bps | 0.00 bps | **REJECT_NO_ECONOMIC_INFORMATION** |
| `48h` | 2.16 bps | **FAIL** | **PASS** | 88.5% | 7/12 | 2.16 bps | 0.00 bps | **REJECT_NO_ECONOMIC_INFORMATION** |

### Feature: `TF5_flow_acceleration_1h`

| Horizon | Raw Spread | R1 (Period) | R2 (Breadth) | R3 (Boot. P) | R4 (Months) | R5 (Winsor.) | Incremental | Verdict |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `8h` | 0.12 bps | **FAIL** | **FAIL** | 63.0% | 6/12 | 0.12 bps | 0.00 bps | **REJECT_NO_ECONOMIC_INFORMATION** |
| `18h` | 0.23 bps | **PASS** | **PASS** | 68.0% | 7/12 | 0.23 bps | 0.00 bps | **REJECT_NO_ECONOMIC_INFORMATION** |
| `48h` | -0.02 bps | **FAIL** | **FAIL** | 47.5% | 6/12 | -0.02 bps | 0.00 bps | **REJECT_NO_ECONOMIC_INFORMATION** |

