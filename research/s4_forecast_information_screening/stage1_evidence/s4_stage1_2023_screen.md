# S4-P1C: One-Shot 2023 Forecast Information Screening Report

- **Pre-registration Commit:** `7b5a97becbd6da1249a484ed588133761cc57bd0`
- **Evaluation Phase:** `2023_REUSED_INTERNAL_SCREEN`
- **Generated At (UTC):** `2026-11-19T02:43:38.059586+00:00`
- **Scientific Verdict:** **`STAGE1_SIGNAL_INCONCLUSIVE`**

## 1. Primary Screening Result

- **Eligible Common Dates:** 349 (Nominal: 364, Excluded: 15)
- **Fisher-z S(Neural):** `0.031217`
- **Fisher-z S(Ridge):**  `0.012557`
- **Primary Delta S [S(Neural) - S(Ridge)]:** `0.018660`
- **Primary 14-day Paired 95% Percentile CI:** `[-0.115742, 0.155270]` (Mean: `0.013970`, Std: `0.069447`)
- **Block-Length Sensitivity CIs:**
  - 7-day:  `[-0.115994, 0.144189]`
  - 21-day: `[-0.112371, 0.158913]`

### Per-Asset Correlation (Raw Unclipped Standardized Target)

| Asset | Neural IC | Ridge IC | Delta IC |
|---|---:|---:|---:|
| `BTCUSDT` | 0.054509 | 0.025599 | 0.028910 |
| `ETHUSDT` | -0.027536 | 0.018645 | -0.046181 |
| `SOLUSDT` | 0.020189 | -0.006411 | 0.026600 |
| `BNBUSDT` | 0.077542 | 0.012389 | 0.065153 |

## 2. Verdict Decision Criteria Checks

- **(a) N_common >= 300:** `True` (349)
- **(b) S(Neural) > 0:** `True` (0.031217)
- **(c) Primary 14d 95% CI Lower Bound > 0:** `False` (-0.115742)
- **(d) MZ Slopes Corroborated (>=3/4 > 0 and median > 0):** `False`
- **(e) Extreme-Day-Excluded Delta S > 0:** `False` (-0.105712)
- **(f) Protocol Integrity Valid:** `True`

## 3. Preregistered Diagnostics

### 3.1. Common Market vs. Relative Decomposition

- **Common Market IC (Neural):** `0.054739`
- **Common Market IC (Ridge):**  `0.004950`
- **Common Market Delta IC:**     `0.049789`
- **Relative Fisher-z S (Neural):** `-0.034685`
- **Relative Fisher-z S (Ridge):**  `0.038033`
- **Relative Delta S:**              `-0.072717`

### 3.2. Mincer-Zarnowitz Regression (Unclipped Return Scale)

| Asset | Neural Alpha (bps) | Neural Beta | SE(Beta) | Neural R² | Ridge Beta | Ridge R² |
|---|---:|---:|---:|---:|---:|---:|
| `BTCUSDT` | 30.16 | 0.3674 | 0.5037 | 0.0015 | 0.2420 | 0.0007 |
| `ETHUSDT` | 15.70 | -0.2174 | 0.4499 | 0.0007 | 0.0377 | 0.0000 |
| `SOLUSDT` | 56.05 | -0.2907 | 0.3442 | 0.0021 | 0.0429 | 0.0000 |
| `BNBUSDT` | 16.02 | 0.6091 | 0.4646 | 0.0049 | -0.1266 | 0.0003 |

### 3.3. BTC-Relative Spread Sign Accuracy (|Spread| > 24 bps)

| Pair | Total Dates | Neural Eligible | Neural Accuracy | Ridge Eligible | Ridge Accuracy |
|---|---:|---:|---:|---:|---:|
| `ETH-BTC` | 349 | 38 (10.9%) | 52.63% | 51 (14.6%) | 58.82% |
| `SOL-BTC` | 349 | 238 (68.2%) | 50.84% | 305 (87.4%) | 52.79% |
| `BNB-BTC` | 349 | 74 (21.2%) | 48.65% | 108 (30.9%) | 41.67% |

### 3.4. Extreme-Day Exclusion Sensitivity

- **Dropped Days Count:** 18 days (top 5% absolute market moves)
- **Kept Days Count:** 331 days
- **S(Neural) on Kept Days:** `-0.009517`
- **S(Ridge) on Kept Days:**  `0.096195`
- **Delta S on Kept Days:**   `-0.105712`

### 3.5. First Half vs. Second Half Stability

- **H1 (Jan-Jun):** N=166, S(Neural)=`0.103764`, S(Ridge)=`-0.020876`, Delta S=`0.124640`
- **H2 (Jul-Dec):** N=183, S(Neural)=`-0.040265`, S(Ridge)=`0.052419`, Delta S=`-0.092684`

## 4. Frozen Artifact Integrity & Boundaries

| Artifact File | Verified SHA-256 Digest |
|---|---|
| `neural_forecaster.pt` | `9eb90134e9bec5b2c2cede72cebf3d815a4cfc088d48d5d51bad16c9c352280a` |
| `ridge_baseline.joblib` | `647f718d2b6d2bf3b56faf0dfdd430a488f228ded7c7ffe4bf931e2afe371fe1` |
| `feature_scaler.json` | `97066d059fee3b50bffdbd8629fd2f7a7d2b0a025907ef040041edb9adec0c09` |
| `sigma_floors.json` | `d001797d07d3738592ab47f877ba5c892d37a69cab6fbed5936a79e29394d697` |

```text
S4_DATASET_READINESS   = DATASET_READY
S4_2023_SCREEN         = COMPLETED (STAGE1_SIGNAL_INCONCLUSIVE)
S4_2024_2026_ACCESS    = NOT_AUTHORIZED
S4_STAGE2_ALLOCATOR    = NOT_AUTHORIZED
PRODUCTION_PROMOTION   = NOT_AUTHORIZED
RE_TUNING_OR_RERUN     = PROHIBITED
```
