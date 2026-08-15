# HMR-V2 Research Program Final Closeout Report

---

## 1. Final Closeout Status

```text
HMR-V2 RESEARCH STATUS                COMPLETE / CLOSED
STRATEGY FAMILY RESULT                REJECTED AS TRADABLE STRATEGY
CANDIDATE ARCHITECTURE SUCCESS        G1-D CONTEXTUAL ARCHITECTURE VALIDATED
WITHIN-POOL PREDICTION STATUS         FAIL (NO PREDICTIVE PIT INFORMATION)
NET TRADABLE ALPHA                    NOT DEMONSTRATED

FURTHER SMA50 OPTIMIZATION            PROHIBITED (FINAL HARD STOP)
```

---

## 2. The Root Cause Evidence Chain

This research program systematically investigated and eliminated alternative hypotheses for the failure of the V1/V2 SMA50-crossing strategy family:

1. **Candidate Duplication?** 
   - *Result*: **NO**. G1.1 multiplicity audit confirmed multiplicity $\approx 1.00$ (deduplication did not improve pool economics).
2. **Candidate Toxicity?** 
   - *Result*: **YES**. Corrected by the G1 contextual candidate architecture redesign.
3. **Architecture Overfit?** 
   - *Result*: **NO**. The G1-D compression and structural room filters successfully transferred, doubling the `Gross>30` base rate (~19% vs 9% baseline) and raising the mean return from `-22 bps` to `-1.5 bps` across a 2-year pre-2025 corpus and a 3-month OOS validation window.
4. **Model Architecture Issue?** 
   - *Result*: **NO**. Replacing the V1 meta-model with Logistic Regression and Gradient Boosting Classifier baselines (V2.4.3) still resulted in near-zero OOS ranking capability.
5. **Contextual Feature Insufficiency?** 
   - *Result*: **YES**. The V2.4D within-pool information audit confirmed a mean OOS ROC-AUC of **0.5446** and flat decile monotonicity lifts (Case A).
6. **Regime / Metadata Subgroup Rescue?** 
   - *Result*: **NO**. Slicing by volatility, trend, and symbols showed no stable, positive subgroups passing the temporal stability gate (D7).
7. **Follow-Through Feature Rescue?** 
   - *Result*: **NO**. Volatility contraction, approach velocity, and volume dynamics features (V2-F2) showed zero predictive value inside the G1-D pool (Spearman $|\rho| \le 0.016$, zero passing features).

---

## 3. The Candidate-Generation Paradox

The core scientific conclusion of the HMR-V2 program is the separation of candidate quality from strategy rankability:

- **G1-D Contextual Selection (Success)**: 
  Early compressed crossings with structural room (`break_distance_atr <= 0.25`, `candle_body_atr <= 0.15`, `room_to_structure_atr >= 1.0`) successfully filter out the toxic subset of SMA50 crossings, delivering a near-neutral population.
- **Within-Pool Prediction (Failure)**: 
  Once the toxic subset is removed, the remaining pool of crossings behaves like a random distribution. Point-in-time features are insufficient for predicting which of the ~19% positive events will generate a large directional expansion.

```
V1:  indicator transition → candidate (structurally toxic, mean -22 bps)
G1:  market setup + fresh transition + room → candidate (near-neutral, mean -1.5 bps)
V2:  within-pool ranking → execution (FAIL, no predictive PIT information)
```

---

## 4. Prohibited Actions (SMA50 Hard Stop)

No further engineering or optimization resources may be spent on the SMA50 candidate family. The following activities are strictly **PROHIBITED**:
- **Further model training** (no GBT/XGBoost/random forest space expansion).
- **Further feature engineering** on the compressed SMA50 state.
- **Further threshold tuning** or candidate eligibility adjustments (e.g. relaxing room gates).
- **Exit optimization** (no TP/SL search or maker/taker cost mapping on G1-D).

The research value of the SMA50 family is retained as a scientific documentation of transition states, but its tradable strategy value is **rejected**.

---

## 5. Transition to HMR-V3

Any future research into trend transitions must abandon the SMA50-crossing anchor and start as a new program: **HMR-V3**.

### Research Machinery Reuse
HMR-V3 may reuse the infrastructure built during V1 and V2:
- The Point-in-Time (PIT) historical replay engine.
- Canonical economic target configurations (`gross_return_72` and `gross_return_8`).
- Walk-forward temporal fold cross-validation frameworks.
- Governance and manifest controls.

### Strategy Starting Point (Economic Event Discovery)
Unlike V1/V2 which began with technical indicators, HMR-V3 must reverse the direction of inquiry:
1. **Target Discovery**: Locate historical instances of large, clean price expansions ($>30/40$ bps moves after realistic friction).
2. **Context Characterization**: Audit the market structures (volatility contraction, liquidity shifts, multi-timeframe breaks) that preceded those moves.
3. **Prospect Formulation**: Translate these observations into prospective PIT rules.
4. **Model Development**: Train classifiers on the prospect pool using a strict multi-stage data partition protocol (OOS validation window frozen prior to modeling).
