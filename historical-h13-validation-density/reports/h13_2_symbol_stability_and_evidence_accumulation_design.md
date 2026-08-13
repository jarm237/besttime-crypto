# H13.2 Symbol Stability And Evidence Accumulation Design Research

Status: `PASS_WITH_LIMITS`

## Acceptance State

```text
H13_2_SYMBOL_STABILITY_AND_EVIDENCE_ACCUMULATION_DESIGN_RESEARCH = PASS_WITH_LIMITS
DESIGN_CELLS_EVALUATED = 9
H13_2_DESIGN_OUTPUT = MULTI_FACTOR_DESIGN_REQUIRED
PRIMARY_METRICS_ONLY_FOR_DESIGN_SELECTION = YES
QUALITY_METRICS_USED_FOR_DESIGN_SELECTION = NO
NEW_POLICY_CANDIDATE = NONE
POLICY_SEARCH = CLOSED
NEW_THRESHOLD_SEARCH = 0
NEW_POLICY_PARAMETER_SEARCH = 0
PRODUCTION_CHANGE = BLOCKED
MARKET_REPLAY_V2_RERUN = NO
H10_ARTIFACTS_MUTATED = NO
H13_1_ARTIFACTS_MUTATED = NO
MIN_SAMPLE_REQUIREMENT_MUTATED = NO
QUALITY_GUARDS_MUTATED = NO
```

## Design Cell Summary

| Design cell | Blocks | Label authority | Actual evaluable rate | Proxy evaluable rate | Min actual n | Min proxy n | Switch blocks |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| `D1_DYNAMIC_SYMBOL_SUBSET x E1_MONTHLY` | 6 | `FULL` | 0.000 | 0.833 | 2 | 6 | 0 |
| `D1_DYNAMIC_SYMBOL_SUBSET x E2_2_MONTH_CONTIGUOUS` | 3 | `FULL` | 0.000 | 1.000 | 12 | 43 | 1 |
| `D1_DYNAMIC_SYMBOL_SUBSET x E3_3_MONTH_CONTIGUOUS` | 2 | `FULL` | 1.000 | 1.000 | 16 | 68 | 1 |
| `D2_FIXED_SYMBOL_SUBSET x E1_MONTHLY` | 6 | `PARTIAL` | 0.000 | 0.833 | 4 | 13 | 0 |
| `D2_FIXED_SYMBOL_SUBSET x E2_2_MONTH_CONTIGUOUS` | 3 | `PARTIAL` | 0.000 | 1.000 | 12 | 45 | 0 |
| `D2_FIXED_SYMBOL_SUBSET x E3_3_MONTH_CONTIGUOUS` | 2 | `PARTIAL` | 1.000 | 1.000 | 21 | 68 | 0 |
| `D3_SLOW_UPDATE_SYMBOL_SUBSET x E1_MONTHLY` | 6 | `PARTIAL` | 0.000 | 0.833 | 4 | 13 | 0 |
| `D3_SLOW_UPDATE_SYMBOL_SUBSET x E2_2_MONTH_CONTIGUOUS` | 3 | `PARTIAL` | 0.000 | 1.000 | 12 | 45 | 0 |
| `D3_SLOW_UPDATE_SYMBOL_SUBSET x E3_3_MONTH_CONTIGUOUS` | 2 | `PARTIAL` | 1.000 | 1.000 | 21 | 68 | 0 |

## Finding

```text
H13_2_DESIGN_OUTPUT = MULTI_FACTOR_DESIGN_REQUIRED
```

H13.2 does not approve a policy. It shows that evidence accumulation and symbol-membership stability must be handled together. A pure longer-window lane is still not justified because dynamic longer blocks can mix symbol-subset regimes, while fixed/slow-update cells require fresh labeled validation authority before policy research reopens.

## Notes

- Actual labeled sample metrics are used only where frozen H10 validation labels directly support the design cell.
- Counterfactual membership cells use pre-label density proxies and are not promotion-eligible.
- EV/PnL was not used to select a design cell.
