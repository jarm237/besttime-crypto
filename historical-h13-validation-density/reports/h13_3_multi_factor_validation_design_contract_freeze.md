# H13.3 Multi-Factor Validation Design Contract Freeze

Status: `PASS`

## Source

```text
SOURCE_H13_2_RESULT =
MULTI_FACTOR_DESIGN_REQUIRED

H13.2 =
PASS_WITH_LIMITS
```

## Frozen Question

```text
Which combination of:

1. symbol-membership persistence
2. evidence-accumulation horizon
3. symbol-subset regime-mixing tolerance

provides sufficient validation density and temporal validity
without weakening H10's quality/sample requirements?
```

## Frozen Design Space

Candidate cells:

```text
A3_SLOW_UPDATE x B2_2_MONTH_CONTIGUOUS
A3_SLOW_UPDATE x B3_3_MONTH_CONTIGUOUS
A2_FIXED x B2_2_MONTH_CONTIGUOUS
A2_FIXED x B3_3_MONTH_CONTIGUOUS
```

Reference cell:

```text
A1_DYNAMIC x B3_3_MONTH_CONTIGUOUS_REFERENCE
```

Excluded cells:

```text
A1_DYNAMIC x B1_1_MONTH = EXCLUDED_BY_PRIOR_H13_2_DESIGN_FINDING
A1_DYNAMIC x B2_2_MONTH_CONTIGUOUS = EXCLUDED_BY_PRIOR_H13_2_DESIGN_FINDING
A2_FIXED x B1_1_MONTH = EXCLUDED_BY_PRIOR_H13_2_DESIGN_FINDING
A3_SLOW_UPDATE x B1_1_MONTH = EXCLUDED_BY_PRIOR_H13_2_DESIGN_FINDING
```

Cell catalog:

```text
historical-h13-validation-density/data/h13_3_design_cell_catalog.jsonl
```

## Slow-Update Semantics

```text
SLOW_UPDATE_V1:

symbol subset may change only at
the start of a new 3-month evidence block

membership remains immutable
through the whole validation block

validation outcomes cannot alter
membership inside that block
```

## Mixing Guard

```text
SYMBOL_SUBSET_REGIME_COUNT
SUBSET_SWITCH_COUNT
DOMINANT_SUBSET_SHARE
MEAN_SUBSET_JACCARD

SUBSET_REGIME_MIXING =
LOW | MODERATE | HIGH
```

A block is studyable only if:

```text
sample adequate
AND
subset-regime mixing within frozen tolerance
```

## Selection Hierarchy

```text
1. sample adequacy
2. temporal validity
3. subset-mixing guard
4. number of usable independent blocks
5. lower membership churn
6. shorter evidence horizon
```

Quality metrics remain `DESCRIPTIVE_ONLY`.

## Acceptance

```text
H13_3_MULTI_FACTOR_VALIDATION_DESIGN_CONTRACT_FREEZE = PASS

DESIGN_SPACE_FROZEN = PASS
SYMBOL_MEMBERSHIP_SEMANTICS_FROZEN = PASS
EVIDENCE_HORIZON_SEMANTICS_FROZEN = PASS
SUBSET_REGIME_MIXING_GUARD_FROZEN = PASS
SUBSET_REGIME_MIXING_SEMANTICS_FROZEN = PASS
DESIGN_SELECTION_RULES_FROZEN = PASS
DESIGN_CELLS_FROZEN = 5

QUALITY_METRICS_USED_FOR_DESIGN_SELECTION = NO
MARKET_REPLAY_V2_USED = NO

NEW_THRESHOLD_SEARCH = 0
NEW_POLICY_PARAMETER_SEARCH = 0
NEW_POLICY_CANDIDATE = NONE

PRODUCTION_CHANGE = BLOCKED
```

H13.3 freezes a design contract only. H13.4 may execute studyability metrics
under this frozen design space. Policy search remains closed.
