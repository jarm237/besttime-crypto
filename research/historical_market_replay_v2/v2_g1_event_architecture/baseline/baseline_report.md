# HMR-V2-G1.0: Event Architecture Baseline Report

This document freezes the baselines for the **HMR-V2-G1** research redesign. It compares the raw candidate generator (V1) against the filtered candidate pool (V2.3) at the frozen evaluation horizons.

---

## 1. Baseline Comparison (72-bar and 8-bar horizons)

| Metric | V1 Raw Generator | V2.3 Filtered Pool | Delta / Direction |
|:-------|:----------------:|:------------------:|:------------------|
| **Candidate Count ($n$)** | `1175` | `60` | `-1115` (starvation blocker) |
| **Dominant Family Share** | `95.1%` (SMA50_BREAK) | N/A | Concentrated pool |
| **Mean Gross @ 72 bars** | `-22.62 bps` | `-19.45 bps` | `+3.17 bps` |
| **Median Gross @ 72 bars** | `-19.15 bps` | `-13.23 bps` | `+5.92 bps` |
| **Gross > 30bps Rate @ 72** | `8.9%` | `11.7%` | `+2.8%` |
| **Gross > 40bps Rate @ 72** | `5.1%` | `5.0%` | `-0.1%` |
| **Net+ Rate @ 72 bars** | `16.4%` | `20.0%` | `+3.6%` |
| **Spearman Correlation @ 8 bars** | `+0.4227` | `+0.0732` | `-0.3496` (information loss) |

---

## 2. Research Contract Constraints

Any event architecture design evaluated in **V2-G1** must adhere to:
* **PIT Correctness**: Point-in-time features only; no future lookahead.
* **Deterministic Replay**: Executions must be fully reproducible.
* **No Active Changes**: No active canary, epoch, or production deployments.

```text
G1_BASELINE_FROZEN = PASS
```
Any candidate generator update must be compared directly against this baseline matrix to measure economic quality improvement and sample sufficiency.
