# R11 Economic Attribution & Execution Fidelity Report (Corrected Edition)

**Clean Aligned Horizon**: 2022-01-16 00:00 UTC to 2026-11-16 19:00 UTC (42,379 hours, 253 decisions)  
**Analyzed Model Checkpoint**: Seed 101 (r11_factorized_model.pt)  
**Causal Execution Accounting**: Next-open execution | Pre-trade open rebalancing | 12.0 bps fee rate  

---

## 1. Executive Scientific Verdicts

### Primary Verdict: **`R11_TRAIN_RETURN_DRIVEN_BY_SOL_CONCENTRATION_NOT_GENERALIZED_ALPHA`**

| Hypothesis / Dimension | Verdict | Definitive Empirical Finding |
| :--- | :---: | :--- |
| **Train Return Concentration** | **`True`** | Over **73.7%** of total Train gross PnL ($37,636.99 of $51,050.86) was generated in just **5 discrete weeks** out of 102 Train weeks. |
| **Cash Timing Historical Benefit** | **`True`** | Dynamic cash exposure delivered significant historical value: Counterfactual B (R11 Cash + BTC: **+140.15%**, Sharpe **0.743**) substantially exceeded Static 58% BTC (Counterfactual E: **+47.24%**, Sharpe **0.422**) by avoiding the 2022 bear drawdown (-17.49% vs -39.47%). |
| **Cash Timing Predictive Skill** | **`NOT_ESTABLISHED`** | Predictive generalization across cycles remains unproven: cash timing did not anticipate market shifts out of sample in 2024 or 2025–2026. |
| **Asset Selection Incremental Value** | **`NOT_SUPPORTED`** | **Validation vs Holdout Distinction**: In Validation 2024, Counterfactual D (Selection + Fixed 58% Exp: **+69.74%**) slightly exceeded Counterfactual E (Static 58% BTC: **+62.35%**). However, in Reused Holdout (2025–2026), Counterfactual D lost **-37.71%**, losing more than double Static 58% BTC (**-16.41%**). Standalone selection alpha across cycles is not supported. |
| **Out-of-Sample Generalization** | **`True`** | In Reused Holdout (2025–2026), R11 lost **-40.08%**, dramatically worse than Static 50/50 BTC/Cash (**-13.79%**) and Static 58% BTC (**-16.41%**). |

---

## 2. Phase A: Causal Execution Delay Audit & Numerical Delta

### Baseline Delay=0h Replication Check
- **Reproduction Status**: `EXACT_PARITY_VERIFIED`
- **Published R11 Net Return**: `+498.68%`
- **Re-simulated Causal Net Return**: `+498.67%` (Delta = `-0.0100%`)
- **Sharpe Ratio Match**: `1.002` vs `1.003`

### Causal Delay=1h Order Replay vs Old Implementation
| Metric | Old Bugged Delay=1h | Causal Pending-Order Delay=1h | Delta (Causal - Old) |
| :--- | :---: | :---: | :---: |
| **Net Return** | `+549.86%` | `+549.85%` | `-0.0100%` |
| **Sharpe Ratio** | `1.037` | `1.037` | `+0.000` |
| **Max Drawdown** | `-53.25%` | `-53.25%` | `+0.00%` |
| **Delta vs Baseline (Delay 1h - Delay 0h)** | — | **+51.18%** | Causal 1h execution delay persists |

> [!NOTE]
> **Epistemic Note on Delayed Execution**: Under causal pending-order execution, decisions made at Sunday 00:00 UTC remain unexecuted until Sunday 01:00 UTC, with hour 00:00 evaluating existing holdings. The observed +51.18% gain is an empirical outcome in this sample; it must NOT be asserted as proven Sunday mean-reversion without dedicated cross-asset intraday statistical testing.

---

## 3. Phase B: Training / Replay Cost Parity Audit

### Mathematical Divergence
In spot crypto trading, transaction fees are levied upon **gross asset traded volume** ($V_{\text{traded}} = \sum_i |\Delta \text{asset}_i|$).
In `compute_risk_budgeted_loss()`, turnover drag was modeled using normalized portfolio one-way turnover:
$$\text{Turnover}_{\text{surrogate}} = \frac{1}{2}\left(\sum_{i=1}^N |w_{i, t+1} - w_{i, t}^{\text{drifted}}| + |w_{\text{cash}, t+1} - w_{\text{cash}, t}^{\text{drifted}}|\right)$$
When cash allocation is constant and capital rotates directly between altcoins:
$$\text{Gross Asset Turnover} = \sum_{i=1}^N |w_{i, t+1} - w_{i, t}| = 2 \times \text{One-Way Turnover}$$

| Metric | Value | Economic Context |
| :--- | :---: | :--- |
| **Total Actual Replay Fees** | **$13,447.09** | Exact 12.0 bps fee levied on gross asset traded notional |
| **Training Loss Surrogate Fees** | **$8,168.30** | Modeled fee drag in loss function |
| **Fee Understatement in Loss** | **$5,278.79** (**39.3%**) | Training objective charged only ~half fee during cross-altcoin swaps |
| **Gross-to-One-Way Turnover Ratio** | **1.65x** | Near 2.0x, confirming heavy cross-altcoin rotation |

> [!NOTE]
> **Nuance on Optimization Incentives**: While the training loss fee surrogate was lower than replay fees, the training objective also included an explicit regularization penalty: $\lambda_{\text{turnover}} \cdot \text{turnover}$ (with $\lambda_{\text{turnover}} = 0.002$). Therefore, the fee surrogate understatement cannot be declared the sole causal driver of high turnover; it operated as one component of the combined optimization landscape.

---

## 4. Phase C: Frozen R11 PnL Attribution & Counterfactual Matrix

> [!NOTE]
> **Weight Distinction**: In factorized allocation:
> - **Total Portfolio Asset Weights**: $w_i(t) = E(t) \cdot q_i(t)$, where $\sum_{i=1}^N w_i(t) + w_{\text{cash}}(t) = 1.0$.
> - **Relative Risky-Sleeve Weights**: $q_i(t) = \text{softmax}(z_{\text{asset}_i})$, where $\sum_{i=1}^N q_i(t) = 1.0$ on the risky simplex.

### Cumulative Gross PnL Contribution by Individual Coin (Approximation)
| Coin | Train PnL (2022–2023) | 2023 Bull PnL | Val PnL (2024) | Holdout PnL (2025–2026) | Full Horizon Gross PnL |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **XRPUSDT** | `$3,075.55` | `$2,009.59` | `$24,046.61` | `$21,209.83` | **`$48,331.99`** |
| **SOLUSDT** | `$32,549.94` | `$32,251.13` | `$15,682.30` | `$-4,377.29` | **`$43,854.95`** |
| **ADAUSDT** | `$8,561.76` | `$8,440.49` | `$25,174.40` | `$-4,855.55` | **`$28,880.62`** |
| **BTCUSDT** | `$982.81` | `$1,100.02` | `$-2,433.96` | `$1,162.87` | **`$-288.28`** |
| **ETHUSDT** | `$1,113.31` | `$841.62` | `$404.60` | `$-3,282.60` | **`$-1,764.69`** |
| **LINKUSDT** | `$6,168.56` | `$6,484.79` | `$-11,584.90` | `$-6,310.30` | **`$-11,726.64`** |
| **BNBUSDT** | `$-1,216.26` | `$-876.88` | `$5,626.61` | `$-22,257.83` | **`$-17,847.49`** |
| **LTCUSDT** | `$-184.81` | `$-2,070.76` | `$-11,206.92` | `$-14,590.80` | **`$-25,982.53`** |

> [!IMPORTANT]
> **Residual Audit**: Summing linear per-coin PnL yields **$50,010.97** net PnL, whereas exact MTM portfolio equity gain is **$49,867.30**, producing an exact residual of **$143.67** (0.24% of final equity). This residual exists because the linear sum multiplies pre-trade equity (P_i = V_pre * w_i * R_i) without deducting the upfront transaction fee from deployed capital (V_deployed = V_pre - Fee), compounding across 253 weekly steps. Per-coin attribution is therefore documented as an **analytical approximation**.

### Train PnL Concentration (The 5 Decisive Weeks)
- Total Train Gross PnL: **$51,050.86**
- Top 5 Weeks Combined PnL: **$37,636.99** (**73.7%** of all Train gains)
- Top 10 Weeks Combined PnL: **$51,159.00** (**100.2%**)

| Decision Date | Gross PnL | SOL PnL | ADA PnL | LINK PnL | Fee Paid | Net PnL | Allocation Context |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **2023-12-17** | `$16,077.97` | `$16,065.65` | `$0.53` | `$3.21` | `$56.01` | **`$16,021.95`** | 63–77% allocation into high-beta pump |
| **2023-01-08** | `$7,171.24` | `$7,131.29` | `$29.78` | `$2.50` | `$19.35` | **`$7,151.89`** | 63–77% allocation into high-beta pump |
| **2023-07-09** | `$5,241.54` | `$5,220.18` | `$10.14` | `$3.18` | `$26.40` | **`$5,215.13`** | 63–77% allocation into high-beta pump |
| **2023-12-03** | `$4,683.76` | `$2,299.56` | `$1,951.02` | `$75.51` | `$42.11` | **`$4,641.65`** | 63–77% allocation into high-beta pump |
| **2023-11-05** | `$4,462.48` | `$632.88` | `$3,741.01` | `$22.57` | `$46.65` | **`$4,415.84`** | 63–77% allocation into high-beta pump |

### Diagnostic Counterfactual Matrix (Identical Accounting)
| Strategy / Counterfactual | Net Return | Sharpe | Max Drawdown | Train | Val 2024 | Holdout | 2022 | 2023 | 2024 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **A. Original R11 Joint** | **+498.67%** | `1.002` | `-54.55%` | `+501.26%` | `+64.48%` | `-40.08%` | `+24.12%` | `+388.51%` | `+64.48%` |
| **B. R11 Cash + BTC Sleeve** | **+140.15%** | `0.743` | `-37.01%` | `+80.13%` | `+65.11%` | `-19.88%` | `-17.49%` | `+118.44%` | `+65.11%` |
| **C. R11 Cash + EW Sleeve** | **+83.70%** | `0.515` | `-48.73%` | `+74.12%` | `+58.02%` | `-33.97%` | `-23.19%` | `+127.28%` | `+58.02%` |
| **D. R11 Selection + Fixed 58% Exp** | **+176.99%** | `0.694` | `-50.86%` | `+159.53%` | `+69.74%` | `-37.71%` | `-21.65%` | `+233.60%` | `+69.74%` |
| **E. Static BTC + Fixed 58% Exp** | **+47.24%** | `0.422` | `-45.42%` | `+7.76%` | `+62.35%` | `-16.41%` | `-39.47%` | `+78.11%` | `+62.35%` |

- **Transaction Fee Drag**: At 12.0 bps fee rate, total fees paid were **$13,446.96**. Net return without transaction fees would have been **+657.37%**, yielding an absolute fee drag of **158.70%**.

---

## 5. Phase D: Seed-Specific Economic Diagnostics

| Metric | Seed 42 | Seed 101 (Selected) | Seed 202 | Seed Divergence Mechanism |
| :--- | :---: | :---: | :---: | :--- |
| **Full Horizon Net Return** | `+401.97%` | `+498.68%` | `+11.13%` | 487.5% return spread |
| **Train Return (2022–2023)** | `+389.58%` | `+501.26%` | `-0.94%` | Seed 202 missed SOL pump entirely |
| **Val Return (2024)** | `+59.02%` | `+64.48%` | `+45.64%` | All 3 seeds underperformed Static BTC |
| **Holdout Return (2025–2026)** | `-36.40%` | `-40.08%` | `-23.69%` | All 3 seeds suffered severe drawdowns |
| **Mean Cash Weight** | `50.1%` | `38.5%` | `50.0%` | Cash allocation was nearly identical (~38–50%) |
| **Gross Turnover** | `138.93` | `195.84` | `15.39` | Heavy churn across all seeds |

> [!IMPORTANT]
> **Diagnostic Conclusion on Seed Instability**: The divergence between Seed 101 (+498%) and Seed 202 (+11%) did **not** come from cash exposure timing (both held ~38–50% cash). It came entirely from **random weight initialization aligning by chance with SOLUSDT's explosive 2023 pump**. When a policy's performance is dominated by whether random initialization catches an episodic 10x altcoin pump, the return is **not reproducible algorithmic alpha**.

---

## 6. Synthesis & Strategic Guidance

### Cumulative R8–R11 Empirical Trajectory
| Iteration | Architecture & Objective | Realized Cash | Train Net Ret | Val 2024 Ret | Holdout Ret | Key Empirical Finding |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **R8** | Joint Softmax + Unbounded Loss | 94.6% | +24.4% | +9.6% | +0.2% | Collapsed into cash shelter due to 20.4x downside gradient dominance |
| **R9** | Attribution Analysis of R8 | 94.6% | — | — | — | Proved R8 return was cash capital preservation, not asset-selection alpha |
| **R10** | Joint Softmax + Risk-Budgeted Loss | 12.1% | -14.4% | +94.2% | -44.4% | Cured cash shelter, but held ~88% crypto continuously, failing bear-market defense |
| **R11** | Factorized Heads (Sigmoid + Softmax) | 38.5% | +501.3% | +64.5% | -40.1% | Disentangled heads; massive Train gain driven by 5 weeks of SOL pump; failed out of sample |

### Final Formal Closures
- **`UNIFIED_NEURAL_ALPHA = NOT_ESTABLISHED`**
- **`R11_FACTORISATION = COMPLETED_EXPLORATORY`**
- **`PRODUCTION_PROMOTION = NOT_AUTHORIZED`**

---

## 7. Next Research Question (Proposal Only — No Implementation)

> [!TIP]
> **Research Hypothesis: Predictive Cross-Cycle Information Discovery**:
> *Can exogenous, point-in-time structural market signals (derivatives positioning, exchange liquidity, on-chain flows) provide statistically significant and causal regime-switching information that price/momentum/volatility features fail to convey, enabling a trading policy to systematically de-risk before market-wide drawdowns without in-sample overfitting?*

### Five Required Research Specifications
1. **Novel Information Sources Beyond Price/Volume**:
   - Cross-sectional perpetual funding rate skew (crowded long/short positioning).
   - Aggregate open interest normalized by volume / market cap (leverage buildup).
   - Exchange net stablecoin flows (dry-powder purchasing power vs distribution).
   - Network active address momentum and transaction count growth.
   - Macro liquidity indicators (US Treasury yield spreads, DXY index, central bank liquidity).
2. **Verifiable Point-in-Time Historical Sources**:
   - Binance / Bybit public perpetual archive (hourly funding and open interest).
   - Glassnode / CryptoQuant point-in-time on-chain metrics (strictly causal timestamps).
   - Federal Reserve FRED API for macro liquidity indices.
3. **Multi-Cycle, Survivorship-Bias-Free Universe Design**:
   - Must span at least two full halving cycles (2018–2019 bear, 2020–2021 bull, 2022 bear, 2023–2024 bull).
   - Universe must be defined dynamically per epoch based on point-in-time top market cap, explicitly including historically prominent tokens that later decayed (e.g. LUNA, FTT, EOS, BCH) to eliminate survivorship bias.
4. **Rigorous Falsification Economic Benchmarks**:
   - Volatility-targeted BTC/Cash (R7 Vol Target 25% with 5% buffer).
   - Simple trend-following SMA/EMA filter benchmark.
   - Static 50/50 BTC/Cash.
5. **Mandatory Prerequisites Before Retraining Neural Models**:
   - Feature Rank IC and Mutual Information must achieve statistically significant cross-cycle predictive power ($p < 0.01$, FDR adjusted).
   - A simple linear or rank-based model must demonstrate positive net economic alpha after double-sided spot transaction fees.
   - Seed stability across $\ge 10$ random seeds must show return standard deviation $< 15\%$.

**STOP RULE APPLIED**: R11 research is fully closed. No R12 training or architectural iteration is initiated.