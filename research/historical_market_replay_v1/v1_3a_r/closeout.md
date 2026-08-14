# HMR-V1.3A-R Closeout Report

**Phase**: Semantic Correctness Restoration  
**Status**: ✅ **COMPLETE**  
**Date**: 2026-08-14  

---

## Acceptance Gate Checklist

| Gate | Status | Evidence |
| :--- | :---: | :--- |
| SIDE_MAPPING_SEMANTICS | ✅ PASS | `signal_score.py` no longer inverts P(win) for SELL |
| PROBABILITY_SEMANTICS_END_TO_END | ✅ PASS | R1 `probability_contract.json` + R3 unit tests |
| MODEL_TEMPORAL_VALIDITY | ✅ PASS | `clean_replay/replay.json` gate |
| CALIBRATION_TEMPORAL_VALIDITY | ✅ PASS | Frozen artifact pre2025 v1 unchanged |
| NO_LOOKAHEAD | ✅ PASS | `clean_replay/replay.json` gate |
| DETERMINISTIC_REPLAY | ✅ PASS | `clean_replay/replay.json` gate |
| EXECUTION_ACCOUNTING | ✅ PASS | `clean_replay/replay.json` gate |
| PRODUCTION_POLICY_PATH | ✅ PASS | `clean_replay/replay.json` gate |
| CLEAN_COHORT_GENERATED | ✅ PASS | 0 trades = valid efficacy finding |

---

## Source Code Change

**Single file modified**: `btc_scraper/ml_engine/signal_score.py`

```diff
-            model_probability_up = max(0.0, min(1.0, float(meta['probability'])))
-            meta_prob = (
-                1.0 - model_probability_up
-                if action == "SELL"
-                else model_probability_up
-            )
+            model_win_probability = max(0.0, min(1.0, float(meta['probability'])))
+            # CONTRACT: meta['probability'] = P(win | proposed_trade), side-agnostic.
+            model_probability_up = model_win_probability
+            meta_prob = model_win_probability
```

```diff
-                "probability_semantics": "P(up)",
+                "probability_semantics": "P(win_given_proposed_trade)",
```

`decision_engine.py` was **not modified**. Its existing `P(win_given_proposed_trade)` branch and `_execution_probability` fallback already handle the corrected semantics correctly.

---

## Root Cause Chain

```
1. signal_score.py mapped SELL meta_prob = 1.0 - P(win)
2. This mapped P(win) → P(loss) for SELL candidates
3. The worst SELL candidates (lowest P(win)) got the highest meta_prob
4. These passed the posterior threshold and were executed
5. All 318 trades in the buggy baseline were artifacts of this inversion

Additionally:
6. probability_semantics was labeled "P(up)" instead of "P(win_given_proposed_trade)"
7. This caused decision_engine.py to apply a second inversion in some code paths
8. The double-inversion created internal consistency in the bugged system
9. Fixing only signal_score.py (+ semantics label) is sufficient
```

---

## Clean Cohort Results

| Metric | Bugged Baseline | Clean (Fixed) | Δ |
| :--- | ---: | ---: | ---: |
| Technical BUY | 45 | 45 | 0 |
| Technical SELL | 1,130 | 1,130 | 0 |
| Canonical BUY | 0 | 0 | 0 |
| Canonical SELL | 318 | 0 | -318 |
| Executed Trades | 318 | 0 | -318 |
| Net PnL | -$1,695.63 | $0.00 | +$1,695.63 |
| Win Rate | 14.15% | 0.00% | N/A |
| Max Drawdown | 17.31% | 0.00% | -17.31% |

**Interpretation**: All 318 executed trades were artifacts of the semantic inversion bug. With correct semantics, no signals pass the 0.65 posterior threshold because the calibrated model max probability is 16.67%.

---

## Calibration Collapse Diagnosis

| Finding | Value |
| :--- | :--- |
| Training win rate | 1.36% (127/9,347) |
| Calibration win rate | 0.73% (3/409) |
| Isotonic max calibrated prob | 16.67% |
| Sigmoid max calibrated prob | 14.70% |
| Raw ensemble max prob | 41.51% |
| BUY threshold | 0.65 |
| **Samples above threshold** | **0 (all methods)** |

Root causes classified:
- `CALIBRATION_POSITIVE_STARVATION` — 3 wins in 409 samples
- `CALIBRATION_SAMPLE_TOO_SMALL` — 409 samples insufficient
- `TEMPORAL_DISTRIBUTION_SHIFT` — win rate dropped from 1.36% to 0.73%
- `SIDE_DISTRIBUTION_IMBALANCE` — 96.3% SELL signals in calibration

**Strategy Decision**: `NO_CALIBRATION_REPLACEMENT_IN_V1.3A-R` — with 3/409 positive samples, neither isotonic nor sigmoid produces meaningful calibration. This is not a validated endorsement of isotonic (`ISOTONIC_VALIDATED`); it is a deferral. Proper calibrator evaluation (Brier, log loss, reliability, resolution, temporal stability) requires a cohort with sufficient positive class representation and is deferred to V1.3C.

---

## Threshold Provenance

- `buy_threshold = 0.65` and `sell_threshold = 0.35` introduced in commit `fa9669d` (Jun 28, 2026)
- Hardcoded defaults, no dynamic configuration
- Classification: `THRESHOLD_CONTRACT = NOT_YET_VALIDATED`

> **Note**: The asymmetric pair `0.65 / 0.35` was likely designed for `P(up)` semantics, where `SELL threshold = 1 - BUY threshold = 0.35` makes sense (selling when P(up) < 35%). Under the corrected `P(win | proposed_trade)` semantics, both BUY and SELL represent the same quantity (P(win) for that side's trade), and there is no obvious semantic justification for different thresholds per side without side-specific calibration evidence. This must be validated in V1.3B before any threshold optimization.

---

## V1.3B Prerequisites Met

This phase confirms:
1. ✅ Semantic correctness restored
2. ✅ Clean OOS cohort generated (0 trades is a valid efficacy finding)
3. ✅ Calibration collapse root cause known
4. ✅ Threshold provenance audited

V1.3B can now proceed with ablations:
```
CURRENT_CLEAN
TECHNICAL_ONLY
RAW_MODEL
NO_CALIBRATION
NO_META
LONG_ONLY_DIAGNOSTIC
SHORT_ONLY_DIAGNOSTIC
```

---

## Artifacts Generated

```
research/historical_market_replay_v1/v1_3a_r/
├── baseline_manifest.json          (R0)
├── probability_contract.json       (R1)
├── probability_contract.md         (R1)
├── semantic_fix/
│   ├── replay.json                 (R4)
│   └── replay.md                   (R4)
├── calibration/
│   ├── cohort_diagnostics.json     (R5-R6)
│   ├── calibration_root_cause.md   (R5-R6)
│   └── calibration_decision.json   (R8)
├── threshold/
│   └── threshold_provenance.md     (R7)
├── clean_replay/
│   ├── replay.json                 (R10)
│   └── replay.md                   (R10)
├── v1_3a_clean/
│   ├── side_funnel.json            (R11)
│   ├── side_funnel.md              (R11)
│   ├── buy_path_audit.json         (R11)
│   ├── calibration_diagnostics.json (R11)
│   ├── entry_exit_analysis.json    (R11)
│   ├── mechanistic_report.md       (R11)
│   └── trade_decomposition.jsonl   (R11)
└── closeout.md                     (this file)
```

## Scripts Created

| Script | Purpose |
| :--- | :--- |
| `scripts/hmr_v1_3a_r_probability_contract.py` | R1: Verify model probability semantics |
| `scripts/hmr_v1_3a_r_semantic_fix_replay.py` | R4: Run 3-month replay with fix |
| `scripts/hmr_v1_3a_r_calibration_diagnosis.py` | R5-R6: Diagnose calibration collapse |
| `scripts/hmr_v1_3a_r_threshold_provenance.py` | R7: Audit threshold history |
| `scripts/hmr_v1_3a_r_clean_replay.py` | R10: Generate clean replay report |
| `tests/ml_engine/test_probability_contract.py` | R3: Regression tests |
