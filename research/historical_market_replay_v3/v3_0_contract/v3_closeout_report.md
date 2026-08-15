# HMR-V3 Research Program Final Closeout Report

---

## 1. Final Closeout Status

```text
HMR-V3 RESEARCH STATUS                COMPLETE / CLOSED
STRATEGY FAMILY RESULT                REJECTED (VOLATILITY COMPRESSION BRIDGES)
CANDIDATE SELECTION STATUS            FAIL (HIGHLY TOXIC CANDIDATES OUT-OF-DISCOVERY)
NET TRADABLE ALPHA                    NOT DEMONSTRATED

FURTHER V3 MODEL DEVELOPMENT          PROHIBITED (STOP 3 TRIGGERED)
```

---

## 2. The V3 Evidence Chain

The HMR-V3 program shifted the research methodology to Outcome-First Discovery, sampling every 15-minute bar to isolate structural precursors to clean trend moves:

1. **Economic Event Vocabulary (V3.2)**: Defined targets (`UP_MOVE`, `DOWN_MOVE`, `NET_POSITIVE`, `MFE/MAE`) across a fixed grid of horizons.
2. **Event Clustering (V3.4)**: Extracted 1,698 independent events over Period A (2023-01-01 to 2024-06-30) after collapsing adjacent overlapping signals.
3. **Pre-Event Characterization (V3.6)**: Showed high statistical divergence for volatility and channel positioning compared to the baseline market background:
   - `range_pos`: KS statistic **0.4228** ($p = 3.64 \times 10^{-213}$)
   - `atr_compression`: KS statistic **0.3287** ($p = 3.31 \times 10^{-127}$)
   - `bollinger_width`: KS statistic **0.2213** ($p = 2.76 \times 10^{-57}$)
4. **Hypothesis Freeze (V3.13)**: Formulated three rounded prospective rules (V3-H1: Compression Breakout, V3-H2: ATR Squeeze, V3-H3: Volatility Slope) and frozen in the JSON registry.
5. **Validation Replay (V3.14-V3.20)**: Replayed all three frozen setups over the out-of-discovery Period B/C (2024-07-01 to 2024-12-31):
   - **V3-H1**: n=4182, mean return **`-39.15 bps`**, `Gross>30` = **1.8%**.
   - **V3-H2**: n=5620, mean return **`-40.27 bps`**, `Gross>30` = **2.4%**.
   - **V3-H3**: n=43161, mean return **`-11.38 bps`**, `Gross>30` = **13.5%**.

---

## 3. Scientific Conclusions & Stop 3 Trigger

Although volatility compression and price channel proximity are statistically distinct prior to large trends in discovery, translating these configurations into simple prospective rules yields **severe candidate toxicity** out-of-discovery:
- The mean return of all candidate families dropped below `-11 bps` (reaching as low as `-40 bps` for H1/H2).
- The large-move base rate collapsed to $1.8\% - 13.5\%$ (significantly worse than the random baseline of $18.9\%$).

This triggers **Stop 3: Candidate population remains toxic (mean gross $\le -15$ bps)**. 

No model development (V3.21) or exit optimization (V3.28) is authorized. The HMR-V3 event-discovery branch is officially closed.
