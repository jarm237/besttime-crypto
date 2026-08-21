# Runtime Remediation Contract v1

Status: `P0_BASELINE_FROZEN = PASS`

Canonical baseline: `runtime_remediation_baseline.json`

Baseline payload SHA-256: `6eaed153158623f7d79ac290e65cd2fb21f380de8888120eb217e5be1b9a2825`

Baseline file SHA-256: `909df17a4af44296b94f5c7b350cd6799ffc18b726b9a8dc3ac9db0cb716c1c0`

## Purpose

This contract freezes the observed behavior and evidence at the start of runtime remediation. It is a comparison anchor, not an assertion that the current behavior is correct, safe to promote, or ready for live money.

P0 is observational. It adds only this contract and its JSON baseline. It does not change runtime, inference, expected-value, S3, scoring, sizing, persistence, artifact-selection, or authorization semantics.

## Non-negotiable governance

- H14 remains `CLOSED` with verdict `RESEARCH_HARD_STOP` and failure class `INFEASIBLE_RESEARCH_DESIGN`.
- H14.3 remains `BLOCKED_FINAL`; collection stays `DISABLED_BY_GOVERNANCE`; activation stays `NOT_ARMED`; transition stays `ABSENT`.
- Raw evidence remains preserved.
- No H14 successor is authorized.
- Real-money live trading remains unauthorized. Legacy enabled/pass flags are not sufficient authorization; the current environment and ML readiness are fail-closed.

## Frozen surfaces

The JSON baseline is canonical for:

- source commit/tree and the preexisting worktree;
- observable release/runtime identity;
- artifact registry, hashes, runtime-scoped artifact observations, and feature order/dtypes;
- decision actions, statuses, fields, rejection reasons, and precedence;
- current EV units and boundary behavior, including the observed mixed-unit defect;
- research per-symbol S3 thresholds and the current runtime non-enforcement behavior;
- historical probability/S3 parity evidence and controlled current-model fixtures;
- scoring, action, context, Kelly, risk, cap, and non-executable-action sizing fixtures;
- targeted/full pytest commands, environment, exact counts, JUnit hashes, and failure fingerprints;
- known ambiguities and contradictions that later phases must remediate explicitly.

## Gate semantics

`PASS` in P0 means the corresponding state was captured, hashed where applicable, and checked for internal consistency. It does not convert a failing regression suite, ambiguous contract, missing S3 enforcement, artifact mismatch, or unsafe edge-case behavior into an accepted target design.

The frozen test baseline is intentionally not green:

- targeted: 169 collected, 168 passed, 1 failed;
- full: 1121 collected, 1116 passed, 5 failed.

Those failures are identified by stable fingerprints in the canonical JSON. Later work must distinguish an intentional fix from an unrelated regression.

## Change-control rule

For every phase after P0:

1. Compare affected fixtures and contracts against `runtime_remediation_baseline.json`.
2. Declare every intended semantic delta before accepting changed output.
3. Preserve all unrelated fixture outputs and governance invariants.
4. Run GitNexus context/impact analysis before edits; the frozen decision, scoring, sizing, and artifact-resolution symbols currently carry HIGH or CRITICAL blast radius.
5. Run targeted checks, the required invariant/end-to-end suite, refresh GitNexus, and inspect change detection against `main`.
6. Never infer live-money or successor authorization from a remediation gate.

## Hash contract

The baseline payload digest is computed from UTF-8 canonical JSON with keys sorted and separators `,` and `:`, after removing `baseline_hashes.runtime_remediation_baseline_payload_sha256`. The separate baseline file digest hashes the final pretty-printed file bytes. A consumer must validate both digests before treating the baseline as frozen.

## P0 decision

All required snapshot gates are present, the governance hard stop is preserved, deterministic fixtures and regression fingerprints are recorded, and the baseline is hash-sealed. Therefore:

`P0_BASELINE_FROZEN = PASS`
