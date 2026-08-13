# H13.7 Final Validation Design Acceptance

Status: `PASS_WITH_LIMITS`

## Decision

```text
H13_7_FINAL_VALIDATION_DESIGN_ACCEPTANCE = PASS_WITH_LIMITS
H13_7_OUTPUT = BOTH_DESIGNS_REMAIN_VIABLE_WITH_LIMITS
SOURCE_H13_4 = PASS_WITH_LIMITS
SOURCE_H13_6 = PASS_WITH_LIMITS
STUDYABILITY_ACCEPTABLE = YES
QUALITY_GATE_ACCEPTABLE = YES
POOLED_QUALITY = POSITIVE
BLOCK_QUALITY_STABILITY = MIXED
QUALITY_GENERALIZATION = NOT_ESTABLISHED
TOP_TIER_TIE_PRESERVED = YES
MF2_STATUS = VIABLE_WITH_LIMITS
MF4_STATUS = VIABLE_WITH_LIMITS
SINGLE_VALIDATION_DESIGN_SELECTED = NO
ROBUST_VALIDATION_DESIGN = NONE
POST_HOC_TIE_BREAK = 0
NEW_POLICY_SEARCH = 0
NEW_THRESHOLD_SEARCH = 0
NEW_POLICY_CANDIDATE = NONE
POLICY_SEARCH = CLOSED
H11_STATUS = BLOCKED_NO_ROBUST_INPUT_CANDIDATE
H12_STATUS = BLOCKED_NO_VALIDATED_POLICY_CANDIDATE
PRODUCTION_CHANGE = BLOCKED
NEXT = H14_PROSPECTIVE_VALIDATION_DESIGN_DISCRIMINATION
```

## Rationale

H13.4 found MF2 and MF4 as a top-tier studyability tie. H13.5 froze both designs before outcome access. H13.6 replayed 148 canonical execution paths once and joined the same outcomes back to 296 design memberships.

MF2 and MF4 both satisfy the quality gate only with limits. Pooled quality is positive, but temporal block quality is mixed: B01 and B02 fail while B03 passes for both designs. That means quality generalization is not established.

## Final Design State

| Design | Studyability | Quality gate | Quality stability | Final status |
| --- | --- | --- | --- | --- |
| MF2 | top-tier tie | PASS_WITH_LIMITS | MIXED | VIABLE_WITH_LIMITS |
| MF4 | top-tier tie | PASS_WITH_LIMITS | MIXED | VIABLE_WITH_LIMITS |

```text
VIABLE != ROBUST != PRODUCTION_APPROVED
ROBUST_VALIDATION_DESIGN = NONE
SINGLE_VALIDATION_DESIGN_SELECTED = NO
```

## Boundary

```text
POST_HOC_TIE_BREAK = 0
NEW_POLICY_SEARCH = 0
NEW_THRESHOLD_SEARCH = 0
NEW_POLICY_CANDIDATE = NONE
POLICY_SEARCH = CLOSED
H11 = BLOCKED_NO_ROBUST_INPUT_CANDIDATE
H12 = BLOCKED_NO_VALIDATED_POLICY_CANDIDATE
PRODUCTION_CHANGE = BLOCKED
```

## Next Lane

```text
NEXT = H14_PROSPECTIVE_VALIDATION_DESIGN_DISCRIMINATION
```

More analysis of the same 148 historical outcomes cannot create a valid discriminator between MF2 and MF4. The next useful evidence is prospective: freeze both designs before new data arrives, measure decision-set overlap and membership divergence, then evaluate quality only after outcomes mature.
