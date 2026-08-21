# H14.2 G6 — sufficiency reachability audit

## Scope and verdict

This audit compares the MF2 and MF4 decision space without reading outcome, quality, win rate, or PnL. It does not modify the model, policy, schedules, or G5 thresholds.

**Verdict: `STRUCTURALLY_UNREACHABLE` under the currently frozen schedules and decision implementation.** Prospective accumulation must not be resumed as a path toward the present G5 disagreement gates until a separately governed research-contract design review establishes a genuinely divergent prospective schedule or decision rule.

The implementation is conditionally capable of exclusive buckets if membership schedules differ. That condition is absent from the current frozen configuration, is not observation-dependent, and has no automatic transition in the observer.

## Static decision-path comparison

Both designs call `H14ProspectiveObserver._design_decision` with the same canonical observation. The function has no design-specific branch other than the schedule payload.

| Decision input/rule | MF2 | MF4 | Can currently diverge? |
|---|---|---|---|
| Canonical observation | Shared | Shared | No |
| Symbol membership | ETHUSDT, BNBUSDT | ETHUSDT, BNBUSDT | No |
| Posterior input | Not consumed | Not consumed | No |
| Design-specific threshold | None | None | No |
| Regime eligibility | Constant `True` | Constant `True` | No |
| Candidate action | Shared `current_policy_action` | Shared `current_policy_action` | No |
| Actionable set | BUY, SELL | BUY, SELL | No |

For each design:

```text
eligible = symbol in current_symbol_subset AND regime_eligible

if eligible AND current_policy_action in {BUY, SELL}:
    shadow_action = current_policy_action
else:
    shadow_action = HOLD
```

The reachable buckets are therefore:

| Bucket | Logical condition | Current frozen schedules |
|---|---|---|
| `BOTH_SAME_ACTION` | Both eligible and shared action is BUY/SELL | Reachable; observed 4 times |
| `NEITHER` | Shared action is non-actionable, or both ineligible | Reachable; observed 643 times |
| `MF2_ONLY` | MF2 member, MF4 non-member, shared action BUY/SELL | Impossible: current membership difference is empty |
| `MF4_ONLY` | MF4 member, MF2 non-member, shared action BUY/SELL | Impossible: current membership difference is empty |
| `BOTH_DIFFERENT_ACTION` | Both actionable with different sides | Impossible in this implementation because both copy one shared action |

## Historical decision-space probe

The probe evaluated all 647 authoritative pairs and also enumerated BUY, SELL, HOLD, IGNORE, and BLOCK_ENTRY across BTCUSDT, ETHUSDT, and BNBUSDT using the frozen schedules.

```text
authoritative pairs                 647
membership_different                  0
decision_different                    0
MF2_ONLY                              0
MF4_ONLY                              0
BOTH_DIFFERENT_ACTION                 0
```

All 647 pairs received the same upstream observation, the same action, identical membership truth values, and no design-specific posterior or threshold.

Distance to a disagreement path:

- Posterior distance: not applicable; posterior is not read by the shadow-decision function.
- Threshold distance: not applicable; there is no MF2/MF4-specific threshold.
- Membership distance to either exclusive bucket: one symbol must enter the symmetric difference between the schedules.
- Membership distance to make both required exclusive subgroups possible in the current three-symbol universe: MF2 must both add one MF4-excluded symbol and exclude one MF4-included symbol, or an equivalent governed two-sided divergence must be frozen.

A read-only counterfactual with MF2 `{BTCUSDT, ETHUSDT}` and MF4 `{ETHUSDT, BNBUSDT}` proves conditional implementation reachability: BTC produces MF2-only, ETH shared, and BNB MF4-only. This counterfactual is not an authorized schedule and was not persisted.

## Temporal implication

MF2's schedule says its next permitted update boundary is `2026-10-13T08:50:07Z`; MF4 is fixed. Permission to update is not an actual transition, and the transition stream currently contains zero rows. The initial 60-day horizon ends at approximately that same boundary, so waiting through the horizon with the current schedules cannot generate disagreement.

No low-rate stochastic explanation can change this result: an observation cannot enter a branch whose configuration predicate is always false.

## Descriptive projections

These projections do not replace G5 thresholds:

```text
observed continuous span                 6.05 days
authoritative observations                647
actionable observations                     4
actionable rate                         0.661/day
projected total days to 400 actionable  605.2

disagreement observations                   0
projected days to 350 disagreement       UNBOUNDED
projected days to 175 MF2-only           UNBOUNDED
projected days to 175 MF4-only           UNBOUNDED
```

## G6 definition of done

```text
MF2 decision path documented             PASS
MF4 decision path documented             PASS
MF2-only logical branch identified        YES, conditional on schedule divergence
MF4-only logical branch identified        YES, conditional on schedule divergence
different-action branch identified        NO
historical decision-space probe           PASS
outcome/PnL accessed                       NO
policy/model modified                      NO
G5 thresholds modified                     NO
reachability verdict                       STRUCTURALLY_UNREACHABLE
```

## Governance consequence

Do not count additional elapsed time as progress toward the current G5 discriminative sample and do not resume long-running accumulation on the assumption that observation volume will create disagreements. The next authorized state is research-contract design review. Any future schedule divergence must be frozen prospectively, must respect MF2's permitted boundary, and must not use observed outcome/PnL to select membership.

