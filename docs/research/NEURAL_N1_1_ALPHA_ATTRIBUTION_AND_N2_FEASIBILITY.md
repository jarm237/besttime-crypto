# N1.1 — Cross-Sectional Alpha Attribution & Neural Risk-Budget Feasibility

- **Date**: 2026-11-11
- **Status**: `COMPLETED`
- **Authoritative Predecessor Report**: [`docs/research/NEURAL_N1_INFORMATION_AND_ECONOMIC_PILOT.md`](NEURAL_N1_INFORMATION_AND_ECONOMIC_PILOT.md)
- **Research Package**: [`neural_trading/n1/`](../../neural_trading/n1/__init__.py) ([`attribution.py`](../../neural_trading/n1/attribution.py), [`experiment.py`](../../neural_trading/n1/experiment.py), [`model.py`](../../neural_trading/n1/model.py))
- **Audit Script & Machine-Readable Output**:
  - [`scripts/n1_1_alpha_attribution_and_n2_feasibility.py`](../../scripts/n1_1_alpha_attribution_and_n2_feasibility.py)
  - [`research/neural_n1/n1_1_alpha_attribution_and_n2_feasibility.json`](../../research/neural_n1/n1_1_alpha_attribution_and_n2_feasibility.json)
- **Final Dispositions**:
  - `N1_ECONOMIC_DISPOSITION = REJECTED_FOR_PRODUCTION_CANDIDACY`
  - `N2_EXPERIMENT_READINESS = N2_NOT_AUTHORIZED_FROM_CURRENT_EVIDENCE`
  - `PROSPECTIVE_COLLECTOR = STOPPED`
  - `REAL_TRADING = DISABLED`

---

## 1. Executive Summary

This audit resolves the portfolio accounting and benchmark attribution questions from **N1** (`CrossSectionalMarketPolicy`) and determines whether N1 truly extracts post-cost economic value from cross-sectional H1/H2 market information or merely reflects market beta and benchmark-rebalancing mechanics:

1. **Phase A — Portfolio Economic Identity & Return Reconciliation**:
   - The apparent discrepancy in N1 between **Direct Portfolio Net PnL Difference** (`Neural Net PnL - Exposure-Matched Passive Net PnL`: `-$300.72` / `-1.50%` in 2022, `+$5,635.63` / `+28.18%` in 2024, `+$536.56` / `+2.68%` in 2025) and **Reported Net Excess** (`+2.35%` in 2022, `+10.35%` in 2024, `-2.82%` in 2025) came from two distinct accounting conventions:
     1. **Benchmark Identity Difference**: The table row `Exposure-Matched Passive` is a **Buy-and-Hold** portfolio initialized at $t=0$ with cash weight $c_0 = \bar{c}_{\text{neural}}$, whereas `net_excess_vs_matched_pct` inside [`simulate_step_policy`](../../neural_trading/n1/experiment.py#L247-L290) was computed against a **synthetic 12h step-rebalanced Constant-Exposure Equal-Weight index** (`synth_gross_step[t] = E_p_bar * ew_mkt_rets[t]`).
     2. **Uncompounded Step-Sum vs Geometrically Compounded Terminal Return**: `net_excess_vs_matched_pct` summed uncompounded 12h step differences $\sum_t (r_{p,t}^{\text{net}} - r_{\text{synth},t}^{\text{net}})$. Using **Carino (1999) geometric linking** ([`_carino_weights`](../../neural_trading/n1/attribution.py#L96-L115)), all five step-level difference components (`Mean Exposure Gap`, `Dynamic Timing vs B&H Drift`, `Neural Cross-Sectional Selection vs EW`, `Avoided B&H Cross-Sectional Drift vs EW`, and `Net Cost Drag Diff`) sum **identically (`0.00%` residual, max step error $1.04 \times 10^{-17}$)** to the exact compounded terminal return difference $\Delta R_{\text{terminal}}^{\text{net}} = \Delta \text{Net PnL}_{\text{USD}} / \$20,000$.
2. **Phase B — Research Independence & Data Eligibility**:
   - Because Phase D feature and horizon (`12h`) selection inspected `2018-01-01 .. 2024-12-31`, **`Fold1_2022_Bear` (`2022`) and `Fold2_2024_Expansion_BookDepth` (`2024`) are strictly `ADAPTIVE_DEVELOPMENT_VALIDATION`**, not independent confirmatory OOS.
   - **`Fold3_2025_Adaptive_Comparison` (`2025`)** lies outside the Phase D `2018–2024` discovery sample, but is classified as **`SEMI_ADAPTIVE_HOLDOUT_COMPARISON`** because the 2025 calendar year was previously evaluated in N0–N0.3 architectural iterations.
3. **Phase C — Real H1 & H2 Information Utility**:
   - Although `H1_trade_size_z168h` had the highest statistical spread in Phase D (`+12.21 bps` at 12h), a standalone long-only tilt on `H1_trade_size_z168h` requires **`161.0x–180.4x` annualized turnover**, burning `$2,560–$6,052` in execution costs. Consequently, the cost-aware neural policy learned to **almost completely ignore `H1_trade_size_z168h`** (weight-tilt correlation `+0.004` to `+0.039`; dropping it in retrained ablations slightly *improves* net PnL in all 3 folds).
   - Instead, N1's cross-sectional tilts are driven primarily by **12h–72h price momentum (`r72h` corr `+0.235 to +0.247`, `H1_xs_rel_ret_24h` corr `+0.133 to +0.140`)** plus low-volatility conditioning (`H1_parkinson_vol_24h` corr `-0.017 to -0.145`). Dropping all 7 non-return H1 flow/size/volatility features (`drop_all_H1_flow_size_vol`) in bounded retrained ablations changes net return by `+2.11%` (2022), `-0.79%` (2024), and `+0.72%` (2025), proving that the newly engineered spot flow/trade-size features add **no consistent incremental economic value** beyond cross-sectional price returns.
4. **Phase D & Phase E — Cross-Sectional Selection vs Market Beta & N2 Feasibility Verdict**:
   - Removing total exposure level (`unit_exposure_cross_sectional_selection`), N1's within-risky asset selection spread vs active Equal-Weight is **`+0.11%` in 2022 (`Prob > 0 = 50.2%`), `+13.89%` in 2024 (`Prob > 0 = 87.0%`, 95% CI `[-4.27%, +23.47%]`), and `-1.44%` in the 2025 post-discovery holdout (`Prob > 0 = 10.0%`)**, where N1 underperforms a simple `Costed Step-Rebalanced EW` benchmark by **`-$219.35` (`-1.09%`)**.
   - Furthermore, testing a causal PIT risk-budget overlay conditioned on trailing volatility, drawdown, market breadth, and 72h trend (`causal_pit_risk_budget_overlay_test`) yields **strictly negative dynamic timing value in all three folds (`-5.55%` in 2022, `-9.16%` in 2024, `-18.89%` in 2025)**.
   - Because neither stable post-discovery cross-sectional selection nor a valid PIT risk-budgeting timing mechanism is supported by current evidence, **`N2_NOT_AUTHORIZED_FROM_CURRENT_EVIDENCE`**.

---

## 2. Phase A — Portfolio Economic Identity & Brinson Reconciliation

### 2.1 `N1_PORTFOLIO_RETURN_RECONCILIATION` (`$20,000.00` Initial Capital, `14 bps RT` / `7 bps per leg`)

In [`scripts/n1_run_phase_f_economic_pilot.py`](../../scripts/n1_run_phase_f_economic_pilot.py#L187-L198), `torch.manual_seed(42)` was called inside `train_n1_policy` rather than prior to `CrossSectionalMarketPolicy.__init__` on iteration 0 (`Fold 1`), whereas `Fold 2` and `Fold 3` inherited the deterministic post-`train_n1_policy(seed=42)` RNG state. To preserve N1 historical results intact without ambiguity, we assign distinct canonical run identities:
- **`N1_FOLD1_2022_ORIGINAL_REPORT_RUN`**: The historical N1 Fold 1 run preserved in [`research/neural_n1/n1_phase_f_economic_pilot_results.json`](../../research/neural_n1/n1_phase_f_economic_pilot_results.json) (`Neural Net = -$11,934.81 / -59.67%`, `Exposure-Matched B&H Net = -$11,634.09 / -58.17%`, `Direct Delta = -$300.72 / -1.50%`).
- **`N1_1_FOLD1_2022_AUDIT_TRACE_RUN`**: The N1.1 diagnostic trace preserved in [`research/neural_n1/n1_1_alpha_attribution_and_n2_feasibility.json`](../../research/neural_n1/n1_1_alpha_attribution_and_n2_feasibility.json) (`Neural Net = -$12,160.77 / -60.80%`, `Exposure-Matched B&H Net = -$11,792.59 / -58.96%`, `Direct Delta = -$368.18 / -1.84%`).
- **`N1_FOLD2_2024_CANONICAL_RUN`** (`Neural Net = +$22,353.70 / +111.77%`, `Exposure-Matched B&H Net = +$16,718.07 / +83.59%`, `Direct Delta = +$5,635.63 / +28.18%`) and **`N1_FOLD3_2025_CANONICAL_RUN`** (`Neural Net = -$4,988.51 / -24.94%`, `Exposure-Matched B&H Net = -$5,525.07 / -27.63%`, `Direct Delta = +$536.56 / +2.68%`), which are byte-for-byte identical (`$0.00` difference) across both runs.

Table `N1_PORTFOLIO_RETURN_RECONCILIATION` reconciles these canonical runs against all four benchmark definitions:

1. **`Exposure-Matched Buy-and-Hold (Initial Cash = Neural Mean Cash)`**: The table row reported in N1 (`build_passive_weights(active_mask, cash_weight=target_cash)`), which buys and holds from $t=0$.
2. **`Time-Average Exposure-Matched Buy-and-Hold (Bisection-Calibrated)`**: Buy-and-hold portfolio whose initial cash weight $c_0^*$ is solved via bisection so that its **realized time-average risky exposure** $\frac{1}{K}\sum_t E_t^{\text{BH}}$ matches $\bar{E}_{\text{neural}}$ to within `0.01%`.
3. **`Costed Step-Rebalanced Equal-Weight`**: Rebalances to $\bar{E}_{\text{neural}}$ total risky exposure and equal active weights $\frac{\bar{E}_{\text{neural}}}{|U_t|}$ every 12h step, paying `7 bps/leg` execution costs.
4. **`Passive Diversified (Active EW, 5% Initial Cash)`**: Buy-and-hold active equal-weight portfolio initialized with `5.0%` cash.

```text
N1_PORTFOLIO_RETURN_RECONCILIATION
```

| Canonical Run ID / Fold | Portfolio / Benchmark | Start Equity (USD) | End Equity (USD) | Gross PnL (USD) | Net PnL (USD) | Gross Return (%) | Net Return (%) | Realized Avg Risk Exp (%) | **Direct Net PnL Diff vs Benchmark (USD)** | **Direct Terminal Net Return Diff (%)** |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **`N1_FOLD1_2022_ORIGINAL_REPORT_RUN`** | **`Unified Neural Policy (N1)`** | $20,000.00 | $8,065.19 | -$11,913.72 | **-$11,934.81** | -59.57% | **-59.67%** | **89.49%** | — | — |
| `N1_FOLD1_2022_ORIGINAL_REPORT_RUN` | `Exposure-Matched B&H (10.51% Init Cash)` | $20,000.00 | $8,365.91 | -$11,628.84 | **-$11,634.09** | -58.14% | **-58.17%** | **81.71%** *(drifted)* | **-$300.72** | **-1.50%** |
| `N1_FOLD1_2022_ORIGINAL_REPORT_RUN` | `Passive Diversified B&H (5.00% Init Cash)` | $20,000.00 | $7,654.49 | -$12,340.42 | **-$12,345.51** | -61.70% | **-61.73%** | 90.77% | **+$410.70** | **+2.06%** |
| **`N1_1_FOLD1_2022_AUDIT_TRACE_RUN`** | **`Unified Neural Policy (N1)`** | $20,000.00 | $7,839.23 | -$12,153.50 | **-$12,160.77** | -60.77% | **-60.80%** | **90.71%** | — | — |
| `N1_1_FOLD1_2022_AUDIT_TRACE_RUN` | `Exposure-Matched B&H (9.29% Init Cash)` | $20,000.00 | $8,207.41 | -$11,787.38 | **-$11,792.59** | -58.94% | **-58.96%** | **83.65%** *(drifted)* | **-$368.18** | **-1.84%** |
| `N1_1_FOLD1_2022_AUDIT_TRACE_RUN` | `Time-Avg Calibrated B&H (5.07% Init Cash)` | $20,000.00 | $7,659.34 | -$12,335.56 | **-$12,340.66** | -61.68% | **-61.70%** | **90.70%** *(matched)* | **+$179.89** | **+0.90%** |
| `N1_1_FOLD1_2022_AUDIT_TRACE_RUN` | `Costed Step-Rebalanced EW (90.71% Exp)` | $20,000.00 | $7,762.26 | -$12,162.51 | **-$12,237.74** | -60.81% | **-61.19%** | **90.71%** *(matched)* | **+$76.97** | **+0.39%** |
| **`N1_FOLD2_2024_CANONICAL_RUN`** | **`Unified Neural Policy (N1)`** | $20,000.00 | $42,353.70 | +$22,400.16 | **+$22,353.70** | +112.00% | **+111.77%** | **91.64%** | — | — |
| `N1_FOLD2_2024_CANONICAL_RUN` | `Exposure-Matched B&H (8.36% Init Cash)` | $20,000.00 | $36,718.07 | +$16,742.08 | **+$16,718.07** | +83.71% | **+83.59%** | **92.64%** *(drifted)* | **+$5,635.63** | **+28.18%** |
| `N1_FOLD2_2024_CANONICAL_RUN` | `Time-Avg Calibrated B&H (9.59% Init Cash)` | $20,000.00 | $36,490.96 | +$16,514.65 | **+$16,490.96** | +82.57% | **+82.45%** | **91.63%** *(matched)* | **+$5,862.74** | **+29.32%** |
| `N1_FOLD2_2024_CANONICAL_RUN` | `Costed Step-Rebalanced EW (91.64% Exp)` | $20,000.00 | $38,246.25 | +$18,403.85 | **+$18,246.25** | +92.02% | **+91.23%** | **91.64%** *(matched)* | **+$4,107.45** | **+20.54%** |
| `N1_FOLD2_2024_CANONICAL_RUN` | `Passive Diversified B&H (5.00% Init Cash)` | $20,000.00 | $37,044.82 | +$17,070.47 | **+$17,044.82** | +85.35% | **+85.22%** | 93.96% | **+$5,308.88** | **+26.55%** |
| **`N1_FOLD3_2025_CANONICAL_RUN`** | **`Unified Neural Policy (N1)`** | $20,000.00 | $15,011.49 | -$4,975.50 | **-$4,988.51** | -24.88% | **-24.94%** | **87.44%** | — | — |
| `N1_FOLD3_2025_CANONICAL_RUN` | `Exposure-Matched B&H (12.56% Init Cash)` | $20,000.00 | $14,474.93 | -$5,514.00 | **-$5,525.07** | -27.57% | **-27.63%** | **86.70%** *(drifted)* | **+$536.56** | **+2.68%** |
| `N1_FOLD3_2025_CANONICAL_RUN` | `Time-Avg Calibrated B&H (11.85% Init Cash)` | $20,000.00 | $14,433.69 | -$5,555.12 | **-$5,566.31** | -27.78% | **-27.83%** | **87.44%** *(matched)* | **+$577.80** | **+2.89%** |
| `N1_FOLD3_2025_CANONICAL_RUN` | `Costed Step-Rebalanced EW (87.44% Exp)` | $20,000.00 | $15,230.84 | -$4,667.99 | **-$4,769.16** | -23.34% | **-23.85%** | **87.44%** *(matched)* | **-$219.35** | **-1.09%** |
| `N1_FOLD3_2025_CANONICAL_RUN` | `Passive Diversified B&H (5.00% Init Cash)` | $20,000.00 | $14,150.94 | -$5,837.15 | **-$5,849.06** | -29.19% | **-29.25%** | 93.69% | **+$860.55** | **+4.31%** |

### 2.2 `N1_BRINSON_ATTRIBUTION_DEFINITION` — Exact Reconciliation of Arithmetic Step-Sum vs Carino Geometric Terminal Return

To prevent any conflation between single-step arithmetic Brinson sums and actual terminal dollar PnL differences, N1.1 separates and defines two distinct attribution conventions:

1. **`Brinson Arithmetic Step-Sum vs Synthetic Constant-Exposure EW` (`reported_net_excess_step_sum_pct` in N1)**:
   - Sums single-step uncompounded return differences $\sum_{t=0}^{K-1}(r_{p,t}^{\text{net}} - r_{\text{synth},t}^{\text{net}})$ against a synthetic benchmark that rebalances to equal active weights $\frac{\bar{E}_p}{|U_t|}$ at every 12h step (`timing_step_sum + selection_step_sum + cost_diff_step_sum`).
   - Because it is an uncompounded arithmetic sum against a **step-rebalanced** benchmark, it excludes geometric compounding interaction and excludes Buy-and-Hold weight/exposure drift.
2. **`Carino Geometrically-Linked Multi-Period Attribution vs Exposure-Matched Buy-and-Hold`**:
   - At each step $t$, the exact single-step net return difference $r_{p,t}^{\text{net}} - r_{m,t}^{\text{net}}$ between `Unified Neural Policy (N1)` and `Exposure-Matched Buy-and-Hold` decomposes identically (`max_abs_err = 1.04e-17`) into five terms:
     $$\begin{aligned}
     r_{p,t}^{\text{net}} - r_{m,t}^{\text{net}} &\equiv \underbrace{(\bar{E}_p - \bar{E}_m) R_{m,t}}_{\text{C1: Mean Exposure Gap}} + \underbrace{\big[(E_{p,t} - \bar{E}_p) - (E_{m,t} - \bar{E}_m)\big] R_{m,t}}_{\text{C2: Dynamic Timing vs B\&H Exposure Drift}} \\
     &\quad + \underbrace{(r_{p,t}^{\text{gross}} - E_{p,t} R_{m,t})}_{\text{C3: Neural XS Selection vs EW}} - \underbrace{(r_{m,t}^{\text{gross}} - E_{m,t} R_{m,t})}_{\text{C4: B\&H XS Drift vs EW}} + \underbrace{\big[(r_{p,t}^{\text{net}} - r_{p,t}^{\text{gross}}) - (r_{m,t}^{\text{net}} - r_{m,t}^{\text{gross}})\big]}_{\text{C5: Net Cost Drag Diff}}
     \end{aligned}$$
   - Multiplying by the Carino (1999) geometric linking weights $k_t = \frac{\ln(1+r_{p,t}^{\text{net}}) - \ln(1+r_{m,t}^{\text{net}})}{r_{p,t}^{\text{net}} - r_{m,t}^{\text{net}}} \Big/ \frac{\ln(1+R_p^{\text{net}}) - \ln(1+R_m^{\text{net}})}{R_p^{\text{net}} - R_m^{\text{net}}}$ links these five components so their sum equals **`100.00%` of the Direct Terminal Net Return Difference** $\Delta R_{\text{terminal}}^{\text{net}} = R_p^{\text{net}} - R_m^{\text{net}} = \Delta \text{Net PnL}_{\text{USD}} / \$20,000$.

```text
N1_BRINSON_ATTRIBUTION_DEFINITION
```

| Attribution Component / Metric | Fold 1 (`2022` N1 Report) | Fold 1 (`2022` Audit Trace) | Fold 2 (`2024` Expansion) | Fold 3 (`2025` Holdout) | Economic Meaning |
| --- | ---: | ---: | ---: | ---: | --- |
| **A. Uncompounded Arithmetic Step-Sum vs 12h Rebalanced EW** | | | | | |
| `Timing Step-Sum vs E_bar * EW (%)` | +1.04% | +0.08% | +3.33% | -0.34% | $\sum_t (E_{p,t} - \bar{E}_p) R_{m,t}$ |
| `Selection Step-Sum vs E_t * EW (%)` | +1.50% | -0.03% | +7.07% | -2.45% | $\sum_t (r_{p,t}^{\text{gross}} - E_{p,t} R_{m,t})$ |
| `Cost Drag Diff Step-Sum (%)` | -0.19% | -0.03% | -0.05% | -0.03% | $\sum_t (\Delta c_{p,t} - \Delta c_{\text{synth},t})$ |
| **`Reported Arithmetic Step-Sum Excess (%)`** | **+2.35%** | **+0.02%** | **+10.35%** | **-2.82%** | Uncompounded step sum vs 12h Rebalanced EW |
| **B. Exact Carino Geometric Attribution vs Exposure-Matched B&H** | | | | | |
| `C1: Mean Exposure Gap (E_p_bar - E_m_bar) (%)` | -3.89% | -3.60% | -1.09% | -0.27% | In 2022 crash, B&H drifted down to `81.7–83.7%` exp vs Neural `89.5–90.7%` |
| `C2: Dynamic Timing vs B&H Exposure Drift (%)` | +1.98% | +2.10% | +6.87% | +1.85% | Step exposure timing difference relative to B&H exposure drift |
| `C3: Neural Cross-Sectional Selection vs EW (%)` | +0.92% | +0.08% | **+12.25%** | **-1.46%** | True compounded cross-sectional selection of Neural vs 12h EW |
| `C4: Minus B&H Cross-Sectional Drift vs EW (%)` | -0.40% | -0.41% | **+10.24%** | **+2.57%** | Rebalancing advantage over B&H weight drift (explains 2025 sign flip!) |
| `C5: Net Transaction Cost Drag Diff (%)` | -0.11% | -0.01% | -0.09% | -0.01% | Incremental transaction cost drag of Neural vs Matched B&H |
| **`Carino Sum = Direct Terminal Net Return Diff (%)`** | **-1.50%** | **-1.84%** | **+28.18%** | **+2.68%** | **Identical to `(Neural Net PnL - Matched B&H Net PnL) / $20,000`** |
| **`Direct Portfolio Net PnL Difference (USD)`** | **-$300.72** | **-$368.18** | **+$5,635.63** | **+$536.56** | **Exact dollar PnL advantage over Exposure-Matched B&H** |
| **`Direct Net PnL Diff vs Costed Rebalanced EW (USD)`** | **+$189.19** | **+$76.97** | **+$4,107.45** | **-$219.35** | **Exact dollar PnL advantage over Costed 12h Step-Rebalanced EW** |

---

## 3. Phase B — Walk-Forward Research Independence & Data Eligibility

```text
N1_WALK_FORWARD_RESEARCH_INDEPENDENCE
```

| Fold | Train Window (UTC) | Eval Window (UTC) | Purge Gap | Phase D (`2018–2024`) Overlap | Epistemic Status | Active Symbols (Train $\to$ Eval) | `EOSUSDT` Eval Status | `H2 bookDepth` Active Frac (Train $\to$ Eval) |
| --- | --- | --- | :---: | :---: | --- | :---: | --- | :---: |
| **`Fold1_2022_Bear`** | `2018-06-01 .. 2021-12-30` (`2,618` steps) | `2022-01-03 .. 2022-12-30` (`724` steps) | `84.0h` | **YES (`S3_2022`)** | **`ADAPTIVE_DEVELOPMENT_VALIDATION`** *(Not Confirmatory OOS)* | `0..13` $\to$ `13` (`SOL` 993 tr steps, `DOGE` 1793 tr steps) | Active all `724` steps | `0.00%` $\to$ `0.00%` *(All H2 cols zero-masked)* |
| **`Fold2_2024_Expansion`** | `2018-06-01 .. 2023-12-30` (`4,078` steps) | `2024-01-03 .. 2024-12-30` (`726` steps) | `84.0h` | **YES (`S4_2023_2024` & `H2_2024`)** | **`ADAPTIVE_DEVELOPMENT_VALIDATION`** *(Not Confirmatory OOS)* | `0..13` $\to$ `13` (`SOL` 2453 tr steps, `DOGE` 3253 tr steps) | Active all `726` steps | `17.46%` (`2023`) $\to$ `99.45%` (`2024`) |
| **`Fold3_2025_Adaptive`** | `2018-06-01 .. 2024-12-30` (`4,810` steps) | `2025-01-03 .. 2025-12-30` (`724` steps) | `84.0h` | **NO** *(Post-Phase D)* | **`SEMI_ADAPTIVE_HOLDOUT_COMPARISON`** *(Post-N0..N0.3 2025 iterations)* | `0..13` $\to$ `12..13` | Active `286` steps (`Jan–May 25`), Delisted `438` steps (`max_w = 0.0`) | `29.94%` (`2023–24`) $\to$ `100.00%` (`2025`) |

---

## 4. Phase C — Real H1 & H2 Information Utility & Bounded Ablations

### 4.1 `N1_H1_INFORMATION_UTILITY`

Table `N1_H1_INFORMATION_UTILITY` compares all six required dimensions (`cross_sectional_predictive_spread`, `beta_adjusted_signal`, `long_only_implementable_payoff`, `turnover_required`, `realized_execution_cost`, and `incremental_portfolio_value` under both frozen zero-masking and bounded retraining with identical seed `42`, `18` epochs, and simulator) across the priority H1 features (`H1_trade_size_z168h`, `H1_xs_rel_ret_24h`, `H1_xs_rel_imb_24h`, `H1_parkinson_vol_24h`, and `r72h`).
- **Explicit Ablation Baseline Identity**: Every `Frozen Mask Marginal Net PnL` and `Bounded Retrained Incremental Net PnL` is defined as $\text{Base Net PnL} - \text{Ablated Net PnL}$ relative to the deterministic audit baseline of that fold:
  - `2022` Baseline = `N1_1_FOLD1_2022_AUDIT_TRACE_RUN` (`Net PnL = -$12,160.77`, `Net Return = -60.80%`, `Selection Step-Sum = -0.03%`).
  - `2024` Baseline = `N1_FOLD2_2024_CANONICAL_RUN` (`Net PnL = +$22,353.70`, `Net Return = +111.77%`, `Selection Step-Sum = +7.07%`).
  - `2025` Baseline = `N1_FOLD3_2025_CANONICAL_RUN` (`Net PnL = -$4,988.51`, `Net Return = -24.94%`, `Selection Step-Sum = -2.45%`).
  A positive value means the feature contributed positively to the baseline; a negative value means the ablated model (without that feature) outperformed the baseline.

```text
N1_H1_INFORMATION_UTILITY
```

| Feature / Group | Fold | XS Predictive Spread (bps/12h) | Beta-Adj Log Signal (bps/12h) | Mean XS Rank IC | Neural Weight Tilt Corr | Standalone Long-Only Gross / Net Ret (%) | Turnover Required (Ann.) | Realized Tx Cost (USD) | Frozen Mask Marginal Net PnL (USD / %) | **Bounded Retrained Incremental Net PnL (USD / %)** |
| --- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **`H1_trade_size_z168h`** *(Priority 1)* | `2022` | +2.73 | +1.89 | -0.0008 | **+0.0193** | -53.40% / -62.74% | **161.01x** | **$2,560.19** | -$4.23 (-0.02%) | **-$82.80 (-0.41%)** |
| **`H1_trade_size_z168h`** *(Priority 1)* | `2024` | +7.85 | +7.62 | +0.0228 | **+0.0387** | +139.68% / +86.43% | **180.43x** | **$6,052.38** | +$81.13 (+0.41%) | **-$316.78 (-1.58%)** |
| **`H1_trade_size_z168h`** *(Priority 1)* | `2025` | -5.69 | -7.01 | -0.0178 | **+0.0038** | -25.25% / -40.45% | **163.67x** | **$3,809.79** | -$51.37 (-0.25%) | **-$110.43 (-0.55%)** |
| **`H1_xs_rel_ret_24h`** *(Priority 2)* | `2022` | +19.46 | +18.02 | -0.0032 | **+0.1326** | -50.27% / -56.56% | 97.31x | $1,670.94 | -$208.49 (-1.04%) | **-$152.80 (-0.76%)** |
| **`H1_xs_rel_ret_24h`** *(Priority 2)* | `2024` | +12.33 | +10.45 | +0.0093 | **+0.1402** | +129.99% / +96.46% | 113.15x | $4,070.88 | +$1,951.85 (+9.76%) | **+$1,848.27 (+9.24%)** |
| **`H1_xs_rel_ret_24h`** *(Priority 2)* | `2025` | -9.21 | -9.59 | -0.0375 | **+0.1363** | -30.14% / -39.26% | 100.73x | $2,317.59 | +$676.85 (+3.39%) | **+$709.44 (+3.55%)** |
| `H1_xs_rel_imb_24h` | `2022` | -1.41 | -0.98 | +0.0053 | +0.0871 | -60.53% / -64.95% | 85.61x | $1,304.55 | +$12.77 (+0.07%) | +$76.15 (+0.38%) |
| `H1_xs_rel_imb_24h` | `2024` | +3.01 | +2.13 | +0.0204 | +0.1247 | +95.57% / +63.02% | 130.70x | $4,024.80 | +$1,868.28 (+9.34%) | +$1,712.25 (+8.56%) |
| `H1_xs_rel_imb_24h` | `2025` | +0.54 | +0.67 | +0.0122 | +0.0105 | -26.15% / -39.45% | 143.07x | $3,212.01 | +$127.61 (+0.64%) | -$30.70 (-0.15%) |
| `H1_parkinson_vol_24h` | `2022` | +2.09 | -4.66 | -0.0219 | -0.0173 | -62.21% / -62.74% | 10.06x | $170.49 | +$18.25 (+0.10%) | -$129.89 (-0.65%) |
| `H1_parkinson_vol_24h` | `2024` | +4.16 | -1.92 | -0.0447 | -0.0611 | +116.23% / +112.26% | 13.31x | $563.43 | +$818.92 (+4.10%) | -$120.47 (-0.60%) |
| `H1_parkinson_vol_24h` | `2025` | -8.22 | -13.87 | -0.0615 | -0.1447 | -25.65% / -26.54% | 8.73x | $223.30 | +$968.30 (+4.84%) | +$654.23 (+3.27%) |
| `r72h` *(3-Day Momentum)* | `2022` | +19.80 | +18.45 | +0.0071 | **+0.2313** | -51.10% / -53.13% | 30.49x | $543.86 | — | — |
| `r72h` *(3-Day Momentum)* | `2024` | +19.62 | +17.12 | +0.0190 | **+0.2469** | +166.69% / +153.44% | 36.61x | $1,594.76 | — | — |
| `r72h` *(3-Day Momentum)* | `2025` | -8.75 | -9.70 | -0.0458 | **+0.2350** | -30.23% / -33.05% | 29.72x | $719.24 | — | — |
| **`All 7 Non-Return H1 Features Combined`** (`drop_all_H1_flow_size_vol`) | `2022` | — | — | — | — | — | — | — | -$28.99 (-0.14%) | **-$423.41 (-2.11%)** *(Return-only beats Full N1)* |
| **`All 7 Non-Return H1 Features Combined`** (`drop_all_H1_flow_size_vol`) | `2024` | — | — | — | — | — | — | — | +$553.73 (+2.77%) | **+$157.27 (+0.79%)** *(Return-only gets +110.98%)* |
| **`All 7 Non-Return H1 Features Combined`** (`drop_all_H1_flow_size_vol`) | `2025` | — | — | — | — | — | — | — | -$6.52 (-0.03%) | **-$144.74 (-0.72%)** *(Return-only beats Full N1)* |

### 4.2Why Predictive Correlation (`H1_trade_size_z168h`) Did Not Translate Into Neural Portfolio Value

1. **The Turnover Barrier**: `H1_trade_size_z168h` measures 12h/24h spikes in average trade size relative to a 168h baseline. While statistically predictive of next-12h returns in 2018–2024 (`+7.62 bps` beta-adjusted spread in 2024), asset rankings flip rapidly from step to step (`161x–180x` annualized turnover in a long-only tilt, costing `$2,560–$6,052`). Furthermore, in 2025 out-of-sample, its predictive spread inverted to **`-7.01 bps/step`** (`IC = -0.0178`).
2. **Neural Policy Adaptation**: Because `CrossSectionalMarketPolicy` is trained end-to-end on net returns after `7 bps/leg` friction plus a turnover penalty (`0.15 * tos`), the network learned to set near-zero weights on `H1_trade_size_z168h` (`tilt_corr = +0.004 to +0.039`) and instead anchored its cross-sectional tilts on slower-moving **24h–72h price returns (`r72h`, `r24h`, `H1_xs_rel_ret_24h`)**. When retrained without any of the 7 H1 flow/size/volatility features (`drop_all_H1_flow_size_vol`), a pure price-return CrossSectionalMarketPolicy achieves `-58.69%` (2022), `+110.98%` (2024), and `-24.22%` (2025)—matching or beating the full H1 model in 2 out of 3 folds!

### 4.3 `N1_H2_INFORMATION_UTILITY`

```text
N1_H2_INFORMATION_UTILITY
```

| H2 Modality / Feature Set | Fold | Active Eval Coverage | Phase D 12h Log Spread (bps) | Phase D 12h Vol Ratio $Q_5/Q_1$ | Frozen Zero-Mask Marginal Net PnL (USD / %) | **Bounded Retrained Incremental Net PnL (USD / %)** | Bounded Retrained Incremental Selection (%) |
| --- | :---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `H2 bookDepth` (`imb_1pct`, `imb_5pct`, `slope`, `thinning`) | `Fold 1 (2022)` | `0.00%` *(Pre-2023)* | N/A | N/A | $0.00 (0.00%) | -$114.85 (-0.57%) *(RNG noise only)* | -0.24% |
| `H2 bookDepth` (`imb_1pct`, `imb_5pct`, `slope`, `thinning`) | `Fold 2 (2024)` | `99.45%` | `-11.32` to `+2.78` ($p \ge 0.08$, non-sig.) | `0.896x` (`thinning`) | **+$1,121.62 (+5.61%)** | **+$1,115.63 (+5.58%)** | **+2.47%** |
| `H2 bookDepth` (`imb_1pct`, `imb_5pct`, `slope`, `thinning`) | `Fold 3 (2025)` | `100.00%` | — | — | **+$854.35 (+4.27%)** | **+$596.49 (+2.99%)** | **+0.87%** |

- **Interpretation of H2 Utility**: Even though H2 order-book depth features have no standalone directional predictive power in Phase D, providing `H2 bookDepth` as global market context (`mkt_proj`) in 2024 and 2025 modestly improves the conditioning of `asset_score_head` and `step_gate_head` (`+$1,115.63` in 2024, `+$596.49` in 2025), but **fails to induce defensive Cash allocation** during market drawdowns (`average_cash_pct` remains `8.36%` in 2024 and `12.56%` in 2025).

---

## 5. Phase D — Cross-Sectional Allocation vs Market Beta & Dynamic Timing

### 5.1 `N1_CROSS_SECTIONAL_SELECTION_VALUE`

To isolate pure cross-sectional asset selection from total market exposure $E_t$, we normalize N1's active asset weights at every step $t$ to unit risky exposure $p_{t,i} = w_{t,i} / E_t$ ($\sum_{i \in U_t} p_{t,i} = 1$) and compare the resulting 100%-invested portfolio against the 100%-invested active Equal-Weight portfolio $R_{m,t} = \frac{1}{|U_t|}\sum_{i \in U_t} r_{t,i}$:

```text
N1_CROSS_SECTIONAL_SELECTION_VALUE
```

| Fold | Unit-Exp Neural Cum. Return (%) | Unit-Exp Active EW Cum. Return (%) | **Unit-Exp Compounded Selection Spread (%)** | Unit-Exp Step-Sum Selection (%) | Carino Portfolio Selection Contrib (% / USD) | Step Hit Rate (%) | Block-Boot 95% CI (Ann. Sel %) | Prob Selection $> 0$ | Top Symbol Selection Contributors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: | ---: | --- |
| **`Fold1_2022_Bear` (Audit Trace)** | -65.39% | -65.49% | **+0.11%** | -0.10% | +0.06% (+$11.76) | 48.48% | `[-8.90%, +8.61%]` | 50.2% | `SOL` (+2.09% via underweight), `ETC` (+0.46%), `DOGE` (-0.70%) |
| **`Fold1_2022_Bear` (N1 Report)** | — | -65.49% | **+0.92%** *(Carino)* | +1.50% | +0.92% (+$184.00) | 49.31% | `[-5.15%, +9.11%]` | 71.8% | Near Equal-Weight (`HHI = 0.0794`, $N_{\text{eff}} = 12.60/13$) |
| **`Fold2_2024_Expansion`** | +115.18% | +101.29% | **+13.89%** | +7.48% | **+9.83% (+$1,965.75)** | 51.65% | `[-4.27%, +23.47%]` | 87.0% | `XLM` (+4.38%), `DOGE` (+2.48%), `XRP` (+0.47%), `BNB` (+0.37%) |
| **`Fold3_2025_Adaptive`** | -29.83% | -28.39% | **-1.44%** | -2.69% | **-1.93% (-$385.07)** | 49.72% | `[-7.19%, +1.40%]` | **10.0%** | `ETH` (+0.72%), `LTC` (-0.78%), `TRX` (-0.45%), `LINK` (-0.44%) |

### 5.2 `N1_MARKET_BETA_CONTRIBUTION`

```text
N1_MARKET_BETA_CONTRIBUTION
```

| Fold | Mean Risky Exposure $\bar{E}_p$ (%) | Exposure Min / Median / Max (%) | Exposure When Market Drops $>2\%$ in 12h (%) | Exposure When Market Rises $\ge 0\%$ in 12h (%) | Equal-Weight Market Return $R_m$ (%) | **Carino Market Beta Contribution (% / USD)** | Share of Total Net PnL Explained by Market Beta |
| --- | ---: | :---: | ---: | ---: | ---: | ---: | ---: |
| **`Fold1_2022_Bear` (N1 Report)** | **89.49%** | `43.1% / 90.4% / 95.0%` | 89.38% | 89.54% | -65.49% | **-59.82% (-$11,964.00)** | **100.2%** of `-$11,934.81` net loss |
| **`Fold1_2022_Bear` (Audit Trace)** | **90.71%** | `42.3% / 91.7% / 95.0%` | 90.59% | 90.65% | -65.49% | **-60.88% (-$12,175.45)** | **100.1%** of `-$12,160.77` net loss |
| **`Fold2_2024_Expansion`** | **91.64%** | `43.1% / 92.6% / 95.0%` | 91.29% | 91.58% | +101.29% | **+97.18% (+$19,436.68)** | **87.0%** of `+$22,353.70` net profit |
| **`Fold3_2025_Adaptive`** | **87.44%** | `32.4% / 88.0% / 93.8%` | 87.15% | 87.28% | -28.39% | **-22.78% (-$4,555.52)** | **91.3%** of `-$4,988.51` net loss |

### 5.3 `N1_DYNAMIC_TIMING_VALUE` & Causal PIT Risk-Budget Overlay Test

To prevent any confusion between timing attribution and total portfolio delta, Table `N1_DYNAMIC_TIMING_VALUE` distinguishes three separate quantities:
1. **`N1 Carino Dynamic Timing vs Constant Mean Exposure E_bar * EW`**: The Carino-linked contribution of step-by-step variations $(E_{p,t} - \bar{E}_p) R_{m,t}$ to N1's total net return relative to `0% Cash` (`+0.08% / +$15.01` in 2022, `+4.92% / +$983.91` in 2024, `-0.16% / -$32.71` in 2025).
2. **`N1 Carino Dynamic Timing vs B&H Exposure Drift (Component C2)`**: One of the five additive Carino components of `Neural Net Return - Exposure-Matched B&H Net Return` (`+1.98% / +2.10%` in 2022, `+6.87%` in 2024, `+1.85%` in 2025), capturing how N1's exposure path $E_{p,t} - \bar{E}_p$ differed from the passive exposure drift $E_{m,t} - \bar{E}_m$ of Buy-and-Hold.
3. **`Causal PIT Overlay Total Portfolio Net PnL Delta vs N1`**: The total dollar PnL difference $\text{Net PnL}_{\text{Overlay}} - \text{Net PnL}_{\text{N1}}$, which combines the overlay's **static mean exposure difference** ($\bar{E}_{\text{Overlay}} \approx 53\%–69\%$ vs $\bar{E}_{\text{N1}} \approx 87\%–92\%$) AND its **dynamic timing value** (`-5.55%` in 2022, `-9.16%` in 2024, `-18.89%` in 2025).

```text
N1_DYNAMIC_TIMING_VALUE
```

| Canonical Run / Fold | N1 Brinson Timing Step-Sum (%) | N1 Carino Dynamic Timing vs $\bar{E}_p \cdot \text{EW}$ (% / USD) | N1 Carino Timing vs B&H Exposure Drift `C2` (%) | Causal PIT Overlay Avg Exposure (%) | Causal PIT Overlay Net PnL (USD / %) | **Causal PIT Overlay Brinson Timing Value (%)** | **Causal PIT Overlay Total Net PnL Delta vs N1 (USD)** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **`N1_1_FOLD1_2022_AUDIT_TRACE_RUN`** *(N1 orig in parens)* | +0.08% *(+1.04%)* | +0.08% / +$15.01 *(+0.64% / +$128.00)* | +2.10% *(+1.98%)* | 53.14% | -$8,673.62 (-43.37%) | **-5.55%** *(Negative dynamic timing)* | +$3,487.15 *(Entirely from lower static mean beta 53.1% vs 90.7%)* |
| **`N1_FOLD2_2024_CANONICAL_RUN`** | +3.33% | +4.92% / +$983.91 | +6.87% | 69.08% | +$12,119.01 (+60.60%) | **-9.16%** *(Negative dynamic timing)* | **-$10,234.69** *(Severe upside truncation + negative timing)* |
| **`N1_FOLD3_2025_CANONICAL_RUN`** | -0.34% | -0.16% / -$32.71 | +1.85% | 60.99% | -$6,070.77 (-30.35%) | **-18.89%** *(Severe whipsaw timing)* | **-$1,082.26** *(Whipsaw timing outweighs lower static beta)* |

### 5.4 Direct Answers to the Five Mandatory Phase D Questions

1. **Why did the model achieve strong results in 2024 (`+111.77%` vs `+85.22%` Passive EW and `+83.59%` Matched B&H)?**
   - **87.0% of N1's net profit (`+$19,436.68` out of `+$22,353.70`) came from holding `91.64%` Market Beta** during a `+101.29%` equal-weight crypto expansion.
   - Relative to `Exposure-Matched Buy-and-Hold (+$16,718.07)`, the `+$5,635.63` (`+28.18%`) outperformance decomposed into **`+12.25%` (`+$2,450`) from cross-sectional momentum tilts** (`XLMUSDT`, `DOGEUSDT`, `XRPUSDT`, `BNBUSDT`), **`+10.24%` (`+$2,048`) from avoiding Buy-and-Hold cross-sectional weight drift**, and **`+6.87%` (`+$1,374`) from avoiding B&H exposure drift**, minus `-1.09%` mean exposure gap and `-0.09%` cost drag.
2. **Why did the model still hold `87–91%` crypto exposure in bear/correction years (`2022` and `2025`)?**
   - **Structural Softmax Cardinality Bias**: In [`CrossSectionalMarketPolicy.forward`](../../neural_trading/n1/model.py#L129-L130), `w_cand = softmax([cash_logit, asset_logit_1, ..., asset_logit_13])` places 1 Cash logit in competition with $|U_t| = 13$ asset logits. At zero/near-zero logits, the uniform prior on Cash is $\frac{1}{1 + 13} = 7.14\%$ (`92.86%` risky exposure). Across all 3 folds, the unconstrained candidate cash allocation averaged `7.54%–9.86%`.
   - **Zero Learned Regime Sensitivity**: During 12h steps where the crypto market dropped $>2\%$, N1's risky exposure averaged `90.59%` (2022), `91.29%` (2024), and `87.15%` (2025)—within `0.06%–0.29%` of its exposure during positive market steps!
3. **Does asset selection add value after removing market-beta contribution?**
   - **No consistent out-of-sample value.** While unit-exposure selection was positive in the 2024 in-sample discovery fold (`+13.89%` compounded / `+7.48%` step-sum, 95% CI `[-4.27%, +23.47%]`, spanning zero), it was flat in 2022 (`+0.11%` / `-0.10%`, `Prob > 0 = 50.2%`) and **negative in the 2025 post-discovery holdout (`-1.44%` compounded / `-2.69%` step-sum, `Prob > 0 = 10.0%`)**, where N1 lost `-$219.35` (`-1.09%`) against a simple `Costed Step-Rebalanced Equal-Weight` portfolio.
4. **Is there reliable PIT information about downside risk or regime transitions in the current dataset?**
   - **For volatility magnitude: Yes (`H1_parkinson_vol_24h` and `H2_depth_thinning_z168h`). For directional market timing: No.** In crypto, elevated realized volatility and trailing drawdowns occur both before continuation crashes and immediately before sharp short-squeeze relief rallies.
5. **Does dynamic risk budgeting have a sufficiently strong independent economic hypothesis to study in N2 using current data?**
   - **No.** When we explicitly decouple total risk budget $E_t$ from N1's cross-sectional weights $p_{t,i}$ and drive $E_t$ with strictly causal PIT volatility, drawdown, breadth, and 72h trend (`causal_pit_risk_budget_overlay_test`), dynamic timing value is **negative in every single fold (`-5.55%` in 2022, `-9.16%` in 2024, `-18.89%` in 2025)**, reducing 2024 net PnL by `-$10,234.69` and worsening 2025 net loss by `-$1,082.26`.

---

## 6. Phase E — Final Disposition & N2 Feasibility Decision

```text
N1_ECONOMIC_DISPOSITION
```

- **`N1_ECONOMIC_DISPOSITION`**: `REJECTED_FOR_PRODUCTION_CANDIDACY`
  - **Summary of Evidence**:
    1. `87%–100%` of N1's absolute return in every fold is driven by quasi-static `87%–92%` market beta (`+$19,436.68` in 2024; `-$11,964.00` in 2022; `-$4,555.52` in 2025).
    2. The newly engineered H1 spot order-flow and trade-size features (`H1_trade_size_z168h`, `H1_xs_rel_imb_24h`, `H1_spot_taker_imb_*`) require `85x–180x` annualized turnover to trade directly and are largely ignored by the low-turnover neural policy; dropping all 7 non-return H1 features (`drop_all_H1_flow_size_vol`) improves net PnL in 2022 (`+$423.41`) and 2025 (`+$144.74`) and leaves 2024 nearly unchanged (`+110.98%` vs `+111.77%`).
    3. In the only fold outside the 2018–2024 Phase D feature-selection window (`Fold3_2025_Adaptive_Comparison`), N1's cross-sectional asset selection is **negative (`-1.46%` Carino / `-2.45%` Brinson step-sum)** and N1 underperforms a simple `Costed Step-Rebalanced Equal-Weight` benchmark by **`-$219.35` (`-1.09%`)**. Its apparent `+$536.56` (`+2.68%`) advantage over `Exposure-Matched Buy-and-Hold` is entirely an artifact of Buy-and-Hold losing `-4.42%` to weight/exposure drift relative to 12h Equal-Weight.

```text
N2_RESEARCH_HYPOTHESIS
```

- **`N2_RESEARCH_HYPOTHESIS`**: `NONE_AUTHORIZED_ON_CURRENT_H1_H2_FEATURES`
  - Per Phase E rules (*"Chỉ xây mô hình mới nếu Phase D xác định được cơ chế thông tin để cải thiện tổng exposure. Nếu H1 không tạo incremental economic value: `N2_NOT_AUTHORIZED_FROM_CURRENT_EVIDENCE`"*), building `N2 — Cross-Sectional Neural Allocation with Learned Risk Budget` on top of H1/H2 is **not justified** because:
    1. H1 non-return features do not provide positive incremental portfolio value over simple price returns after transaction costs.
    2. H1 cross-sectional selection fails out-of-sample in 2025 (`-1.44%` unit-exposure selection spread).
    3. Causal PIT volatility/drawdown/trend risk-budgeting produces negative Brinson timing across all three folds (`-5.55%`, `-9.16%`, `-18.89%`).

```text
N2_DATA_REQUIREMENTS
```

- **`N2_DATA_REQUIREMENTS`**: Any future greenfield research cycle must NOT re-architect neural heads around the existing 13-coin Spot kline / USD-M `bookDepth` dataset. Before any new neural policy is trained, a genuinely independent information source must first clear pre-neural net-of-cost hurdles on a strictly held-out discovery window:
  - Cross-exchange or spot-perpetual term-structure/basis dislocations across a broad universe ($N \ge 30$ liquid assets) where long-short or benchmark-relative selection does not depend on directional crypto market beta.
  - Exogenous macro/liquidity flow series (e.g., stablecoin mint/burn supply velocity, ETF/institutional session flow separation) tested strictly for out-of-sample regime-transition lead time before neural modeling.

```text
N2_EXPERIMENT_READINESS
```

- **`N2_EXPERIMENT_READINESS`**: `N2_NOT_AUTHORIZED_FROM_CURRENT_EVIDENCE`

```text
PROSPECTIVE_COLLECTOR
```

- **`PROSPECTIVE_COLLECTOR`**: `STOPPED`

```text
REAL_TRADING
```

- **`REAL_TRADING`**: `DISABLED` (`real_orders = False`; frozen M5 ETH candidate `vol_aware_mean_reversion_v1` remains `HISTORICAL_OOS_REJECTED_FOR_PROMOTION`; 2026 burned holdout untouched).
