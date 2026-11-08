# HMR-V5 v2: Causal Next-Bar-Open & Time-Block Candidate Evaluation Report (2023–2026)

- **Evaluation Timestamp**: `2026-11-01T18:55:57.834229+00:00`
- **Execution Timing Contract (`VOL_COMPRESSION_BREAKOUT_V1`)**: Signal confirmed at close of bar `i`; earliest entry at `opens[i+1]` (`entry_index = signal_index + 1`); SL-first collision resolution; adverse `opens[curr_idx]` fill on gap-through-stop (`SL_GAP`); `max_hold` anchored at `entry_index`.
- **Split Taxonomy**: `2023` = Exploratory Discovery/Train; `2024–2025` = Development Selection (NOT independent confirmatory OOS); `2026-H1` = Exposed One-Shot Audit Set (failed & permanently burned; zero retuning).
- **Multiple-Testing & CI Governance**: `multiple_testing_trials_count = UNKNOWN`; all pre-lock historical CIs are exploratory. Primary Gate 7 uses **Moving-Block & Stationary Bootstrap (`B=10d`) on cross-symbol daily MTM portfolio returns**; IID trade-level CI is strictly diagnostic.
- **System Disposition**: `NO_VALIDATED_OOS_EDGE_ENFORCE_NO_TRADE_SHADOW` (`ENFORCE_NO_TRADE_SHADOW`)

## 1. Development Selection (2024–2025) & Burned 2026-H1 Audit Summary

| Candidate |Dev 24–25 N | Dev Gross (bps) | Dev Net @14 | Dev Net @20 | Primary Daily Block 95% CI (bps/d) | Diag IID Trade 95% CI (bps) | Burned 2026 N | Burned 2026 Gross / Net @14 | Verdict |
| :--- | ---: | ---: | ---: | ---: | :---: | :---: | ---: | :---: | :--- |
| **NO_TRADE** | 0 | +0.00 | +0.00 | +0.00 | `[+0.00, +0.00]` | `[+0.0, +0.0]` | 0 | +0.00 / +0.00 | `BASELINE_ABSTENTION` |
| **CONTROL** | 2084 | -1.36 | -15.14 | -21.36 | `[-12.22, -9.68]` | `[-17.0, -13.8]` | 509 | +1.59 / -12.52 | `REJECTED_NEGATIVE_EXPECTANCY` |
| **S3_LEGACY** | 0 | +0.00 | +0.00 | +0.00 | `[+0.00, +0.00]` | `[+0.0, +0.0]` | 0 | +0.00 / +0.00 | `OUT_OF_DOMAIN_DIAGNOSTIC_REJECTED` |
| **NET_RETURN_RANKER** | 1 | +50.00 | +35.96 | +30.00 | `[+0.00, +0.04]` | `[+36.0, +36.0]` | 0 | +0.00 / +0.00 | `REJECTED_INSUFFICIENT_SAMPLE_AND_ZERO_FOLD_COVERAGE` |
| **VOL_COMPRESSION_BREAKOUT_V1** | 369 | +39.88 | +24.26 | +19.88 | `[-0.05, +6.55]` | `[+2.6, +49.3]` | 125 | -7.60 / -22.26 | `EXPLORATORY_DEV_EDGE_AUDIT_FAILED_NO_VALIDATED_EDGE` |

## 2. Retracted Same-Close vs. Corrected Next-Bar-Open (`VOL_COMPRESSION_BREAKOUT_V1`)

| Split | Timing Mode | Signals | Exec / Rej | Gross (bps) | Net @14 | Net @20 | PF | MDD% | Primary Daily Block CI (bps/d) | Diag IID Trade CI (bps) |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | :---: |
| `EXPLORATORY_TRAIN_2023` | Retracted Same-Close | 860 | 226 / 633 | +26.67 | +11.83 | +6.67 | 1.13 | 10.98% | `[-3.87, +8.14]` | `[-15.8, +41.2]` |
| `EXPLORATORY_TRAIN_2023` | Corrected Next-Bar-Open | 860 | 226 / 633 | +26.68 | +11.83 | +6.68 | 1.13 | 10.97% | `[-3.85, +8.17]` | `[-15.8, +41.2]` |
| `DEV_SELECTION_2024` | Retracted Same-Close | 836 | 156 / 680 | +48.14 | +32.62 | +28.14 | 1.37 | 5.62% | `[-0.68, +7.92]` | `[-0.9, +70.3]` |
| `DEV_SELECTION_2024` | Corrected Next-Bar-Open | 836 | 156 / 680 | +48.11 | +32.59 | +28.11 | 1.37 | 5.63% | `[-0.70, +7.91]` | `[-0.9, +70.3]` |
| `DEV_SELECTION_2025` | Retracted Same-Close | 1365 | 213 / 1146 | +33.86 | +18.79 | +13.86 | 1.21 | 6.80% | `[-2.02, +7.93]` | `[-9.3, +49.3]` |
| `DEV_SELECTION_2025` | Corrected Next-Bar-Open | 1365 | 213 / 1146 | +33.86 | +18.79 | +13.86 | 1.21 | 6.80% | `[-2.01, +7.94]` | `[-9.3, +49.3]` |
| `DEV_WALK_FORWARD_SELECTION_2024_2025` | Retracted Same-Close | 2201 | 369 / 1826 | +39.90 | +24.27 | +19.90 | 1.27 | 6.80% | `[-0.05, +6.55]` | `[+2.6, +49.3]` |
| `DEV_WALK_FORWARD_SELECTION_2024_2025` | Corrected Next-Bar-Open | 2201 | 369 / 1826 | +39.88 | +24.26 | +19.88 | 1.27 | 6.80% | `[-0.05, +6.55]` | `[+2.6, +49.3]` |
| `BURNED_EXPOSED_AUDIT_2026_H1` | Retracted Same-Close | 647 | 124 / 523 | -6.45 | -21.16 | -26.45 | 0.78 | 15.39% | `[-11.02, +4.54]` | `[-53.9, +13.7]` |
| `BURNED_EXPOSED_AUDIT_2026_H1` | Corrected Next-Bar-Open | 652 | 125 / 523 | -7.60 | -22.26 | -27.60 | 0.77 | 15.39% | `[-11.07, +4.20]` | `[-54.9, +14.2]` |

## 3. Per-Symbol Breakdown (`VOL_COMPRESSION_BREAKOUT_V1`: Retracted Same-Close vs. Corrected Next-Bar-Open)

| Split | Symbol | Same-Close N | Same-Close Gross / Net@14 | Next-Bar-Open N | Next-Bar-Open Gross / Net@14 |
| :--- | :--- | ---: | :---: | ---: | :---: |
| `EXPLORATORY_TRAIN_2023` | **BTC** | 79 | +15.72 / +1.71 | 79 | +15.72 / +1.70 |
| `EXPLORATORY_TRAIN_2023` | **ETH** | 78 | +30.36 / +16.34 | 78 | +30.35 / +16.33 |
| `EXPLORATORY_TRAIN_2023` | **BNB** | 69 | +35.05 / +21.02 | 69 | +35.09 / +21.06 |
| `DEV_SELECTION_2024` | **BTC** | 66 | +76.04 / +61.98 | 66 | +76.02 / +61.96 |
| `DEV_SELECTION_2024` | **ETH** | 40 | +73.11 / +59.06 | 40 | +73.11 / +59.06 |
| `DEV_SELECTION_2024` | **BNB** | 50 | -8.67 / -22.66 | 50 | -8.73 / -22.73 |
| `DEV_SELECTION_2025` | **BTC** | 97 | +19.38 / +5.37 | 97 | +19.38 / +5.37 |
| `DEV_SELECTION_2025` | **ETH** | 38 | +57.36 / +43.32 | 38 | +57.36 / +43.32 |
| `DEV_SELECTION_2025` | **BNB** | 78 | +40.42 / +26.39 | 78 | +40.42 / +26.39 |
| `DEV_WALK_FORWARD_SELECTION_2024_2025` | **BTC** | 163 | +42.32 / +28.29 | 163 | +42.31 / +28.28 |
| `DEV_WALK_FORWARD_SELECTION_2024_2025` | **ETH** | 78 | +65.44 / +51.39 | 78 | +65.44 / +51.39 |
| `DEV_WALK_FORWARD_SELECTION_2024_2025` | **BNB** | 128 | +21.25 / +7.23 | 128 | +21.22 / +7.21 |
| `BURNED_EXPOSED_AUDIT_2026_H1` | **BTC** | 49 | -27.61 / -41.59 | 49 | -27.61 / -41.59 |
| `BURNED_EXPOSED_AUDIT_2026_H1` | **ETH** | 30 | +22.61 / +8.59 | 31 | +17.03 / +3.02 |
| `BURNED_EXPOSED_AUDIT_2026_H1` | **BNB** | 45 | -2.77 / -16.77 | 45 | -2.78 / -16.78 |

## 4A. Cost-Sensitivity Matrix — Development Selection (2024–2025)

| Candidate | Executed N | Gross (bps) | 10 bps Friction | 14 bps (Baseline) | 20 bps (Stressed) | 30 bps (Extreme) |
| :--- | ---: | ---: | :--- | :--- | :--- | :--- |
| **NO_TRADE** | 0 | +0.00 bps | +0.00 bps (PF 0.00) | +0.00 bps (PF 0.00) | +0.00 bps (PF 0.00) | +0.00 bps (PF 0.00) |
| **CONTROL** | 2084 | -1.36 bps | -11.36 bps (PF 0.56) | -15.36 bps (PF 0.46) | -21.36 bps (PF 0.33) | -31.36 bps (PF 0.19) |
| **S3_LEGACY** | 0 | +0.00 bps | +0.00 bps (PF 0.00) | +0.00 bps (PF 0.00) | +0.00 bps (PF 0.00) | +0.00 bps (PF 0.00) |
| **NET_RETURN_RANKER** | 1 | +50.00 bps | +40.00 bps (PF INF_UNDEFINED_SMALL_SAMPLE) | +36.00 bps (PF INF_UNDEFINED_SMALL_SAMPLE) | +30.00 bps (PF INF_UNDEFINED_SMALL_SAMPLE) | +20.00 bps (PF INF_UNDEFINED_SMALL_SAMPLE) |
| **VOL_COMPRESSION_BREAKOUT_V1** | 369 | +39.88 bps | +29.88 bps (PF 1.34) | +25.88 bps (PF 1.29) | +19.88 bps (PF 1.21) | +9.88 bps (PF 1.10) |

## 4B. Cost-Sensitivity Matrix — Burned Exposed 2026-H1 Audit Set

| Candidate | Executed N | Gross (bps) | 10 bps Friction | 14 bps (Baseline) | 20 bps (Stressed) | 30 bps (Extreme) |
| :--- | ---: | ---: | :--- | :--- | :--- | :--- |
| **NO_TRADE** | 0 | +0.00 bps | +0.00 bps (PF 0.00) | +0.00 bps (PF 0.00) | +0.00 bps (PF 0.00) | +0.00 bps (PF 0.00) |
| **CONTROL** | 509 | +1.59 bps | -8.41 bps (PF 0.65) | -12.41 bps (PF 0.53) | -18.41 bps (PF 0.39) | -28.41 bps (PF 0.22) |
| **S3_LEGACY** | 0 | +0.00 bps | +0.00 bps (PF 0.00) | +0.00 bps (PF 0.00) | +0.00 bps (PF 0.00) | +0.00 bps (PF 0.00) |
| **NET_RETURN_RANKER** | 0 | +0.00 bps | +0.00 bps (PF 0.00) | +0.00 bps (PF 0.00) | +0.00 bps (PF 0.00) | +0.00 bps (PF 0.00) |
| **VOL_COMPRESSION_BREAKOUT_V1** | 125 | -7.60 bps | -17.60 bps (PF 0.82) | -21.60 bps (PF 0.78) | -27.60 bps (PF 0.73) | -37.60 bps (PF 0.66) |
