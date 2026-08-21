# H14 final research verdict

This file is the canonical H14 entry point. Its machine-readable seal is `h14_final_branch_state.json`; the gate history is `h14_research_decision_ledger.md`.

## Canonical verdict

```text
Research branch: H14
Status: CLOSED
Final verdict: RESEARCH_HARD_STOP
Failure class: INFEASIBLE_RESEARCH_DESIGN
Model failure: NO
Pipeline integrity failure: NO
```

The frozen `SLOW_UPDATE_V1` versus `FIXED` membership-schedule estimand cannot accumulate statistically meaningful prospective evidence within the operational horizon of the current three-symbol population.

This is not a failed model conclusion. H14 did not evaluate whether either schedule, model, or policy was economically better.

## Statistical basis

```text
Minimum meaningful effect                 rate ratio 1.50
Required power                            0.80
Two-sided alpha                           0.05
Dependence design effect                  1.50
Adjusted primary requirement              144 exclusive events per arm
Primary-only expected calendar horizon    approximately 261.5 days
G5 v1 operational expected horizon        approximately 363 days
60-day detectable rate ratio              approximately 2.16 or larger
```

A 60-day design is underpowered for the frozen meaningful effect. A primary-only revision still requires roughly nine months; G5 v1 requires approximately one year after operational margin. Neither is accepted for the current H14 program.

## Final branch state

```text
H14 integrity                  PASS
H14 provenance                 PASS
H14 canonical uniqueness       PASS
H14 score semantics            PASS
H14 sufficiency design         VALID_BUT_INFEASIBLE

G6 reachability                STRUCTURALLY_UNREACHABLE_CURRENTLY
G7 divergence design           VOLUME_INFEASIBLE
G8 statistical feasibility     RESEARCH_HARD_STOP

H14.3                          BLOCKED_FINAL
Prospective collection         DISABLED_BY_GOVERNANCE
Activation                     NOT_ARMED
Transition                     ABSENT
Post-divergence clock          NOT_STARTED
Runtime/model/policy           UNCHANGED
```

Therefore there is no H14 activation, transition, prospective continuation, H14.3 evaluation, or further H14 gate.

## Evidence preservation

- The 647 authoritative rows remain preserved as valid pre-divergence integrity and behavior evidence.
- They do not count toward a future discrimination horizon.
- Raw checkpoint #681 remains immutable.
- G5 v1 remains immutable and unsuperseded.
- G5 v2 is absent.
- No H14 prospective outcome or PnL was accessed or used.
- The previously disclosed incidental display of legacy H13 quality summaries was not used in G7/G8 design selection or power calculations.

## Revisit boundary

H14 is not resumable. A future investigation must use a new research revision or successor branch and may be proposed only if at least one of these conditions is independently established:

1. The research estimand changes.
2. The eligible population materially expands and the new population is formally defined.
3. The effective independent event rate materially increases for a scientifically justified reason.
4. An operational horizon of at least approximately 262 days becomes acceptable.
5. A new design demonstrates adequate power for the unchanged meaningful effect without using H14 outcomes or silently weakening thresholds.

The following are insufficient reasons to reopen H14:

- more calendar time happened to pass;
- the current market changed;
- MF2 membership happened to change;
- additional samples are desired;
- the frozen thresholds feel conservative.

## Successor decision

`NO_SUCCESSOR_AUTHORIZED`.

Expanded-universe membership research or a genuinely contrastive policy/model research family may be proposed later, but either would be a new estimand and must begin with population, endpoint, power, and feasibility design before runtime changes.
