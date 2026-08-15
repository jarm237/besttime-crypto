# HMR-V1.3E Closeout Report

**Phase**: Efficacy Audit & Exit counterfactuals  
**Status**: ✅ **COMPLETE**  
**Date**: 2026-08-15  

---

## Strategic Verdict

**We are officially closing V1.3E and stopping the threshold/calibration tuning workstream as a primary focus.** 

The empirical evidence indicates that the most appropriate diagnosis for the current system is **CASE B: ALPHA_TOO_SMALL_FOR_COST_STRUCTURE**.
* **Best Observed Gross Edge**: `≈ +6 bps` (at 32-bar horizon exit)
* **All-in Cost Structure (Friction)**: `≈ 15 bps`
* **Deficit**: `≈ 9 bps/trade`

This is a structural magnitude gap. Bps-level adjustments to the score threshold (e.g., trying to tune from `0.2119 → 0.20 → 0.18`) cannot bridge a ~9 bps gap without severely starving candidate count and degrading statistical significance.

---

## Acceptance Criteria & Diagnostics Checklist

| Diagnostic Area | Verdict | Evidence / Finding |
| :--- | :---: | :--- |
| **TECHNICAL_SIGNAL_EDGE** | **NO** | Raw technical triggers without model filtering do not exhibit net positive returns. |
| **RAW_MODEL_DISCRIMINATION** | **YES** | Raw score yields solid sorting power (ROC-AUC `0.68–0.71` on lifecycle targets). |
| **LIFECYCLE_DISCRIMINATION** | **YES** | The model's predictions align meaningfully with downstream trading outcome ranks. |
| **CURRENT_EXECUTION_GROSS_EDGE**| **TOO SMALL**| Best gross edge is `~+6.23 bps`, far below break-even requirements. |
| **CURRENT_NET_TRADABLE_EDGE** | **NO** | All tested realistic exit horizons yield negative net returns after 15 bps friction. |
| **CALIBRATION** | **BROKEN / NOT PRIORITY**| Starved class sizes destroy isotonic calibrator resolution. Tuning is halted. |
| **THRESHOLD TUNING** | **STOP** | Discontinued. Cannot solve the economic deficit. |
| **TRAINING_LABEL_ALIGNMENT** | **NOT DIRECTLY PROVEN**| `current_label` is unavailable in the dataset; training-label AUC cannot be measured. |
| **LIFECYCLE TARGET ALIGNMENT** | **MEANINGFUL** | AUC of `0.68–0.71` confirms predictions are non-trivial and carry ranking signal. |

---

## Key Experimental Findings

### 1. E2: Discrimination Matrix (Label Alignment Audit)
* **Status**: `TRAINING_LABEL_ALIGNMENT = NOT DIRECTLY PROVEN`
* Since `current_label` is unavailable, we cannot directly measure training-label AUC.
* However, `LIFECYCLE TARGET ALIGNMENT = MEANINGFUL`. Raw scores show ROC-AUC scores of `0.68–0.71` against lifecycle targets (e.g., `profitable_8bar` SELL ROC-AUC = `0.7054`, `lifecycle_profitable_gross` SELL ROC-AUC = `0.6826`).
* **Conclusion**: This disproves the hypothesis that the model is predicting complete noise, though it does not fully audit the original training objective.

### 2. E3: TP/SL Counterfactual Surface
* **Status**: Classified as `EXIT_SURFACE_HYPOTHESIS` (not `PROFITABLE_EXIT_POLICY`).
* **Finding**: A setting of `TP = 0.5×ATR` and `SL = 1.0–2.5×ATR` showed a gross return of `+14.6 bps`. 
* **Wording Correction**: This surface is based on an MFE/MAE approximation. Because it assumes perfect order fills at the boundaries, it remains an exit hypothesis rather than a confirmed profitable exit policy.

### 3. E4: Horizon Exit Experiment (Bar-Level Exits)
* **Status**: Highly reliable bar-level/fixed-horizon analysis.
* **Finding**:
  * `EXIT_32BAR` (8h horizon): Gross = `+6.23 bps`, Net = `-8.77 bps`.
  * `EXIT_48BAR` (12h horizon): Gross = `+5.66 bps`, Net = `-9.34 bps`.
  * `CURRENT_TPSL` (ATR-based): Gross = `+5.66 bps`, Net = `-9.34 bps`.
* **Conclusion**: Even under optimal fixed exit horizons, the maximum gross edge of `+6.23 bps` is wiped out by the `15.0 bps` flat friction, confirming that stopping threshold tuning is the correct path.

---

## System State Summary

* **Correctness**: Substantially repaired.
* **Historical Replay**: Trustworthy.
* **Temporal Model Validity**: Proven for research artifact.
* **Technical Raw Alpha**: Absent.
* **Raw Model Ranking**: Meaningful.
* **Lifecycle Prediction**: Meaningful.
* **Net Economic Alpha**: Absent.
* **Primary Blocker**: **EDGE MAGNITUDE < FRICTION**.

---

## Next Phase: HMR-V1.3F (Economic Viability Branch Selection)

We are transitioning the project from an optimization phase to a **decision phase**. The goal of V1.3F is to determine if there is a realistic path for this system family to exceed the `~15–16 bps` break-even edge. 

Three main research branches will be studied:
1. **F1 — Cost-Floor Sensitivity**: Sweep transaction friction (`15, 12, 10, 8, 6, 4, 2 bps`) to find the required cost level.
2. **F2 — Maker Execution Feasibility**: Sweep maker fill ratio and adverse selection scenarios to test execution suitability.
3. **F3 — Edge-by-Horizon Search**: Expand exit horizons to `32, 48, 72, 96, 192 bars` to see if returns scale faster than costs at lower frequency.
4. **F4 — Economic Label Redesign Probe**: Explore alternative regression or higher-threshold classification targets.
5. **F5 — Frequency Economics**: Report turnover, daily trade volume, and daily net expectancy.
