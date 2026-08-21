# H14.2 Checkpoint #681 Integrity Baseline

Status: `G0_BASELINE_FROZEN = PASS`

This artifact freezes the state observed at checkpoint #681 before integrity
remediation. It does not modify, reinterpret, delete, or validate any historical
row as authoritative.

## Frozen identity

```text
checkpoint_sequence          = 681
checkpoint_generated_at      = 2026-08-19T12:01:03Z
checkpoint_file_sha256       = 6ddd601108bbdca29527a032c40a8e7a2223b065b431e769b32d68ab2ab7efd4
checkpoint_payload_hash      = b57df46889a00be1c1ebe7b5b41788a615c68807befe3f4a6da2fa311147f7e2
repository_commit            = 1f358cfbcc35be217f7d3d19b3fecb9d90b9b87a
```

## Reconfirmed stream state

| Stream | Rows | SHA-256 |
|---|---:|---|
| Analysis | 652 | `9192aa6e7e12111ff108560d2019ec109967d8854c36df4597cb5c0db2eedf27` |
| Decisions | 1,304 | `8aa32ad6d4c3f8507d91d3f31447cf62bc4fd0a52022ca092c671569e2dd8e7b` |
| Accounting | 652 | `f7ffefc3985c4f8f8a8cc3b0b9bc4d0f86e93d8814f3a5da6cd9b91bccd94b58` |
| MF2 transitions | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

```text
SHARED_ACTIONABLE            = 4
MF2_ONLY_ACTIONABLE          = 0
MF4_ONLY_ACTIONABLE          = 0
NEITHER_ACTIONABLE           = 648
LOCAL_PRODUCTION_COVERAGE    = 215 / 223 = 96.412556%
```

## Frozen anomalies

```text
TIMESTAMP_FUTURE_ROWS        = 84
TEST_CONTAMINATION_ROWS      = 3
CANONICAL_COLLISION_GROUPS   = 1
CANONICAL_COLLISION_ROWS     = 2
```

The canonical collision is the pair of distinct `BNBUSDT` records at
`2026-08-17T22:45:00Z`. The contamination records carry release
`dummy-dep` and feature snapshot hash `dummy-hash`.

## Governance state

```text
timestamp_semantics          = FAIL
stream_purity                = FAIL
canonical_uniqueness         = FAIL
temporal_horizon             = INSUFFICIENT
actionable_sample            = INSUFFICIENT
quality_evaluation           = BLOCKED
H14.3                        = BLOCKED
```

Checkpoint #681 and its raw streams remain immutable inputs to later quarantine
and authoritative reconstitution phases.
