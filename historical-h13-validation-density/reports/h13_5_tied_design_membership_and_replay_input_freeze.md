# H13.5 Tied Design Membership And Replay Input Freeze

Status: `PASS`

## Scope

H13.5 preserves the H13.4 top-tier tie between `MF2` and `MF4`. It freezes both membership schedules, hypothetical decisions, and replay inputs before any Market Replay V2 outcome access. It does not choose between slow-update and fixed membership.

## Acceptance

```text
H13_5_TIED_DESIGN_MEMBERSHIP_AND_REPLAY_INPUT_FREEZE = PASS
SOURCE_H13_4 = PASS_WITH_LIMITS
SOURCE_TOP_TIER_DESIGNS = MF2, MF4
TOP_TIER_TIE_PRESERVED = YES
POST_HOC_TIE_BREAK = 0
MF2_MEMBERSHIP_SCHEDULE_FROZEN = PASS
MF4_MEMBERSHIP_SCHEDULE_FROZEN = PASS
MEMBERSHIP_SCHEDULE_FROZEN_BEFORE_REPLAY = PASS
HYPOTHETICAL_DECISIONS_FROZEN = PASS
REPLAY_INPUT_FROZEN = PASS
MARKET_REPLAY_V2_USED = NO
NEW_THRESHOLD_SEARCH = 0
NEW_POLICY_PARAMETER_SEARCH = 0
NEW_POLICY_CANDIDATE = NONE
POLICY_SEARCH = CLOSED
PRODUCTION_CHANGE = BLOCKED
DESIGNS_FROZEN = 2
DESIGN_BLOCKS_FROZEN = 6
HYPOTHETICAL_DECISIONS_FROZEN_COUNT = 296
REPLAY_INPUT_ROWS = 296
UNIQUE_CANONICAL_EXECUTION_PATHS = 148
MF2_REPLAY_INPUT_HASH = 919dbb38c897c674ee105c67e43d5db19e09a183ff5b3107819555b1b2151da7
MF4_REPLAY_INPUT_HASH = b4fae1f255b0002078b17257385d2ae8bb9bb10d4ba4b0991347d929e7c8ea5d
MF2_MEMBERSHIP_SCHEDULE_HASH = 541f377d0e7c7863f607fa4af51f9e8b2c5a0600cc4acd239e6bd54287c90ae9
MF4_MEMBERSHIP_SCHEDULE_HASH = 3c5a7bfac8c5ae0247bb21f8731b8be357ed9c1c116fd80ce2a408dbf627afd3
CONTRACT_SHA256 = 75067d3a0a10bbbf970fe31aac3da41d1cf3a5541970e6f34517570c067b0f0f
```

## Frozen Designs

| Design | Label | Blocks | Decisions | Replay input hash | Membership schedule hash |
| --- | --- | ---: | ---: | --- | --- |
| MF2 | SLOW_UPDATE_2M | 3 | 148 | `919dbb38c897c674ee105c67e43d5db19e09a183ff5b3107819555b1b2151da7` | `541f377d0e7c7863f607fa4af51f9e8b2c5a0600cc4acd239e6bd54287c90ae9` |
| MF4 | FIXED_2M | 3 | 148 | `b4fae1f255b0002078b17257385d2ae8bb9bb10d4ba4b0991347d929e7c8ea5d` | `3c5a7bfac8c5ae0247bb21f8731b8be357ed9c1c116fd80ce2a408dbf627afd3` |

## Decision Rule

```text
historical H10 analysis at T
+ frozen H13.5 design membership for block
+ frozen H10 policy identity
+ raw_direction/technical/posterior eligibility
= frozen hypothetical validation decision
```

No policy parameter, threshold, symbol schedule, or quality criterion was selected after inspecting H13.4 results. The replay input is frozen but not replayed in H13.5.

## Replay Boundary

```text
MARKET_REPLAY_V2_USED = NO
QUALITY_OUTCOME_ACCESSED = NO
POLICY_SEARCH = CLOSED
NEW_POLICY_CANDIDATE = NONE
PRODUCTION_CHANGE = BLOCKED
```

The next valid phase is H13.6, where these frozen inputs may be consumed by Market Replay V2 and evaluated against independent quality gates. H13.6 still must not choose a design by highest EV; it may only eliminate a design that fails an independent frozen quality gate.
