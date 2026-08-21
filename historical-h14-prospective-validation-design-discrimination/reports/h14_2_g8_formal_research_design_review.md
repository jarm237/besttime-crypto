# H14.2-G8 formal research design and G5 feasibility review

## Frozen lineage

```text
G5 v1 SHA-256  f8e5702d3f6660dcb51de67054579a8a08d80347a0441828cbd77cec242d4675
G7 contract    8c1e9b21d22ef5da79ed59f748980d3e8e86f8d27e046fb1b44322d885ed5f25
G7 checkpoint  b8172112ca07f482a73833bd9ae3a2655442c9129a5797451ef871109311dac9
```

G5 v1 is not overwritten or marked superseded. Collection remains blocked and no transition is frozen.

## Formal inference target

| Item | Frozen definition |
|---|---|
| Population | Canonical prospective market opportunities for the existing BTCUSDT, ETHUSDT, BNBUSDT universe under the shared frozen policy |
| Treatment contrast | MF2 `SLOW_UPDATE_V1` membership schedule versus MF4 `FIXED` membership schedule |
| Primary endpoint | Ratio of MF2-only to MF4-only actionable-event rates per UTC calendar day |
| Primary estimand | `rate_ratio = lambda_MF2_only / lambda_MF4_only`; superiority is two-sided because either schedule may produce more exclusive opportunities |
| Unit of inference | UTC calendar day |
| Observation hierarchy | 15-minute symbol cycles nested within symbol and day; raw rows are not treated as independent samples |
| Minimum meaningful effect | Rate ratio `1.50` or its reciprocal `0.667` |
| Rationale | A schedule must change exclusive actionable opportunity rate by at least 50% to justify the operational complexity of slow membership updates; smaller effects are not decision-relevant for this research question |
| Type-I error | Two-sided alpha `0.05` |
| Target power | `0.80` |
| Dependence allowance | Design-effect multiplier `1.50` for serial and cross-symbol clustering, applied before calendar projection |
| Availability margin | `1.20` calendar multiplier after the outcome-blind event-rate projection |

Secondary descriptive endpoints are shared-actionable rate, total actionable rate, overlap rate, symbol-stratified exclusive counts, and schedule transition count. Outcome quality and economic performance remain outside G8.

## Power derivation

For a log rate-ratio test with approximately equal arm event counts, the unadjusted expected event requirement per exclusive arm is:

```text
E_arm = 2 × (z_0.975 + z_0.80)^2 / log(1.50)^2
      = 95.484
```

Applying the predeclared clustering allowance:

```text
ceil(95.484 × 1.50) = 144 events per exclusive arm
```

G7's outcome-blind upper-bound candidate rate is `4 / 6.052083 = 0.66093` exclusive events per arm-day. Therefore:

```text
144 / 0.66093                    = 217.9 observed days
217.9 × 1.20 availability margin = 261.5 calendar days
```

At 60 days the expected raw count is only 39.7 per arm, or 26.4 effective events after the dependence allowance. That design can detect only an approximate rate ratio of 2.16 at the frozen alpha/power, materially larger than the 1.50 minimum meaningful effect.

## G5 v1 assessment

G5 v1's `175 + 175` exclusive thresholds exceed the new primary-endpoint requirement of `144 + 144` and remain statistically conservative under the declared assumptions. Its `400 actionable` threshold originated from the separate worst-case Bernoulli precision objective of approximately ±5 percentage points at 95% confidence.

Thus the G5 thresholds are not merely arbitrary quotas. The incompatibility is calendar volume:

```text
G5 v1 projected threshold time      302.6 days
20% operational availability margin 363.1 days
review horizon                       approximately 365 days
```

## Branch assessment

| Design | Estimand preserved | Statistical sufficiency | Calendar feasible | Governance result |
|---|---|---|---|---|
| G5 v1 / 60 days | Yes | Only if unreachable counts occur; expected counts are insufficient | No | Reject |
| G5 v1 / ~365 days | Yes | Yes | Mathematically, but not operationally accepted | Reject for current H14 program |
| Formal primary-only G5 v2 / ~262 days | Yes | Yes for primary rate ratio; weaker secondary precision | No | Do not adopt |
| Expanded symbol universe | No, not without redefining population | Unknown | Potentially better | Separate estimand review required |
| Faster cycle cadence | Nominally | Invalid without effective-sample proof | Misleading | Reject |
| Random assignment with identical policy | No meaningful slow-vs-fixed contrast | No | No | Reject |

## Final verdict

`RESEARCH_HARD_STOP` for the current H14 population, estimand, and observation availability.

The statistically lighter primary-only design still needs about 261.5 calendar days. G5 v1 needs approximately one year with margin. Such horizons materially increase regime drift, release-contract drift, operational continuity risk, and schedule-version complexity. Reducing requirements to the 60-day available volume would only power effects around a 2.16 rate ratio, which exceeds the frozen minimum meaningful effect and would make the study insensitive to decision-relevant differences.

No G5 v2 is frozen because it would not make the experiment operationally feasible. G5 v1 remains immutable and unsuperseded. H14 may reopen only through a formal population/estimand revision or materially different outcome-blind observation availability—not by threshold tuning against available volume.

## Data-use boundary

This review uses only G7 outcome-blind counts, timestamps, membership definitions, and actionability availability. H14 outcome/PnL and H13 quality summaries are prohibited design inputs and were not used in any effect-size, variance, power, or branch calculation.

