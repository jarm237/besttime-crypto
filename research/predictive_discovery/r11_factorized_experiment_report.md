# R11 Unified Neural Factorized Allocation Experiment Report

**Clean Aligned Horizon**: 2022-01-16 00:00 UTC to 2026-11-16 19:00 UTC (42,379 hourly bars, 253 weekly decisions)  
**Selected Checkpoint**: Seed 101 (`r11_factorized_model.pt`) | Selected strictly via Validation 2024 balanced score  
**Parameter Parity**: R11 Factorized Policy: **1746** params | R10 Joint-Softmax Policy: **1746** params (**Exact Match**)  
**Execution & Accounting**: Next-open execution (`open[t_dec]`) | Base Fee: 12.0 bps | Stress Fee: 25.0 bps  

---

## 1. Executive Scientific Verdict

### Final Verdict: **`FACTORIZED_ALLOCATION_INCREMENTAL_VALUE_NOT_SUPPORTED`**

> [!IMPORTANT]
> **Key Empirical Findings**:
> 1. **Controlled Architectural Head Comparison**: Under identical data, Train-calibrated risk budget (0.0282), Adam optimizer, and 1,746 parameters, Factorizing the output head into macro continuous exposure $E(t) = \text{sigmoid}(z_{\text{exp}})$ and micro relative crypto weights $q_i(t) = \text{softmax}(z_{\text{asset}})$ resulted in full-horizon net return of **+498.68%** (Sharpe **1.003**, MaxDD **-54.55%**), compared to R10 Joint-Softmax at **-6.09%** (Sharpe **0.265**, MaxDD **-64.66%**).
> 2. **Exposure Distribution & Saturation**: R11 realized an average risky exposure of **61.4%** (38.6% cash). Saturation diagnostics show that the sigmoid exposure head spent **0.0%** of decisions near zero (<5% crypto), **0.0%** near full (>95% crypto), and **100.0%** in intermediate continuous allocation.
> 3. **Validation & Holdout Generalization**: In Validation 2024, R11 achieved **+64.48%** (vs R10: **+94.21%**). In Reused Holdout 2025–2026, R11 delivered **-40.08%** (vs R10: **-44.37%**).
> 4. **Incremental Value vs Benchmark Alpha**: R11 demonstrates that factorizing the output head alters training dynamics and gradient flow, but does NOT establish standalone alpha over disciplined static controls (Static 50/50: **+43.02%**, Vol Target 25%: **+58.22%**).

---

## 2. Phase A: Focused R10 Findings Closure

| Audit Item | Status | Detailed Resolution |
| :--- | :--- | :--- |
| **Horizon Scope Audit** | **RESOLVED** | CONFIRMED: R10 cash timing permutation evaluated full 4.84-year horizon, including holdout. |
| **Empirical P-Value Formulation** | **RESOLVED** | Applied Laplace pseudo-count $(c+1)/(N+1)$: Temporal Return $p = 0.0020$ (not 0.0); Sharpe $p = 0.0140$; Circular Shift Return $p = 0.0040$; Sharpe $p = 0.0158$. |
| **Epistemic Classification** | **RESOLVED** | Observed historical association (2022 cash avoidance) is not predictive generalization. Dynamic timing skill was unproven out of sample. |
| **Temporal Permutation Caveat** | **RESOLVED** | Temporal shuffling held relative asset selection schedule fixed, altering cross-interaction between cash and risky selection. |
| **Head Interference Epistemic Status** | **RESOLVED** | Hypothesis tested in R11; previously unproven because R8 vs R10 simultaneously varied the objective. |

---

## 3. Gradient Attribution & Training Dynamics

### Initial vs Final Gradient Norm Diagnostics (Selected Checkpoint)
| Metric | Epoch 0 (Initialization) | Epoch 60 (Convergence) | Interpretation |
| :--- | :---: | :---: | :--- |
| **Exposure Head Gradient Norm** | `0.006156` | `0.014805` | Macro risk allocation gradient signal |
| **Selection Head Gradient Norm** | `0.000428` | `0.004064` | Micro cross-asset relative weighting gradient |
| **Shared Encoder Gradient Norm** | `0.006598` | `0.016314` | Feature representation updates |
| **Cross-Asset Interaction Norm** | `0.000847` | `0.004571` | Cross-sectional market pooling updates |
| **Exposure / Selection Grad Ratio** | `14.39x` | `3.64x` | Relative gradient pressure on exposure vs selection |
| **Growth vs Risk Cosine Alignment** | `+0.6092` | `-0.0832` | Direct measure of objective gradient conflict (<0 = opposing) |

> [!NOTE]
> **Gradient Alignment Finding**: The empirical cosine similarity between the log-growth gradient and the thresholded downside risk gradient is **+0.6092** at initialization and **-0.0832** at convergence. This proves quantitatively whether growth and risk gradients are conflicting (< 0) or orthogonal (~0).

---

## 4. Controlled Architectural Comparison: R10 vs R11

| Metric | R10 Joint-Softmax Policy | R11 Factorized Unified Policy | Delta (R11 - R10) |
| :--- | :---: | :---: | :---: |
| **Head Architecture** | Joint Softmax $[z_1..z_N, z_{\text{cash}}]$ | Factorized $E(t) \cdot q_i(t) + (1-E)$ | Two-Head Decoupling |
| **Parameter Count** | 1,746 params | 1,746 params | 0 (Strict Parity) |
| **Selected Model Seed** | Seed 202 | Seed 101 | Cross-Seed Val Selection |
| **Full Horizon Net Return** | **-6.09%** | **+498.68%** | **+504.77%** |
| **Annualized Sharpe** | `0.265` | `1.003` | `+0.738` |
| **Annualized Sortino** | `0.363` | `1.450` | `+1.087` |
| **Max Drawdown** | `-64.66%` | `-54.55%` | `+10.11%` |
| **Average Realized Cash** | `12.1%` | `38.5%` | `+26.4%` |
| **Average Risky Exposure** | `87.9%` | `61.5%` | `-26.4%` |
| **Train Return (2022–2023)** | `-14.43%` | `+501.26%` | `+515.69%` |
| **Validation Return (2024)** | `+94.21%` | `+64.48%` | `-29.73%` |
| **Holdout Return (2025–2026)** | `-44.37%` | `-40.08%` | `+4.29%` |
| **Gross Asset Turnover** | `9.80` | `195.84` | `+186.04` |
| **Total Transaction Fees** | `$118.68` | `$13447.09` | `$+13328.41` |

---

## 5. Seed Stability Evaluation (Seeds 42, 101, 202)

| Metric | Seed 42 | Seed 101 | Seed 202 | Mean | Std Dev | Range |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **R11 Cash Weight (%)** | `50.1%` | `38.5%` | `50.0%` | `46.2%` | `5.44%` | `11.60%` |
| **R11 Net Return (%)** | `+401.97%` | `+498.68%` | `+11.13%` | `+303.93%` | `210.77%` | `487.55%` |
| *R10 Cash Weight Reference* | `19.9%` | `8.1%` | `12.1%` | `13.4%` | `4.90%` | `11.80%` |
| *R10 Net Return Reference* | `-2.45%` | `-12.11%` | `-6.09%` | `-6.88%` | `3.98%` | `9.66%` |

---

## 6. Regime & Exposure Breakdown by Calendar Year

| Year | Market Regime | Mean Risky Exp | Min Exp | Max Exp | R11 Return | R10 Return | BTC Return |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **2022** | Crypto Bear | `60.5%` | `24.2%` | `80.4%` | `+24.12%` | `-63.02%` | `-61.59%` |
| **2023** | Early Recovery | `63.4%` | `28.2%` | `79.8%` | `+388.51%` | `+132.21%` | `+155.80%` |
| **2024** | Strong Bull | `63.3%` | `32.2%` | `81.9%` | `+64.48%` | `+94.21%` | `+120.31%` |
| **2025** | Holdout / Consolidating | `61.6%` | `28.6%` | `81.0%` | `-9.66%` | `-16.76%` | `-7.15%` |
| **2026** | Holdout / Consolidating | `57.8%` | `23.8%` | `82.0%` | `-33.80%` | `-33.31%` | `-26.03%` |

---

## 7. Comprehensive Benchmark & Stress Evaluation Matrix

| Strategy | Fee Regime | Net Return | Sharpe (95% CI) | Max Drawdown | Train | Val 2024 | Holdout | Cash | Turnover |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **R11 Factorized Policy (Selected)** | 12.0 bps | `+498.68%` | `1.003` [0.06, 1.59] | `-54.55%` | `+501.26%` | `+64.48%` | `-40.08%` | `38.5%` | `195.84` |
| **R11 Factorized Policy (Stress 25 bps)** | 25.0 bps | `+363.92%` | `0.894` [-0.05, 1.51] | `-58.69%` | `+441.98%` | `+54.96%` | `-45.30%` | `38.5%` | `195.84` |
| **R11 Factorized (1h Execution Delay)** | 12.0 bps | `+549.86%` | `1.037` [0.11, 1.63] | `-53.25%` | `+523.96%` | `+68.61%` | `-38.85%` | `38.5%` | `195.87` |
| **R10 Joint-Softmax Policy (Selected)** | 12.0 bps | `-6.09%` | `0.265` [-0.70, 1.12] | `-64.66%` | `-14.43%` | `+94.21%` | `-44.37%` | `12.1%` | `9.80` |
| **Static 50/50 BTC/Cash Weekly** | 12.0 bps | `+43.02%` | `0.423` [-0.45, 1.24] | `-40.27%` | `+8.12%` | `+52.54%` | `-13.79%` | `49.9%` | `3.55` |
| **Static BTC/Cash Exp-Matched Train** | 12.0 bps | `+47.24%` | `0.422` [-0.45, 1.24] | `-45.42%` | `+7.76%` | `+62.35%` | `-16.41%` | `42.0%` | `3.55` |
| **Static BTC/Cash Exp-Matched R11 Realized** | 12.0 bps | `+48.74%` | `0.422` [-0.45, 1.24] | `-47.53%` | `+7.46%` | `+66.69%` | `-17.56%` | `38.5%` | `3.51` |
| **R7 Vol Target 25% (No Buffer)** | 12.0 bps | `+62.29%` | `0.500` [-0.38, 1.32] | `-42.48%` | `+23.74%` | `+59.82%` | `-18.50%` | `39.9%` | `34.32` |
| **R7 Vol Target 25% (5% Buffer)** | 12.0 bps | `+58.22%` | `0.482` [-0.39, 1.31] | `-42.54%` | `+21.98%` | `+58.52%` | `-18.73%` | `40.0%` | `33.24` |
| **Benchmark BTC Buy & Hold** | 12.0 bps | `+50.57%` | `0.420` [-0.45, 1.24] | `-67.38%` | `-1.83%` | `+120.31%` | `-31.20%` | `0.0%` | `1.00` |
| **Benchmark EW 8-Coin Weekly** | 12.0 bps | `-19.20%` | `0.259` [-0.71, 1.11] | `-70.41%` | `-21.32%` | `+103.38%` | `-50.40%` | `0.0%` | `10.77` |
| **Benchmark 100% Cash** | 12.0 bps | `+0.00%` | `0.000` [0.00, 0.00] | `0.00%` | `+0.00%` | `+0.00%` | `+0.00%` | `100.0%` | `0.00` |

---

## 8. Epistemic Assessment & Path Forward

> [!TIP]
> **Synthesis of Neural Portfolio Architecture Evolution (R8 -> R10 -> R11)**:
> 1. **R8 (Unbudgeted Loss + Joint Head)**: Collapsed into the 94.6% cash shelter due to a 20.4x downside gradient dominance. +37.43% return, but Sharpe 0.884 was primarily a cash-preservation effect with near-zero bull participation (+9.58% in 2024).
> 2. **R10 (Risk-Budgeted Loss + Joint Head)**: Cured the cash shelter (cash dropped to 12.1%), surged in 2024 bull (+94.21%), but suffered -63.02% in 2022 bear market and -44.37% in 2025–2026 holdout, yielding net -6.09% across full horizon.
> 3. **R11 (Risk-Budgeted Loss + Factorized Head)**: Disentangled macro exposure $E(t)$ from micro relative selection $q_i(t)$. Average cash allocation was 38.5%.
> 4. **Core Scientific Lesson**: Factorization of network heads modifies the parameter landscape and gradient routing, but DOES NOT by itself generate predictive market timing or out-of-sample alpha without causal predictive input features. A neural network cannot time macro cycles unless the feature space contains genuine, non-spurious cross-cycle regime information.

**STOP RULE APPLIED**: Bounded R11 factorized allocation experiment complete. Scientific verdict established: `FACTORIZED_ALLOCATION_INCREMENTAL_VALUE_NOT_SUPPORTED`.