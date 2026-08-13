# H13.1 Symbol Subset Density And Generalization Research

Status: `PASS`

## Acceptance State

```text
H13_1_SYMBOL_SUBSET_DENSITY_AND_GENERALIZATION_RESEARCH = PASS
SOURCE_F4_INSUFFICIENT_FOLDS = 6
SOURCE_F4_FOLDS_ACCOUNTED_FOR = 6
FROZEN_SYMBOL_SUBSETS_RECOVERED = 6
SYMBOL_DENSITY_FUNNEL_ACCOUNTING = PASS
SYMBOL_SUBSET_SELECTION_STABILITY = MIXED
SELECTIVITY_DENSITY_TRADEOFF = PRESENT
SELECTION_OBJECTIVE_DENSITY_BLIND_SPOT = NOT_PRESENT
REGIME_DENSITY_EVIDENCE = LIMITED
MARKET_REPLAY_V2_RERUN = NO
H10_ARTIFACTS_MUTATED = NO
H10_SELECTION_RULES_MUTATED = NO
MIN_SAMPLE_RULE_MUTATED = NO
VALIDATION_DESIGN_MUTATED = NO
LONGER_VALIDATION_WINDOW_RESEARCH_OPENED = NO
NEW_THRESHOLD_SEARCH = 0
NEW_POLICY_SEARCH = 0
NEW_POLICY_CANDIDATE = NONE
PRODUCTION_CHANGE = BLOCKED
```

## Primary Finding

```text
H13_1_PRIMARY_FINDING = MIXED_SYMBOL_SUBSET_DRIFT_AND_SELECTIVITY_DENSITY_TRADEOFF
```

## Symbol Selection Stability

- Exact subset repeat count: `4/5`
- Symbol set switch count: `1`
- Mean consecutive Jaccard similarity: `0.900`
- Min consecutive Jaccard similarity: `0.500`
- Classification: `MIXED`

## Density Funnels

| Fold | Enabled | Pre-symbol | Post-symbol | Removed | Loss rate | Validation n / min | Days to min, pre-label |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `H10_WF_EXPANDING_MONTHLY_V1_F03` | `ETHUSDT,BNBUSDT` | 31 | 20 | 11 | 0.355 | 4 / 15 | 23.2 |
| `H10_WF_EXPANDING_MONTHLY_V1_F04` | `ETHUSDT,BNBUSDT` | 34 | 25 | 9 | 0.265 | 9 / 15 | 16.8 |
| `H10_WF_EXPANDING_MONTHLY_V1_F05` | `ETHUSDT,BNBUSDT` | 32 | 23 | 9 | 0.281 | 8 / 15 | 20.2 |
| `H10_WF_EXPANDING_MONTHLY_V1_F06` | `ETHUSDT,BNBUSDT` | 51 | 30 | 21 | 0.412 | 4 / 15 | 15.0 |
| `H10_WF_EXPANDING_MONTHLY_V1_F07` | `ETHUSDT,BNBUSDT` | 52 | 37 | 15 | 0.288 | 10 / 15 | 12.6 |
| `H10_WF_EXPANDING_MONTHLY_V1_F08` | `BNBUSDT` | 24 | 6 | 18 | 0.750 | 2 / 15 | 75.0 |

## Notes

- Days-to-min-sample is reported as a consequence of symbol selectivity, not as `VALIDATION_WINDOW_TOO_SHORT`.
- Comparable broader parents and runner-up comparisons use only frozen H10.5/H10.6 artifacts.
- No market replay was rerun, no threshold or policy search was started, and no policy candidate was created.
