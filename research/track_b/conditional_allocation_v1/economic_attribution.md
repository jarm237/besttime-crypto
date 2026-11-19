# Track B1 Economic Attribution — Fixed Initialization Ablation & Timing Decomposition

## 1. Executive Summary & Attribution Verdict
- **INCREMENTAL_TRAINING_VALUE:** `B1_CONDITIONAL_RULE_EFFECT / TRAINING_VALUE_NOT_DEMONSTRATED`
- **B1_FROZEN_VERDICT:** `B1_NO_INCREMENTAL_VALUE` (Locked — Preserved)

### Key Finding:
The historical economic performance of Track B1 (Net CAGR +11.64% on full diagnostic) is **almost entirely attributable to the pre-designed mathematical structure of the regime-conditioned rule**, and **NOT to learned neural weights**.
A fixed initialization model (`B1_UNTRAINED`, with bias=0.0 and positive Softplus coefficients = 1.0) achieves virtually identical economic results across all 4 chronological splits with 0.00% difference in CAGR and identical trade execution counts.

---

## 2. Parameter Comparison: Trained vs Untrained

| Parameter | Trained (Epoch 1 Checkpoint) | Untrained (Initial Specification) | Absolute Difference |
| :--- | :---: | :---: | :---: |
| `bias` | `-0.001000` | `0.000000` | `0.001000` |
| `positive_trend_coef` | `1.000632` | `1.000000` | `0.000632` |
| `positive_risk_coef` | `0.999368` | `1.000000` | `0.000632` |
| `positive_breadth_coef` | `0.999368` | `1.000000` | `0.000632` |

> [!NOTE]
> Because early stopping on validation loss selected Epoch 1, the optimizer took only a single micro-step (~1e-3). Hence, the learned head never diverged from its initial hand-crafted mathematical form.

---

## 3. Economic Ablation Across Chronological Splits

### TRAIN Window (2022-01-01 → 2023-12-31)

| Metric | B1 Trained | B1 Untrained | Delta (Trained - Untrained) | Track A v1 (Frozen) | Delta (Trained - Track A) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Net PnL (USDT)** | $+3,191.26 | $+3,191.28 | **$-0.02** | $+2,758.11 | **$+433.15** |
| **Net CAGR** | +14.87% | +14.87% | **-0.00%** | +12.96% | **+1.90%** |
| **Max Drawdown** | -28.84% | -28.84% | +0.01% | -28.12% | -0.71% |
| **Calmar Ratio** | 0.52 | 0.52 | +0.00 | 0.46 | +0.05 |
| **Sharpe Ratio** | 0.63 | 0.63 | +0.00 | 0.58 | +0.05 |
| **Annualized Turnover** | 6.40x | 6.40x | -0.00x | 3.97x | +2.42x |
| **Total Fees (USDT)** | $332.42 | $332.45 | $-0.03 | $211.17 | $+121.25 |
| **Number of Trades** | 88 | 88 | 0 | 23 | 65 |
| **Average BTC Exposure** | 50.6% | 50.6% | -0.0% | 49.9% | +0.7% |
| **Multiplier Distribution** | Mean: 1.018, Med: 1.042 | Mean: 1.018, Med: 1.042 | Identical | N/A (1.000) | N/A |

### VALIDATION Window (2024-01-01 → 2024-12-31)

| Metric | B1 Trained | B1 Untrained | Delta (Trained - Untrained) | Track A v1 (Frozen) | Delta (Trained - Track A) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Net PnL (USDT)** | $+7,283.20 | $+7,283.07 | **$+0.12** | $+7,825.10 | **$-541.90** |
| **Net CAGR** | +72.65% | +72.65% | **+0.00%** | +78.05% | **-5.40%** |
| **Max Drawdown** | -33.11% | -33.12% | +0.00% | -30.69% | -2.43% |
| **Calmar Ratio** | 2.19 | 2.19 | +0.00 | 2.54 | -0.35 |
| **Sharpe Ratio** | 1.44 | 1.44 | +0.00 | 1.53 | -0.09 |
| **Annualized Turnover** | 10.38x | 10.38x | -0.00x | 4.79x | +5.59x |
| **Total Fees (USDT)** | $380.63 | $380.73 | $-0.10 | $172.48 | $+208.15 |
| **Number of Trades** | 62 | 62 | 0 | 12 | 50 |
| **Average BTC Exposure** | 79.6% | 79.6% | -0.0% | 76.5% | +3.1% |
| **Multiplier Distribution** | Mean: 1.228, Med: 1.347 | Mean: 1.228, Med: 1.347 | Identical | N/A (1.000) | N/A |

### REUSED_TEST Window (2025-01-01 → 2026-11-18)

| Metric | B1 Trained | B1 Untrained | Delta (Trained - Untrained) | Track A v1 (Frozen) | Delta (Trained - Track A) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Net PnL (USDT)** | $-2,645.78 | $-2,645.71 | **$-0.07** | $-3,349.00 | **$+703.22** |
| **Net CAGR** | -15.07% | -15.07% | **-0.00%** | -19.49% | **+4.42%** |
| **Max Drawdown** | -38.64% | -38.65% | +0.00% | -42.08% | +3.44% |
| **Calmar Ratio** | -0.39 | -0.39 | -0.00 | -0.46 | +0.07 |
| **Sharpe Ratio** | -0.46 | -0.46 | -0.00 | -0.69 | +0.23 |
| **Annualized Turnover** | 7.87x | 7.87x | -0.00x | 6.40x | +1.47x |
| **Total Fees (USDT)** | $392.20 | $392.20 | $+0.00 | $311.50 | $+80.70 |
| **Number of Trades** | 82 | 82 | 0 | 30 | 52 |
| **Average BTC Exposure** | 58.6% | 58.6% | -0.0% | 54.6% | +4.0% |
| **Multiplier Distribution** | Mean: 1.110, Med: 1.203 | Mean: 1.110, Med: 1.203 | Identical | N/A (1.000) | N/A |

### FULL_DIAGNOSTIC Window (2022-01-01 → 2026-11-18)

| Metric | B1 Trained | B1 Untrained | Delta (Trained - Untrained) | Track A v1 (Frozen) | Delta (Trained - Track A) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Net PnL (USDT)** | $+7,119.38 | $+7,119.39 | **$-0.01** | $+5,419.98 | **$+1,699.39** |
| **Net CAGR** | +11.64% | +11.64% | **-0.00%** | +9.28% | **+2.37%** |
| **Max Drawdown** | -38.64% | -38.65% | +0.00% | -42.08% | +3.44% |
| **Calmar Ratio** | 0.30 | 0.30 | +0.00 | 0.22 | +0.08 |
| **Sharpe Ratio** | 0.50 | 0.50 | +0.00 | 0.44 | +0.06 |
| **Annualized Turnover** | 7.37x | 7.37x | -0.00x | 4.67x | +2.70x |
| **Total Fees (USDT)** | $1,641.52 | $1,641.67 | $-0.15 | $1,047.28 | $+594.25 |
| **Number of Trades** | 230 | 230 | 0 | 63 | 167 |
| **Average BTC Exposure** | 59.6% | 59.6% | -0.0% | 57.2% | +2.5% |
| **Multiplier Distribution** | Mean: 1.096, Med: 1.189 | Mean: 1.096, Med: 1.189 | Identical | N/A (1.000) | N/A |

---

## 4. Granular Timing Attribution (B1 vs Track A v1)

### 4.1 Decision Breakdown on Full Diagnostic Period (1,782 Days)

| Decision Group | Days Count | % of Time | Avg BTC Return | Avg Delta Exposure | Cum PnL Excess vs Track A |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **B1 Reduced Exposure** | 329 | 18.5% | +0.03% | -0.08 | **$+121.47** |
| **B1 Increased Exposure** | 453 | 25.4% | +0.12% | +0.16 | **$+1,989.35** |
| **Identical Exposure** | 1000 | 56.1% | +0.03% | 0.00 | **$-425.97** |

- **Total Net Dollar Excess:** **$+1,684.85**

### 4.2 Fat-Tail & Decision Concentration Analysis
- **Top 5 Gaining Days Sum:** **$+1,926.91** (accounts for **114.4%** of total excess profit).
- **Top 10 Gaining Days Sum:** **$+3,299.67** (accounts for **195.8%** of total excess profit).
- **Top 5 Worst Days Sum:** **$-1,566.71**.

#### Top 5 Positive Attribution Days:
| Date | Group | Delta Exposure | BTC 1-Day Return | Dollar Excess PnL |
| :--- | :---: | :---: | :---: | :---: |
| 2026-09-18 | `B1_INCREASED_EXPOSURE` | +0.30 | +6.63% | **$+453.85** |
| 2024-05-20 | `B1_INCREASED_EXPOSURE` | +0.29 | +7.30% | **$+421.93** |
| 2026-09-21 | `B1_INCREASED_EXPOSURE` | +0.30 | +5.25% | **$+382.72** |
| 2025-07-10 | `B1_INCREASED_EXPOSURE` | +0.30 | +4.21% | **$+350.99** |
| 2026-08-21 | `B1_INCREASED_EXPOSURE` | +0.28 | +5.76% | **$+317.40** |

#### Top 5 Negative Attribution Days (Whipsaw / Churn Drag):
| Date | Group | Delta Exposure | BTC 1-Day Return | Dollar Excess PnL |
| :--- | :---: | :---: | :---: | :---: |
| 2026-06-02 | `B1_INCREASED_EXPOSURE` | +0.13 | -6.10% | **$-259.62** |
| 2025-06-12 | `B1_INCREASED_EXPOSURE` | +0.28 | -4.52% | **$-279.55** |
| 2025-08-29 | `B1_INCREASED_EXPOSURE` | +0.28 | -3.48% | **$-306.08** |
| 2026-01-20 | `B1_INCREASED_EXPOSURE` | +0.27 | -4.08% | **$-318.67** |
| 2025-08-14 | `B1_INCREASED_EXPOSURE` | +0.31 | -4.57% | **$-402.79** |

---

## 5. Synthesis & Scientific Conclusion
1. **Zero Evidence of Neural / Machine Learning Alpha:**
   The model never learned anything during training; the optimizer settled at Epoch 1 with weights identical to initialization within 0.001. All behavior originates from the hand-crafted Sigmoid rule with Softplus coefficients.
2. **Pre-Designed Rule Sensitivity:**
   The rule structure $0.5 + \sigma(1.0 \cdot z_{\text{trend}} - 1.0 \cdot z_{\text{risk}} + 1.0 \cdot z_{\text{breadth}})$ dynamically adjusted exposure, scaling down exposure during high downside risk days (recovering losses during bear drops) and scaling up exposure during strong multi-asset breadth. However, this dynamic adjustment increased trade counts from 63 to 230 and fee costs by +$594.
3. **Protocol Adherence:**
   Under the registered Validation-first protocol, Track B1 failed to achieve risk-adjusted superiority on the 2024 validation window (Calmar 2.19 vs 2.54). Hence, the locked verdict remains `B1_NO_INCREMENTAL_VALUE`.
   No further training, B2 pilots, or neural models should be explored.