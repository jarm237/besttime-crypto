# H14.2-G7 prospective divergence design review

## Decision

The H13 source contracts establish that H14 compares **membership-update designs**, not different models or trading policies:

- MF2: `SLOW_UPDATE_2M` / `SLOW_UPDATE_V1`
- MF4: `FIXED_2M` / `FIXED`
- Shared policy identity, posterior threshold, technical gates, side, model lineage, and observation stream

The frozen estimand is therefore:

> Under one shared policy and observation universe, does a prospectively frozen slow-update membership schedule provide a more studyable and later quality-valid validation design than a fixed membership schedule?

Any later conclusion is about schedule/update semantics. It must not be stated as “the MF2 model is better than the MF4 model.” Symbol-stratified reporting is mandatory because membership is the treatment and symbol behavior remains a potential effect modifier.

## Pre-divergence freeze

```text
authoritative observations       647
design-actionable                  4
effective disagreement             0
MF2-only                            0
MF4-only                            0
MF2 membership          ETHUSDT, BNBUSDT
MF4 membership          ETHUSDT, BNBUSDT
action rule              identical
regime eligibility       always true
design posterior rule    none in runtime shadow decision
```

These rows remain valid `PRE_DIVERGENCE_EVIDENCE`. They are excluded from any future post-divergence 60-day clock and discriminative quotas.

## Candidate review

### Same-observation policy divergence

Rejected for G7. It changes the frozen estimand from validation membership design to policy/model comparison. No co-equal MF2/MF4 policy candidates are frozen in the H13/H14 source contracts.

### Membership schedule divergence

Semantically admissible because membership persistence is the original treatment. No concrete transition is selected in this batch:

- the H13 source does not provide an outcome-free rule that mandates a new MF2 subset;
- choosing a subset only because it creates both exclusive buckets would be quota engineering;
- every possible MF2 subset in the three-symbol universe fails G5 volume reachability under the outcome-free H14 decision-space probe.

### Deterministic randomized assignment

Rejected. Assignment would compare exposure allocation rather than slow-update versus fixed membership, while both arms would still run identical decision logic. It also cannot overcome the observed upper bound of eight shared-policy actionable observations in 6.05 days.

## Transition decision

No `effective_at`, transition ID, or post-transition schedule hash is frozen. The existing MF2 permission boundary at `2026-10-13T08:50:07Z` remains permission only. Current schedule hashes remain immutable.

Before a future transition can be armed, a separate governance action must provide an outcome-independent MF2 update rule and demonstrate both structural and volume reachability without modifying G5 silently.

## Outcome-access disclosure

No H14 prospective outcome, future return, trade result, or PnL was accessed. During broad source discovery, the terminal output incidentally exposed legacy H13 quality-summary fields from already completed H13 artifacts. Those values were not used in the estimand, candidate replay, projection, or rejection decision. Because they were displayed, this batch does not claim that all legacy H13 outcome summaries were unseen; no mechanism is selected, which prevents post-exposure design choice.

## Gate state

```text
G7_RESEARCH_ESTIMAND          PASS
G7_DIVERGENCE_MECHANISM       NOT_SELECTED
G7_STATIC_REACHABILITY        PASS_CONDITIONAL
G7_VOLUME_REACHABILITY        FAIL
G7_TRANSITION_CONTRACT        NOT_OPENED
G7_RUNTIME_IMPLEMENTATION     NOT_STARTED
G7_SHADOW_SANITY              NOT_STARTED
prospective collection        BLOCKED
```

