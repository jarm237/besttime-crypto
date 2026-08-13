# H13.4 Multi-Factor Validation Design Execution

Status: `PASS_WITH_LIMITS`

## Scope

H13.4 executed the five H13.3-frozen design cells using studyability metrics only. It did not run Market Replay V2, did not select a policy candidate, and did not use EV/PnL or any other quality metric for design selection.

## Accounting

```text
H13_4_MULTI_FACTOR_VALIDATION_DESIGN_EXECUTION = PASS_WITH_LIMITS
H13_4_DESIGN_OUTPUT = MULTI_FACTOR_DESIGN_ADEQUATE
DESIGN_CELLS_EXPECTED = 5
DESIGN_CELLS_EVALUATED = 5
DESIGN_BLOCKS_EXPECTED = 12
DESIGN_BLOCKS_ACCOUNTED_FOR = 12
CELL_ID_DUPLICATES = 0
BLOCK_ID_DUPLICATES = 0
DESIGN_CONTRACT_HASH_MISMATCH = 0
QUALITY_METRICS_USED_FOR_DESIGN_SELECTION = NO
MARKET_REPLAY_V2_RERUN = NO
NEW_THRESHOLD_SEARCH = 0
NEW_POLICY_PARAMETER_SEARCH = 0
NEW_POLICY_CANDIDATE = NONE
POLICY_SEARCH = CLOSED
PRODUCTION_CHANGE = BLOCKED
```

## Evidence Modes

```text
MF1 = LABELED_EXISTING, QUALITY_COMPARABILITY = FULL
MF2..MF5 = PRE_LABEL_PROXY, QUALITY_COMPARABILITY = NOT_AVAILABLE
```

MF1 can use existing labeled evidence because dynamic three-month semantics match the frozen H10/H13 data. MF2 through MF5 remain pre-label studyability lanes because fixed and slow-update membership semantics require a future frozen membership schedule and counterfactual replay before quality evidence is comparable.

## Cell Metrics

| Cell | Role | Mode | Blocks | Sample rate | Mixing pass rate | Usable blocks | Min sample | Median sample | Churn | Output note |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| MF1 | baseline_reference_not_default_candidate | LABELED_EXISTING | 2 | 1.000 | 0.500 | 1 | 16 | 18.5 | 1 | reference; one high-mixing block |
| MF2 | candidate_design_cell | PRE_LABEL_PROXY | 3 | 1.000 | 1.000 | 3 | 45 | 50 | 0 | top studyability tier |
| MF3 | candidate_design_cell | PRE_LABEL_PROXY | 2 | 1.000 | 1.000 | 2 | 68 | 74.0 | 0 | studyable but lower usable-block count |
| MF4 | candidate_design_cell | PRE_LABEL_PROXY | 3 | 1.000 | 1.000 | 3 | 45 | 50 | 0 | top studyability tier |
| MF5 | candidate_design_cell | PRE_LABEL_PROXY | 2 | 1.000 | 1.000 | 2 | 68 | 74.0 | 0 | studyable but lower usable-block count |

## Selection Result

```text
H13_4_DESIGN_OUTPUT = MULTI_FACTOR_DESIGN_ADEQUATE
TOP_STUDYABILITY_TIER = MF2, MF4
TIE_RESOLUTION = UNRESOLVED_BY_FROZEN_H13_3_HIERARCHY
QUALITY_METRICS_USED_FOR_DESIGN_SELECTION = NO
```

The frozen hierarchy identifies MF2 and MF4 as the top studyability tier: both have adequate proxy sample density, temporal validity, low subset-regime mixing, three usable independent two-month blocks, zero churn, and the shorter evidence horizon. H13.3 did not freeze an additional preference between slow-update and fixed membership when these metrics tie, so H13.4 preserves the tie rather than injecting a post-result quality or preference rule.

## Boundary

```text
NEW_POLICY_CANDIDATE = NONE
POLICY_SEARCH = CLOSED
MARKET_REPLAY_V2_RERUN = NO
PRODUCTION_CHANGE = BLOCKED
```

If a fixed or slow-update design is preferred after H13.4, the next valid step is H13.5 to freeze the preferred design and exact membership schedule. Counterfactual quality replay can only occur after that freeze.
