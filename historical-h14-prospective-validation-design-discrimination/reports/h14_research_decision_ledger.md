# H14 research decision ledger

This ledger records why H14 closed. The hard stop follows a staged evidence chain rather than a model-performance judgment.

| Gate | Result | Canonical finding |
|---|---|---|
| G0 — Baseline | PASS | Checkpoint #681 and raw evidence frozen before remediation |
| G1 — Timestamp integrity | PASS | Legacy timezone semantics reconstructed; no future authoritative timestamps |
| G2 — Provenance purity | PASS | Test lineage isolated; unknown/invalid lineage excluded from authoritative evidence |
| G3 — Canonical uniqueness | PASS | Semantic key frozen; entire unresolved BNB collision quarantined |
| G4 — Score semantics | PASS | Score 50 is documented neutral behavior; no observed silent fallback or score collapse |
| G5 — Sufficiency contract | PASS | 60 days, 95% coverage, 400 actionable, 350 disagreements, 175 per exclusive arm frozen before outcomes |
| G6 — Reachability | STRUCTURALLY_UNREACHABLE_CURRENTLY | Identical schedules and one shared action rule cannot create design disagreement |
| G7 — Divergence design | VOLUME_INFEASIBLE | Every admissible membership candidate misses G5 volume within 60 days |
| G8 — Formal statistics | RESEARCH_HARD_STOP | RR 1.50 at alpha 0.05/power 0.80 needs 144 adjusted events per arm and approximately 261.5–363 calendar days |

Decision chain:

```text
data integrity
  -> timestamp/provenance/uniqueness
  -> score semantics
  -> logical reachability
  -> prospective divergence design
  -> statistical power
  -> operational feasibility
  -> RESEARCH_HARD_STOP
```

## Closure invariants

```text
canonical final verdict          PASS
machine-readable branch state    CLOSED
G5 v1                            IMMUTABLE_UNSUPERSEDED
G5 v2                            ABSENT
transition                       ABSENT
collection                       DISABLED_BY_GOVERNANCE
activation                       NOT_ARMED
H14.3                            BLOCKED_FINAL
raw evidence                     PRESERVED
H14 outcome/PnL contamination    NONE
successor research               NOT_AUTHORIZED
```

No further H14 observer restart, periodic sufficiency checkpoint, membership experiment, score audit, historical H14 replay, threshold tuning, or H14 outcome evaluation is authorized by this branch.

