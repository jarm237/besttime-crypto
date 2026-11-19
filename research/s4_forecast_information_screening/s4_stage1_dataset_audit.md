# S4-P1A Dataset Integrity & Causal Readiness Audit

- Preregistration frozen at `7b5a97becbd6da1249a484ed588133761cc57bd0`.
- Scope: Binance Spot 1h, UTC open time, BTCUSDT/ETHUSDT/SOLUSDT/BNBUSDT.
- Authorized content window: `2021-11-01 00:00` through `2023-12-31 23:00 UTC`.
- No model training, forecast, IC, backtest, allocator, or post-2023 market-data content access was performed.

## Verdict

`DATASET_READY` — next mapped step: `S4-P1A_FORECAST_IMPLEMENTATION` (**not executed**).

The authentic market-wide gap is handled by strict complete-case exclusion and leaves `349` common 2023 dates, above the frozen minimum of 300.

## Source provenance and selection

Canonical source: **monthly Binance Spot archives with verified Binance SHA-256 sidecars**. Selection reason: direct raw provenance, exact authorized-month isolation, full authorized open-time window. All `104` monthly ZIP checksums matched their sidecars.

Derived Parquets were cross-checks only. Across the four full-window derivatives, `18` overlapping OHLCV cells conflict with the checksum-verified raw archives, and all four files omit `2023-12-31 23:00 UTC`. Every difference is recorded as `SOURCE_CONFLICT`; none is imported into the canonical calendar.

| Asset | Raw rows | Start | End | Missing | Other anomalies |
|---|---:|---|---|---:|---:|
| BTCUSDT | 18983 | 2021-11-01T00:00:00+00:00 | 2023-12-31T23:00:00+00:00 | 1 | 0 |
| ETHUSDT | 18983 | 2021-11-01T00:00:00+00:00 | 2023-12-31T23:00:00+00:00 | 1 | 0 |
| SOLUSDT | 18983 | 2021-11-01T00:00:00+00:00 | 2023-12-31T23:00:00+00:00 | 1 | 0 |
| BNBUSDT | 18983 | 2021-11-01T00:00:00+00:00 | 2023-12-31T23:00:00+00:00 | 1 | 0 |

## Effective dataset

| Phase | Expected hours | Actual/asset | Common hours | Market-wide missing | Nominal decisions | Feature-valid | Label-valid | Common complete-case | Excluded |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| Warmup | 1464 | BTCUSDT:1464, ETHUSDT:1464, SOLUSDT:1464, BNBUSDT:1464 | 1464 | 0 | 61 | 47 | 61 | 47 | 14 |
| 2022 Dev | 8760 | BTCUSDT:8760, ETHUSDT:8760, SOLUSDT:8760, BNBUSDT:8760 | 8760 | 0 | 364 | 364 | 364 | 364 | 0 |
| 2023 Screen | 8760 | BTCUSDT:8759, ETHUSDT:8759, SOLUSDT:8759, BNBUSDT:8759 | 8759 | 1 | 364 | 350 | 363 | 349 | 15 |

## Gap and causal dependency impact

- Gap: `2023-03-24T13:00:00+00:00`, all four assets, market-wide.
- Label interval exclusion: `2023-03-24T00:00:00+00:00`.
- 336-hour feature dependency exclusions: `2023-03-25T00:00:00+00:00` through `2023-04-07T00:00:00+00:00` (14 decisions).
- Combined 2023 exclusion: 15 decisions.
- No forward-fill, backward-fill, interpolation, or zero-imputation is used.

## Label availability, sigma warmup, and folds

At cutoff `t 00:00`, only labels whose completion timestamp is `<= cutoff` enter EWMA; the ordinary latest label is `t-2`. Each asset has 60 completed valid labels by the 2022-01-01 cutoff, so the 30-label initialization is feasible.

| Fold | Nominal fit | Purged row | Complete-case fit | Floor feasible |
|---|---:|---|---:|---|
| F1 | 120 | 2022-04-30T00:00:00+00:00 | 119 | True |
| F2 | 166 | 2022-06-15T00:00:00+00:00 | 165 | True |
| F3 | 212 | 2022-07-31T00:00:00+00:00 | 211 | True |
| F4 | 273 | 2022-09-30T00:00:00+00:00 | 272 | True |

## Synthetic leakage negative tests

- A: `PASS` — mutating t 01:00 entry does not change features at t.
- B: `PASS` — mutating t+1 01:00 exit changes neither features nor sigma at t.
- C: `PASS` — mutating incomplete t-1 label does not change sigma at t.
- D: `PASS` — mutating an old completed label can change future, never past sigma.
- E: `PASS` — removing one authentic dependency bar excludes the sample.
- F: `PASS` — 2022-12-31 label is unavailable at 2023-01-01 00:00.
- G: `PASS` — 2023-12-31 decision is excluded.

## Technical readiness

- `RAW_SOURCE_PROVENANCE = PASS`
- `UTC_CALENDAR_ALIGNMENT = PASS`
- `OHLCV_INTEGRITY = PASS`
- `FEATURE_CAUSALITY = PASS`
- `FEATURE_COMPLETENESS = PASS`
- `LABEL_FEASIBILITY = PASS`
- `LABEL_AVAILABILITY = PASS`
- `SIGMA_WARMUP = PASS`
- `FOLD_PURGING = PASS`
- `2023_COMMON_SAMPLE_COVERAGE = PASS`
- `NO_2024_2026_ACCESS = PASS`

## Final authorization state

```text
S3_RESEARCH = CLOSED_NEGATIVE_EXPLORATORY
S4_P0_EXECUTABLE_PREREG = FROZEN
S4_STAGE1_RESEARCH = AUTHORIZED
S4_DATASET_READINESS = DATASET_READY
S4_NEURAL_TRAINING = NOT_PERFORMED
S4_RIDGE_TRAINING = NOT_PERFORMED
S4_2023_PREDICTIVE_SCREEN = NOT_PERFORMED
S4_STAGE2_ALLOCATOR = NOT_AUTHORIZED
S4_2024_2026_ACCESS = NOT_AUTHORIZED
PRODUCTION_PROMOTION = NOT_AUTHORIZED
```
