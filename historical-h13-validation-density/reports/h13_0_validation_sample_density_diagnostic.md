# H13.0 Validation Sample Density Diagnostic

Status: `PASS`

## Source Provenance

```text
AUTHORITATIVE_INPUT_SOURCE = RELEASE_LOCAL_H10_FROZEN_ARTIFACTS
H13_0_INPUT_PROVENANCE = PASS
SOURCE_BYTES_MUTATED = NO
H10_ARTIFACTS_MUTATED = NO
```

## Acceptance State

```text
H13_0_VALIDATION_SAMPLE_DENSITY_DIAGNOSTIC = PASS
SOURCE_INSUFFICIENT_FOLDS = 7
INPUT_ROWS = 7
INSUFFICIENT_FOLDS_ACCOUNTED_FOR = 7
ROOT_CAUSE_UNIQUENESS = PASS
ROOT_CAUSE_ASSIGNED = 7
H10_ARTIFACTS_MUTATED = NO
MARKET_REPLAY_V2_RERUN = NO
THRESHOLD_SEARCH_STARTED = NO
POLICY_SEARCH_STARTED = NO
VALIDATION_DESIGN_MUTATED = NO
PRODUCTION_CHANGE = BLOCKED
```

## Primary Finding

```text
H13_0_PRIMARY_FINDING = SAMPLE_INSUFFICIENCY_DOMINATED_BY_SYMBOL_SUBSET_TOO_NARROW
```

## Root Cause Distribution

| Root cause | Count |
| --- | ---: |
| `ZERO_DIRECTIONAL_DENSITY` | 0 |
| `TECHNICAL_FILTER_TOO_SPARSE` | 0 |
| `POSTERIOR_FILTER_TOO_SPARSE` | 0 |
| `META_FILTER_TOO_SPARSE` | 0 |
| `SYMBOL_SUBSET_TOO_NARROW` | 6 |
| `REGIME_FILTER_TOO_NARROW` | 1 |
| `COMBINED_POLICY_SELECTIVITY` | 0 |
| `VALIDATION_WINDOW_TOO_SHORT` | 0 |
| `OTHER_EXPLICIT_CAUSE` | 0 |

## Fold Diagnostics

| Fold | Family | Actual / Required | Primary root cause | Key counts |
| --- | --- | ---: | --- | --- |
| `H10_WF_EXPANDING_MONTHLY_V1_F03` | `F4_SYMBOL_SPECIFIC_ELIGIBILITY` | 4 / 15 | `SYMBOL_SUBSET_TOO_NARROW` | pre_symbol=31, post_symbol=20, pre_regime=20, post_regime=20, label=4 |
| `H10_WF_EXPANDING_MONTHLY_V1_F04` | `F4_SYMBOL_SPECIFIC_ELIGIBILITY` | 9 / 15 | `SYMBOL_SUBSET_TOO_NARROW` | pre_symbol=34, post_symbol=25, pre_regime=25, post_regime=25, label=9 |
| `H10_WF_EXPANDING_MONTHLY_V1_F05` | `F4_SYMBOL_SPECIFIC_ELIGIBILITY` | 8 / 15 | `SYMBOL_SUBSET_TOO_NARROW` | pre_symbol=32, post_symbol=23, pre_regime=23, post_regime=23, label=8 |
| `H10_WF_EXPANDING_MONTHLY_V1_F06` | `F4_SYMBOL_SPECIFIC_ELIGIBILITY` | 4 / 15 | `SYMBOL_SUBSET_TOO_NARROW` | pre_symbol=51, post_symbol=30, pre_regime=30, post_regime=30, label=4 |
| `H10_WF_EXPANDING_MONTHLY_V1_F07` | `F4_SYMBOL_SPECIFIC_ELIGIBILITY` | 10 / 15 | `SYMBOL_SUBSET_TOO_NARROW` | pre_symbol=52, post_symbol=37, pre_regime=37, post_regime=37, label=10 |
| `H10_WF_EXPANDING_MONTHLY_V1_F08` | `F4_SYMBOL_SPECIFIC_ELIGIBILITY` | 2 / 15 | `SYMBOL_SUBSET_TOO_NARROW` | pre_symbol=24, post_symbol=6, pre_regime=6, post_regime=6, label=2 |
| `H10_WF_EXPANDING_MONTHLY_V1_F09` | `F5_REGIME_CONDITIONED_ELIGIBILITY` | 7 / 15 | `REGIME_FILTER_TOO_NARROW` | pre_symbol=47, post_symbol=47, pre_regime=47, post_regime=39, label=7 |

## Notes

- Actual sample is the frozen H10.7 labeled sample `n`.
- Funnel counts were recomputed read-only from frozen H10 historical analysis and fold membership artifacts.
- No H10 source artifact was modified and no market replay was rerun.
- H13.1 was not opened by this diagnostic.
