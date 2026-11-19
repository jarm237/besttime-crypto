# Scientific & Economic Verdict — Learned Policy v1 (Corrected)

## 1. Executive Verdict
**ECONOMIC_VERDICT:** `LEARNED_POLICY_PROFITABLE_NOT_INCREMENTAL`  
**TRACK_A_V1_COMPARISON:** `WORSE`  
**STATIC_50_50_COMPARISON:** `MIXED`  
**REBALANCED_50_50_COMPARISON:** `WORSE`  
**NEXT_EXPERIMENT:** `NONE_NEGATIVE_NEURAL_EXPERIMENT_STOP`

---

## 2. Addressing the Three Core Research Questions

### Question 1: Does Learned Policy v1 achieve positive net trading profit?
- **Validation (2024):** Net CAGR is **+51.54%** (PnL: $+5,166.18).
- **Full Period (2022–2026):** Net CAGR is **+6.58%** (PnL: $+3,646.59).
- **Finding:** YES. The policy achieves positive net capital growth after all-in 30 bps execution costs.

### Question 2: Does it outperform the frozen Track A v1 Donchian benchmark?
- **Validation (2024):** Learned Policy (+51.54%) vs Track A v1 (+78.05%) → Excess: **-26.51%**.
- **Reused Test (2025–2026):** Learned Policy (-8.08%) vs Track A v1 (-19.49%) → Excess: **+11.41%**.
- **Full Period (2022–2026):** Learned Policy (+6.58%) vs Track A v1 (+9.28%) → Excess: **-2.70%**.
- **Finding:** NO. Across the full 4.8-year diagnostic horizon, Track A v1 generated higher net CAGR (+9.28% vs +6.46%) and greater net dollar wealth ($+5,419.98 vs $+3,646.59).

### Question 3: Does it outperform a naive / periodic 50/50 BTC/Cash allocation?
- **Validation (2024):**
  - Learned Policy: Net CAGR **+51.54%**, MaxDD **-17.36%**, Calmar **2.97**
  - BTC 50/50 Static: Net CAGR **+59.77%**, MaxDD **-20.48%**, Calmar **2.92**
  - BTC 50/50 Rebalanced: Net CAGR **+54.78%**, MaxDD **-15.86%**, Calmar **3.45**
- **Reused Test (2025–2026):**
  - Learned Policy: Net CAGR **-8.08%**, MaxDD **-29.77%**, Calmar **-0.27**
  - BTC 50/50 Static: Net CAGR **-9.27%**, MaxDD **-30.72%**, Calmar **-0.30**
  - BTC 50/50 Rebalanced: Net CAGR **-8.12%**, MaxDD **-30.74%**, Calmar **-0.26**
- **Full Period (2022–2026):**
  - Learned Policy: Net CAGR **+6.58%**, MaxDD **-39.38%**, Calmar **0.17**
  - BTC 50/50 Static: Net CAGR **+3.34%**, MaxDD **-39.22%**, Calmar **0.09**
  - BTC 50/50 Rebalanced: Net CAGR **+6.59%**, MaxDD **-41.04%**, Calmar **0.16**
- **Finding:**
  The learned policy's average BTC exposure is approximately 49% across all windows. Its returns and drawdown characteristics closely track a passive 50/50 BTC/Cash portfolio. While it curtails max drawdown relative to full BTC exposure, this is primarily an artifact of reduced beta rather than dynamic regime-aware alpha.

---

## 3. Scientific Synthesis & Negative Experiment Verdict
1. **No Evidence of Regime-Aware Alpha:**
   The neural network primarily learned to sit near a ~50% cash allocation. It does not consistently outperform a simple, static or rebalanced 50/50 allocation rule after accounting for transaction fees.
2. **Defeat by Simple Heuristics:**
   The frozen Track A v1 multi-horizon Donchian strategy achieves superior net compounding and total dollar profits without neural complexity.
3. **Formal Termination of Neural Branch:**
   In accordance with the pre-registration principles and research directives, we do NOT open Neural v2, hyperparameter search, or model sweeps. The results stand as an empirical negative neural experiment.
