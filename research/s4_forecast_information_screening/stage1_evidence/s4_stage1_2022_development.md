# S4-P1B: 2022 Development & Frozen Model Fitting Report

- **Pre-registration Commit:** `7b5a97becbd6da1249a484ed588133761cc57bd0`
- **Generated At (UTC):** `2026-11-19T02:11:10.075945+00:00`
- **Status:** `COMPLETED`
- **Verdict:** `FROZEN_MODELS_READY`

## 1. Data Provenance & 2021 Warmup

- **Canonical Source:** monthly Binance Spot archives with verified SHA-256 sidecars
- **Archives Count:** 104 monthly Binance Spot archives verified via SHA-256 sidecars.
- **Universe:** BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT
- **2021 Warmup Completed Labels at 2022-01-01 00:00 UTC:** 60 (minimum required: 30).
- **2022 Development Decisions:** 364 eligible decisions (2022-01-01 00:00:00+00:00 through 2022-12-30 00:00:00+00:00), 0 excluded.

## 2. Ridge Alpha Cross-Validation (4 Expanding Folds)

| Alpha | Mean Validation MSE | F1 MSE | F2 MSE | F3 MSE | F4 MSE |
|---|---:|---:|---:|---:|---:|
| 0.001 | 2.397309 | 3.319560 | 2.086419 | 1.562777 | 2.620479 |
| 0.01 | 2.397268 | 3.319522 | 2.086388 | 1.562751 | 2.620410 |
| 0.1 | 2.396855 | 3.319137 | 2.086075 | 1.562487 | 2.619720 |
| 1.0 | 2.392746 | 3.315307 | 2.082958 | 1.559855 | 2.612863 |
| 10.0 | 2.353408 | 3.278009 | 2.052774 | 1.534806 | 2.548042 |
| 100.0 | 2.076506 | 2.984251 | 1.823820 | 1.366552 | 2.131402 |
| 1000.0 | 1.452496 | 2.173028 | 1.231629 | 1.021283 | 1.384046 |
| 10000.0 | 1.155056 | 1.749129 | 0.954279 | 0.819949 | 1.096867 |

- **Selected Ridge Alpha:** `10000.0`
- **2022 In-Sample MSE:** `0.816430`

## 3. Shared Neural Forecaster Training (2022 Development)

- **Architecture:** `Shared GRU(6, 16) + Cross-asset MHA(16, 2) + LayerNorm + Linear(16, 1)`
- **Trainable Parameters:** 2289 (budget: <= 5000)
- **Optimizer:** AdamW (lr=0.001, weight_decay=0.001)
- **Batch Size / Epochs:** batch_size=32, epochs=30, shuffle=False
- **Device / Seed:** cpu, seed=42
- **Initial Epoch Loss:** `1.404906`
- **Final Epoch Loss (Epoch 30):** `1.000839`
- **2022 In-Sample MSE:** `0.997524`

## 4. Frozen Model Artifacts & SHA-256

| Artifact File | Size (Bytes) | SHA-256 Digest |
|---|---:|---|
| `neural_forecaster.pt` | 14003 | `9eb90134e9bec5b2c2cede72cebf3d815a4cfc088d48d5d51bad16c9c352280a` |
| `ridge_baseline.joblib` | 129607 | `647f718d2b6d2bf3b56faf0dfdd430a488f228ded7c7ffe4bf931e2afe371fe1` |
| `feature_scaler.json` | 362 | `97066d059fee3b50bffdbd8629fd2f7a7d2b0a025907ef040041edb9adec0c09` |
| `sigma_floors.json` | 149 | `d001797d07d3738592ab47f877ba5c892d37a69cab6fbed5936a79e29394d697` |
| `training_trace.json` | 4141 | `d463b5c4a394f37d41ffa2b7746b73929697dc51c687a4884f26bf45d753534f` |

## 5. Reload & Finite Output Verification

- **Status:** `PASS`
- **Sample Predictions Finite:** `True`
- **Reloaded Exact Match:** `True`

## 6. Research Boundaries

```text
S4_DATASET_READINESS   = DATASET_READY
S4_2022_DEVELOPMENT    = COMPLETED
S4_RIDGE_MODEL         = FROZEN
S4_NEURAL_MODEL        = FROZEN
S4_PREPROCESSING       = FROZEN
S4_2023_SCREEN         = NOT_PERFORMED
S4_2024_2026_ACCESS    = NOT_AUTHORIZED
S4_STAGE2_ALLOCATOR    = NOT_AUTHORIZED
PRODUCTION_PROMOTION   = NOT_AUTHORIZED
```
