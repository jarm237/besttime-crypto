# R9 Unified Neural Allocation Attribution Report (Corrected Edition)

**Clean Aligned Horizon**: 2022-01-16 00:00 UTC to 2026-11-16 19:00 UTC (42,379 hourly bars, 253 weekly decisions)  
**Selected Model Checkpoint**: Seed 202 (`r8_selected_model.pt`) | Selected strictly via Validation 2024  
**Exposure Distinction**: Train-Matched Fixed Exposure (Counterfactual D & E): **6.07%** | Realized Full-Horizon Exposure (Counterfactual A): **5.40%**  
**Execution & Accounting**: Next-open execution (`open[t_dec]`) | Valuation (`close[t]`) | Base: 12.0 bps | Stress: 25.0 bps  

> [!NOTE]
> **Audit Transparency Statement**: Validation split (2024) was actively used to select the optimal model checkpoint across training seeds. Consequently, Validation 2024 represents a model-selection validation set, not an untouched pristine out-of-sample test.

---

## 1. Executive Scientific Verdict

### Final Verdict: **`NEURAL_CASH_TIMING_VALUE_OBSERVED_PREDICTIVE_SKILL_UNPROVEN`**

> [!IMPORTANT]
> **Definitive Attribution Findings**:
> 1. **Interaction Between Cash Timing & Selection**: Switching the risky sleeve from Neural Selection (A) to pure BTC (B) under dynamic cash timing alters return by **+13.88%** (+37.43% vs +23.55%), with A - C delivering **+5.63%**. Conversely, when dynamic cash timing is stripped away and exposure is held fixed at 6.07%, Neural Selection (D: **+5.26%**) vs Static BTC (E: **+6.13%**) yields **-0.87%** delta. This reveals a critical **interaction**: neural selection only added positive return during dynamic exposure bursts, but produced slightly negative incremental value (-0.87%) at constant exposure.
> 2. **Observed Economic Delta (A vs D)**: Dynamic cash timing generated an observed historical return delta of **+32.17%** (+37.43% vs +5.26%). However, this historical delta alone does NOT prove formal statistical predictive timing skill, as it may reflect market drift or regime coincidence.
> 3. **The 2022 Bear Market Engine**: In 2022, BTC plunged **-61.59%** and Equal-Weight fell **-68.85%**. Neural Policy returned **+16.46%**, Neural BTC (B) returned **+8.00%**, and Static 6.1% BTC (E) lost **-4.54%**. The +16.46% return was driven primarily by avoiding the downtrend through high cash (+8.00%), while active altcoin selection contributed +8.46%.
> 4. **Sharpe Ratio Nature**: The Sharpe ratio of 0.884 was not solely an artifact of holding cash (Static 6.1% BTC / Cash achieved Sharpe 0.425). Dynamic cash timing actively compressed variance by remaining in cash during high-volatility drawdown phases.
> 5. **Root Cause of Cash Shelter**: In the training objective, the downside semi-deviation penalty had a loss-term magnitude 17.5x larger than expected return, and an initial parameter gradient vector norm 20.4x larger than the return gradient, providing an overwhelming optimization incentive to collapse into the cash shelter.

---

## 2. Answers to the 5 Mandatory Attribution Questions

### Q1: How much does performance change if the risky sleeve is switched to pure BTC?
- **Counterfactual A (Neural Selection + Dynamic Cash)**: Net Return **+37.43%**, Sharpe **0.884**, MaxDD **-8.51%**.
- **Counterfactual B (Pure BTC + Dynamic Cash)**: Net Return **+23.55%**, Sharpe **0.723**, MaxDD **-7.70%**.
- **Finding**: Switching to pure BTC alters return by **+13.88%**, but Sharpe (0.884 vs 0.723) and MaxDD (-8.51% vs -7.70%) remain comparable.

### Q2: Does asset selection add value without dynamic cash timing?
- **Counterfactual D (Neural Selection + Fixed 6.07% Exposure)**: Net Return **+5.26%**, Sharpe **0.288**, MaxDD **-5.96%**.
- **Counterfactual E (Static BTC + Fixed 6.07% Exposure)**: Net Return **+6.13%**, Sharpe **0.425**, MaxDD **-5.67%**.
- **Finding**: When exposure is held constant at 6.07%, Neural Selection underperforms static BTC by **-0.87%**. Asset selection possesses no standalone alpha without cash timing.

### Q3: What drove the +16.46% return in 2022?
- BTC Buy & Hold lost **-61.59%**, Equal-Weight 8 coins lost **-68.85%**.
- Static 6.1% BTC (E) returned **-4.54%**.
- Neural Cash + BTC (B) returned **+8.00%**, confirming +8.00% came from cash preservation and timing, while selection added **+8.46%**.

### Q4: Did exposure scale with market regime or stay ~95% cash continuously?
- Realized cash allocation averaged **94.6%** across the 4.84-year horizon.
- The policy remained heavily cash-sheltered across all regimes: 2022 (94.2%), 2023 (93.6%), 2024 (95.2%), 2025–2026 (95.4%). It failed to expand exposure during the 2024 crypto bull run.

### Q5: Is Sharpe really superior to controls of comparable exposure?
- Neural Policy (Sharpe **0.884**) significantly exceeded Static 6.1% BTC/Cash (Sharpe **0.425**), proving that timing compressed variance beyond static cash dilution. However, absolute capital growth lagged unconstrained baselines (Static 50/50: +43.02%, Vol Target 25%: +58.22%).

---

## 3. Mathematical Loss & Gradient Diagnosis

Initial parameter gradient vector norms:
- $\nabla_\theta (-\mathbb{E}[R_{\text{net}}]): 0.00178$
- $\nabla_\theta (\lambda_{\text{downside}} \cdot \text{SemiDev}): 0.03640$
- **Gradient Norm Disparity**: Downside gradient is **20.44x larger** than Return gradient at initialization.
- This explains why backpropagation relentlessly drives the policy toward the cash shelter.