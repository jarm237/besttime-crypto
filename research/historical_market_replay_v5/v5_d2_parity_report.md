# HMR-V5-D2: Research/Runtime Parity Replay Report

> **Timestamp**: `2026-08-16T17:38:25.825957+00:00` | **Status**: `PASS`

## 1. Parity Audit Results

This audit verified the feature computation, scaling standardizations, model score calculations, threshold rules, and serialization decisions between the offline research environment and the mock online production runtime.

| Asset | Max Probability Diff | Decision Mismatches | Parity Verdict |
| :--- | :---: | :---: | :---: |
| `BTC` | 2.22e-16 | 0 | **`PARITY_MATCH`** |
| `ETH` | 2.22e-16 | 0 | **`PARITY_MATCH`** |
| `BNB` | 2.22e-16 | 0 | **`PARITY_MATCH`** |

### Parity Gates Evaluation Status

| Gate | Description | Status |
| :--- | :--- | :---: |
| `D2-G0` | Artifact integrity (Checksum verification) | **`PASS`** |
| `D2-G1` | Feature parity (Values match exactly) | **`PASS`** |
| `D2-G2` | Score parity (LogReg math matches exactly) | **`PASS`** |
| `D2-G3` | Decision parity (Threshold filter matches exactly) | **`PASS`** |
| `D2-G4` | Execution-policy parity (P4 serialization matches) | **`PASS`** |
| `D2-G5` | Exit-contract parity (E4 exits match) | **`PASS`** |
| `D2-G6` | Deterministic replay (Identical seed reproducibility) | **`PASS`** |
| `D2-G7` | Restart/idempotency (State persistence) | **`PASS`** |
