# HMR-V1.3D-D5: Diagnostic OOS Policy Experiment

> [!WARNING]
> **DIAGNOSTIC OOS POLICY EXPERIMENT — NOT A VALIDATED PRODUCTION POLICY**
>
> This run deliberately disabled three gates to isolate threshold-only behavior:
> - EV gate (`min_ev_pct` set to `-1.0` → pass-through)
> - Kelly sizing gate (`AUTO_TRADE_USE_KELLY=false`)
> - Minimum reward-to-risk gate (`AUTO_TRADE_MIN_RR=0.0`)
>
> These gates are **not confirmed unnecessary**. They were disabled solely for diagnostic isolation.
> This result answers: *"If the score threshold passes through all legacy gates, how does that cohort trade?"*
> Answer: **negative gross and net across all three windows.**

---

## Candidate Policy Configuration

- Gating: raw model probabilities (`use_raw_model=True`)
- Frozen SELL threshold: `sell_prob >= 0.2119` (Top 5% SELL cutoff on Discovery)
- BUY threshold: `buy_prob >= 0.50` (not frozen — no BUY discovery evidence)
- Meta gating: `meta_threshold >= 0.21`, `min_ev_pct >= -1.000` (disabled)

---

## Primary Result: SELL-Only Candidates

> [!IMPORTANT]
> The frozen candidate is **SELL-only** (threshold 0.2119 was derived from Discovery SELL cohort analysis).
> BUY trades in the table below have **no frozen discovery evidence** and must not be used as the headline result.

| Window | Dates | SELL Trades | SELL Gross PnL ($) | SELL Net PnL ($) | SELL Win Rate |
| :--- | :---: | ---: | ---: | ---: | ---: |
| DISCOVERY | 2025-01-01 → 2025-03-31 | 45 | (see combined table) | (see combined table) | est. ~14% |
| VALIDATION | 2025-04-01 → 2025-06-30 | 38 | (see combined table) | (see combined table) | est. ~14% |
| UNTOUCHED_TEST | 2025-07-01 → 2025-09-30 | 38 | (see combined table) | (see combined table) | est. ~13% |

*SELL-only breakdown to be extracted in V1.3E-E1.*

---

## Combined Performance (BUY + SELL)

| Window | Dates | Trades | BUY | SELL | Gross PnL ($) | Net PnL ($) | Win Rate | Profit Factor | MaxDD |
| :--- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DISCOVERY | 2025-01-01 → 2025-03-31 | 50 | 5 | 45 | -83.77 | -250.48 | 14.0% | 0.041 | 3.0% |
| VALIDATION | 2025-04-01 → 2025-06-30 | 43 | 5 | 38 | -28.37 | -171.70 | 14.0% | 0.107 | 2.1% |
| UNTOUCHED_TEST | 2025-07-01 → 2025-09-30 | 48 | 10 | 38 | -145.50 | -305.52 | 12.5% | 0.045 | 3.3% |

---

## Correct Interpretation

```text
OOS win rates (12.5–14.0%) match Discovery (14.0%) consistently.

This is NOT "no temporal overfitting".
This IS "poor economic behavior generalizes across later windows."

The candidate does not fail Discovery and succeed elsewhere.
It fails consistently — which is robustness of FAILURE, not robustness of alpha.
```

### Comparison: ranking horizon vs lifecycle horizon

| Metric | Raw model next-bar ranking | Actual lifecycle (D5) |
|--------|---------------------------|----------------------|
| Win Rate | 58.9% (Top 5% SELL) | 12.5–14.0% |
| Gross mean return | +4.2 bps | Negative across all windows |
| Net expectancy | −11.6 bps | Deep negative |

The gap between 58.9% and 12.5–14.0% is not attributable to a single cause.
See **HMR-V1.3E: Objective Alignment** for causal investigation (E2/E3/E4).

---

## Core Conclusion

```text
DIAGNOSTIC_RESULT           NEGATIVE GROSS AND NET ACROSS ALL THREE WINDOWS
FROZEN_CANDIDATE_STATUS     FAILS ECONOMIC THRESHOLD (net < 0)
TEMPORAL_CONSISTENCY        CONSISTENT FAILURE (not inconsistency / overfitting)
GATE_STATUS                 EV / Kelly / MinRR gates remain valid — not confirmed removable
NEXT_ACTION                 HMR-V1.3E E2 discrimination matrix to determine causal pathway
```
