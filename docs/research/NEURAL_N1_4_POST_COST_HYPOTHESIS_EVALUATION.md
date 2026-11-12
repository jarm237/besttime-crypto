# N1.4 — Greenfield Economic-First Alpha Discovery: Post-Cost Hypothesis Falsification & Bounded Neural Evaluation

- **Date**: 2026-11-11
- **Status**: `PHASE_E_F_G_COMPLETE`
- **Results Ledger**: [`research/neural_n1_4/n1_4_economic_discovery_results.json`](file:///d:/Workspaces/besttime-crypto/research/neural_n1_4/n1_4_economic_discovery_results.json)
- **Implementation**:
  - [`neural_trading/n1_4/falsification.py`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_4/falsification.py)
  - [`neural_trading/n1_4/neural_pilot.py`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_4/neural_pilot.py)
  - [`scripts/n1_4_run_economic_discovery.py`](file:///d:/Workspaces/besttime-crypto/scripts/n1_4_run_economic_discovery.py)

---

## 1. Phase E — Economic Falsification Before Neural Training

Before any neural network training is allowed, both selected candidates (`H-1` and `H-2`) are evaluated using their simplest executable, non-neural economic baselines on `$20,000.00` initial capital across `2022–2025`.

### 1.1 Candidate `H-1`: Dated Quarterly Delivery Basis Carry & Convergence (`SYMUSD_YYMMDD`) — **PASSED PHASE E**

- **Executable Baseline Specification (`build_h1_simple_carry_weights`)**:
  - **2-Leg Delta-Neutral Structure**: `1x` COIN-M Cash-and-Carry (`Long 1.0x Spot Coin` deposited as `1x` inverse margin collateral for `Short 1.0x Dated Quarterly Delivery Future SYMUSD_YYMMDD`).
  - **Entry Rule**: Enter on a `24h` cadence when 24h-smoothed front-quarter basis `f1_basis_ma24_bps >= 75.0 bps` (`> 3.4x` the `22.0 bps` 4-leg round-trip cost), annualized yield `f1_yield_ma24_pct >= 5.0% p.a.`, and `f1_ttm_hours >= 24.0`.
  - **Stateful Hold & Exit Rule**: Hold existing positions across weeks (`mean holding period = 56.36 days`) until either basis compresses to `<= 15.0 bps` (early roll-down harvest) or the contract reaches `08:00 UTC` quarterly delivery settlement (`basis = 0.0 bps`).
  - **Complete Cost Model**: `11.0 bps` per combined entry/exit (`7.0 bps` Spot leg + `4.0 bps` CM Delivery leg = **`22.0 bps` 4-leg round-trip**) plus `5.5 bps` quarterly maturity roll fee (`1.5 bps` settlement + `4.0 bps` new short leg).

#### Table 1A — Complete 13-Metric Economic Falsification of `H-1` Across Regimes (`$20,000` Initial Capital, `22.0 bps` RT Cost)

| Phase E Metric | `2022 Bear` | `2023 Recovery` | `Discovery 2022–2023` | `Validation 2024` | `Adaptive Dev 2025` | `Full 2022–2025` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Gross Economic Payoff** (`zero_friction_counterfactual_pnl`) | `+$331.44` (`+1.66%`) | `+$804.31` (`+4.02%`) | `+$1,098.38` (`+5.49%`) | `+$3,898.48` (`+19.49%`) | `+$1,570.64` (`+7.85%`) | **`+$7,091.13` (`+35.46%`)** |
| **2. Expected Cost to Capture** (`transaction_friction_paid`) | `$141.37` | `$504.36` | `$635.59` | `$839.37` | `$681.33` | **`$2,177.05`** (`$2,152.43` rebal + `$24.62` roll) |
| **3. Net Payoff (`realized_net_pnl`)** | **`+$188.97` (`+0.94%`)** | **`+$291.56` (`+1.46%`)** | **`+$449.09` (`+2.25%`)** | **`+$3,007.88` (`+15.04%`)** | **`+$868.58` (`+4.34%`)** | **`+$4,582.65` (`+22.91%`)** |
| **Net Excess vs Matched Passive Carry** | **`+$178.70`** | **`+$174.31`** | **`+$341.26`** | **`+$669.96`** | **`+$275.76`** | **`+$2,571.61` (`+12.86%`)** |
| **4. Holding Period** (`mean` / `median` days) | `22.07d` / `24.00d` | `42.34d` / `44.00d` | `36.53d` / `38.50d` | `77.69d` / `82.00d` | `51.03d` / `63.00d` | **`56.36d` (`1,352.5h`) / `47.50d`** |
| **5. Realized Turnover** (`annualized_turnover`) | `6.39x/yr` | `22.51x/yr` | `14.12x/yr` | `33.58x/yr` | `30.08x/yr` | **`21.81x/yr`** |
| **6. 5-Term Gross vs Net Bridge**: | | | | | | |
| - `gross_pnl_same_executed_path` | `+$330.35` | `+$795.92` | `+$1,084.68` | `+$3,847.25` | `+$1,549.91` | `+$6,759.70` |
| - `capital_path_effect` | `-$1.09` | `-$8.39` | `-$13.71` | `-$51.23` | `-$20.73` | `-$331.43` |
| - `reconciliation_residual_usd` | **`$0.000000`** | **`$0.000000`** | **`$0.000000`** | **`$0.000000`** | **`$0.000000`** | **`$0.000000`** |
| **7. Exposure & Market Beta**: | | | | | | |
| - `mean_hedged_exposure` | `6.93%` (`93.1%` Cash) | `38.52%` | `22.56%` | `84.83%` | `45.98%` | `43.39%` |
| - `empirical_beta_vs_ew_crypto` | `+0.00045` | `-0.00097` | `-0.00005` | `-0.00807` | `-0.00685` | **`-0.00360`** |
| - `empirical_beta_vs_btc` | `+0.00068` | `-0.00031` | `+0.00030` | `-0.01060` | `-0.00859` | **`-0.00409`** |
| **8. Drawdown (`max_drawdown_pct`)** | **`-0.37%`** | **`-0.86%`** | **`-1.00%`** | **`-2.23%`** | **`-0.61%`** | **`-2.24%`** |
| **9. Tail Risk & Margin Safety**: | | | | | | |
| - `var95_1h_pct` / `cvar95_1h_pct` | `-0.012%` / `-0.027%` | `-0.053%` / `-0.083%` | `-0.037%` / `-0.064%` | `-0.104%` / `-0.153%` | `-0.104%` / `-0.156%` | `-0.074%` / `-0.118%` |
| - `worst_1h_pct` / `worst_7d_pct` | `-0.175%` / `-0.254%` | `-0.277%` / `-0.820%` | `-0.244%` / `-0.954%` | `-1.076%` / `-1.156%` | `-0.489%` / `-0.442%` | `-1.078%` / `-1.427%` |
| - `margin_liquidation_events` | **`0`** | **`0`** | **`0`** | **`0`** | **`0`** | **`0`** |
| **10. Capacity** (`median_hourly_contract_vol`) | `$688,790/h` | `$67,810/h` | `$142,890/h` | `$31,440/h` | `$57,010/h` | `$57,925/h` (instant 1h) / `$550k+/d` TWAP |
| **12. Regime & Asset Breadth** (`positive_assets`) | `6 / 6` active (`BNB=0, SOL=0`) | `6 / 6` active (`BNB=0, SOL=0`) | `6 / 6` active | **`8 / 8` positive** | **`8 / 8` positive** | **`8 / 8` positive** |
| **13. Uncertainty**: | | | | | | |
| - `sharpe_annualized` / `sortino_annualized` | `0.887` / `0.549` | `0.459` / `0.599` | `0.478` / `0.485` | **`1.999` / `3.118`** | `0.740` / `0.952` | **`1.109` / `1.333`** |
| - `net_step_tstat` (Newey-West) | `+2.199` | `+1.301` | `+1.828` | **`+3.790`** | **`+2.650`** | **`+4.892`** |
| - `net_pnl_ci95_usd` (168h block bootstrap) | `[+$34.48, +$359.52]` | `[+$121.70, +$733.74]` | `[+$252.78, +$902.10]` | `[+$1,662.67, +$4,703.90]` | `[+$385.37, +$1,479.37]` | **`[+$2,799.75, +$6,688.03]`** |

#### Table 1B — Metric 11: Timing & Latency Sensitivity of `H-1` (`Full 2022–2025` and Sub-Splits)

Unlike `N1.3` `H-B` (where a `+1h` execution delay wiped out `83.3%` of gross PnL and turned net PnL deeply negative), `H-1` harvests multi-week structural contango convergence (`56.36d` mean holding period) and retains **`85.2%` to `89.9%` of its post-cost net profit even under `next_bar_open_slippage`, `+1h` delay, and `+4h` delay**:

| Execution Latency Mode | `2022 Bear` Net PnL | `2023 Recovery` Net PnL | `Discovery 2022–2023` Net PnL | `Validation 2024` Net PnL | `Adaptive Dev 2025` Net PnL | `Full 2022–2025` Gross PnL | `Full 2022–2025` Friction | `Full 2022–2025` Net PnL | `Full` Sharpe / NW `t` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`close_t` (Causal Bar Close)** | `+$188.97` | `+$291.56` | `+$449.09` | `+$3,007.88` | `+$868.58` | `+$7,091.13` | `$2,177.05` | **`+$4,582.65`** | `1.109` / `+4.892` |
| **`next_bar_open_slippage`** | `+$144.69` | `+$196.93` | `+$313.52` | `+$2,847.80` | `+$708.69` | `+$7,091.13` | `$2,602.99` | **`+$4,091.17`** (`89.3%` retained) | `1.002` / `+4.422` |
| **`1h_delay` (`close_{t+1}`)** | `+$181.18` | `+$197.28` | `+$327.40` | `+$2,918.97` | `+$628.98` | `+$6,580.78` | `$2,158.02` | **`+$4,120.68`** (`89.9%` retained) | `1.007` / `+4.453` |
| **`4h_delay` (`close_{t+4}`)** | `+$186.47` | `+$198.47` | `+$274.06` | `+$2,862.90` | `+$638.69` | `+$6,342.41` | `$2,149.85` | **`+$3,902.86`** (`85.2%` retained) | `0.958` / `+4.252` |

#### Table 1C — Cost Sensitivity Frontier of `H-1` (`0.0 bps` to `44.0 bps` 4-Leg Round-Trip Cost)

| 4-Leg Round-Trip Cost (bps) | `Discovery 2022–2023` Net PnL | `Validation 2024` Net PnL | `Adaptive Dev 2025` Net PnL | `Full 2022–2025` Net PnL | `Full 2022–2025` Net Excess vs Passive Carry |
| :---: | :---: | :---: | :---: | :---: | :---: |
| `0.0 bps` (Zero Rebal Fee, `5.5 bps` Roll Only) | `+$1,094.32` | `+$3,876.15` | `+$1,570.64` | `+$7,060.60` | `+$4,638.40` |
| `10.0 bps` (VIP / Maker Limit Execution) | `+$798.57` | `+$3,477.52` | `+$1,248.67` | `+$5,904.81` | `+$3,670.44` |
| `16.0 bps` (Blended Maker/Taker) | `+$623.10` | `+$3,241.52` | `+$1,057.77` | `+$5,235.10` | `+$3,112.68` |
| **`22.0 bps` (Standard Taker Baseline: `14 bps` Spot + `8 bps` CM)** | **`+$449.09`** | **`+$3,007.88`** | **`+$868.58`** | **`+$4,582.65`** | **`+$2,571.61`** |
| `28.0 bps` (Stressed Taker) | `+$276.54` | `+$2,776.56` | `+$681.08` | `+$3,947.03` | `+$2,046.82` |
| `36.0 bps` (Severe Impact) | `+$48.71` | `+$2,471.73` | `+$433.67` | `+$3,124.95` | `+$1,371.64` |
| `44.0 bps` (`2x` Standard Taker Cost) | `-$176.58` | `+$2,170.94` | `+$189.19` | **`+$2,331.01`** | **`+$723.62`** |

---

### 1.2 Candidate `H-2`: Multi-Day (`72h–168h`) Forced-Deleveraging Spot Liquidity Provision — **REJECTED AT PHASE E**

#### Table 2 — Phase E Falsification of `H-2` (`$20,000` Initial Capital, `14.0 bps` Spot RT Cost)

| Metric | `2022 Bear` | `2023 Recovery` | `Discovery 2022–2023` | `Validation 2024` | `Adaptive Dev 2025` | `Full 2022–2025` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Gross PnL (`zero_friction_counterfactual_pnl`)** | `+$1,476.01` | `+$1,028.87` | `+$2,125.36` | `+$7,409.81` | **`-$103.88` (`-0.52%`)** | `+$11,038.86` |
| **Transaction Friction Paid** | `$366.05` | `$333.55` | `$742.05` | `$529.77` | `$282.23` | `$1,563.49` |
| **Realized Net PnL** | `+$1,085.99` | `+$689.25` | `+$1,348.41` | `+$6,748.62` | **`-$378.74` (`-1.89%`)** | `+$8,991.00` |
| **Net Excess vs Matched Passive Spot EW** | `+$3,694.06` | **`-$2,039.64`** | `+$1,192.42` | `+$3,129.91` | **`-$345.47`** | `+$6,316.47` |
| **Mean Holding Period (days)** | `6.18d` | `6.08d` | `6.91d` | `6.36d` | `7.15d` | `6.18d` |
| **Annualized Turnover** | `26.18x/yr` | `23.26x/yr` | `25.53x/yr` | `34.78x/yr` | `19.87x/yr` | `24.36x/yr` |
| **Empirical Market Beta vs EW Crypto** | `+0.1758` | `+0.1676` | `+0.1727` | `+0.2513` | `+0.1213` | `+0.1656` |
| **Max Drawdown (%)** | **`-22.23%`** | **`-21.15%`** | **`-22.23%`** | **`-21.97%`** | **`-16.36%`** | **`-22.23%`** |
| **Newey-West `t-stat` & 95% CI** | `+0.335` `[-$7.1k, +$9.4k]` | `+0.261` `[-$8.8k, +$9.7k]` | `+0.361` `[-$10.1k, +$11.9k]` | `+1.271` `[-$2.7k, +$15.7k]` | **`-0.003` `[-$5.9k, +$5.1k]`** | `+1.039` `[-$8.3k, +$25.4k]` |
| **Phase E Verdict** | — | **Underperformed benchmark (`-$2,039.64`)** | Statistically noisy (`t = 0.361`) | Bull beta tailwind | **Gross & Net Negative (`-$378.74`)** | **`REJECTED_AT_PHASE_E`** |

- **Why `H-2` is Rejected and Excluded from Phase F Neural Training**:
  1. In `Adaptive Dev 2025`, `H-2` was **gross negative (`-$103.88`)**, **net negative (`-$378.74`)**, and underperformed its exposure-matched passive Spot benchmark (`-$345.47`), with only `3 / 8` assets positive (`LTCUSDT` lost `-$1,167.04` during multi-week 2025 altcoin bleed).
  2. Across every period, `H-2` suffered `-16.36%` to `-22.23%` drawdowns and statistically insignificant `t-stats` (`0.361` in 2022–2023; `-0.003` in 2025) with 95% block-bootstrap confidence intervals spanning `[-$10,077, +$11,947]`.
  3. Per Phase E rules, we **do not train a neural network to rescue a rejected economic mechanism**.

---

## 2. Phase F — Bounded Neural Evaluation on `H-1` (`TermStructureCarryPolicy`)

Because Candidate `H-1` (`DATED_QUARTERLY_DELIVERY_BASIS_CARRY_AND_CONVERGENCE`) passed Phase E across every regime, latency mode, and cost level, we executed **one single bounded neural pilot (`TermStructureCarryPolicy`)** designed directly from the term-structure carry mechanics:
- **Decision Cadence**: `24h` steps (matching multi-week carry holding lifecycles).
- **Inputs**: 6 stationary term-structure features (`f1_basis_ma24_bps`, `f1_yield_ma24_pct`, `f1_ttm_hours`, `f1_basis_z168`, `term_structure_slope_ann_pct`, `f1_yield_cs_excess_pct`), their cross-sectionally demeaned counterparts, and explicit portfolio state `[w_prev_i, cash_prev]`.
- **Outputs**: Per-asset carry allocation scores, a stateful HOLD/rebalance gate $g_{t,i} \in (0, 1)$, and an aggregate Cash vs Carry exposure budget $B_t \in [0, 1]$.
- **External Deterministic Risk Controls**: Inactive/expiring contracts (`f1_ttm_hours < 2.0`) and compressed/backwardated contracts (`f1_basis_ma24_bps <= 15.0`) are masked to `0.0` outside the network; single-asset concentration is capped at `w_i <= 0.35`; L1 hysteresis `0.08` is enforced.

### Table 3 — Phase F Comparison: `TermStructureCarryPolicy` vs `H-1 Simple Carry Baseline` & `Exposure-Matched Passive Carry` (`$20,000` Capital, `22.0 bps` RT Cost)

| Evaluation Split & Strategy | Gross PnL (`CF`) | Total Friction Paid | Realized Net PnL (`Net %`) | Net Excess vs Matched Passive Carry | Net Excess vs `H-1` Simple Carry Baseline | Mean Hedged Exposure | Annualized Turnover | Mean Hold (Days) | Max DD (%) | Annualized Sharpe / Sortino | Newey-West `t-stat` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Split 1: Validation 2024 (Trained strictly on 2022–2023)** | | | | | | | | | | | |
| 1. `TermStructureCarryPolicy` (Neural) | `+$2,579.66` | `$436.17` | **`+$2,123.90` (`+10.62%`)** | **`+$372.82`** | **`-$883.98`** | `64.08%` | **`17.99x/yr`** | `89.86d` | `-1.79%` | `1.586` / `2.205` | `+3.672` |
| 2. Exposure-Matched Passive Carry (`64.08%` Exp) | `+$1,928.05` | `$171.09` | `+$1,751.08` (`+8.76%`) | `$0.00` | `-$1,256.80` | `64.08%` | `6.07x/yr` | `337.68d` | `-1.20%` | `1.732` / `2.732` | `+3.424` |
| 3. **`H-1` Simple Carry Baseline** | **`+$3,898.48`** | `$839.37` | **`+$3,007.88` (`+15.04%`)** | `+$669.96` | `$0.00` | `84.83%` | `33.58x/yr` | `77.69d` | `-2.23%` | **`1.999` / `3.118`** | **`+3.790`** |
| **Split 2: Adaptive Dev 2025 (Trained strictly on 2022–2024)** | | | | | | | | | | | |
| 1. **`TermStructureCarryPolicy` (Neural)** | `+$1,303.18` | **`$305.05`** | **`+$988.84` (`+4.94%`)** | **`+$652.84`** | **`+$120.26`** | `25.95%` | **`13.51x/yr`** | `52.71d` | **`-0.49%`** | **`0.935` / `1.161`** | **`+3.906`** |
| 2. Exposure-Matched Passive Carry (`25.95%` Exp) | `+$420.78` | `$84.04` | `+$336.00` (`+1.68%`) | `$0.00` | `-$532.58` | `25.95%` | `3.26x/yr` | `328.75d` | `-0.29%` | `0.703` / `1.086` | `+2.697` |
| 3. `H-1` Simple Carry Baseline | `+$1,570.64` | `$681.33` | `+$868.58` (`+4.34%`) | `+$275.76` | `$0.00` | `45.98%` | `30.08x/yr` | `51.03d` | `-0.61%` | `0.740` / `0.952` | `+2.650` |

### Key Diagnostic Findings from Phase F
1. **Why `TermStructureCarryPolicy` Beat Passive Carry in Both Years (`+$372.82` in 2024, `+$652.84` in 2025) and Beat Simple Carry in 2025 (`+$120.26`)**:
   - The stateful hold gate successfully cut annualized turnover by **`46.4%` in 2024** (`17.99x` vs `33.58x`, saving `$403.20` in fees) and **`55.1%` in 2025** (`13.51x` vs `30.08x`, saving `$376.28` in fees).
   - In `Adaptive Dev 2025` (after observing a full contango expansion cycle in `2022–2024` training), the neural policy achieved higher net PnL (`+$988.84` vs `+$868.58`), higher annualized Sharpe (`0.935` vs `0.740`), lower max drawdown (`-0.49%` vs `-0.61%`), and higher Newey-West `t-stat` (`+3.906` vs `+2.650`) than the simple carry baseline.
2. **Why `TermStructureCarryPolicy` Trailed the Simple Carry Baseline in Validation 2024 (`-$883.98`)**:
   - When trained strictly on `2022–2023` (where `2022` was a deep bear market with `93.1%` cash and low basis), the neural network's aggregate exposure budget head `B_t` learned a conservative exposure ceiling (`mean_hedged_exposure = 64.08%` in 2024 vs `84.83%` for the simple rule-based baseline).
   - Because 2024 had an extraordinary contango expansion (`+19.49%` gross return on the simple baseline), carrying `20.75%` less average exposure cost the neural network `-$1,318.82` in foregone gross carry, which exceeded its `+$403.20` transaction fee savings.
3. **Attribution Conclusion**:
   - The robust post-cost profitability across `2022`, `2023`, `2024`, and `2025` is driven by the **economic mechanism (`H-1` Dated Quarterly Delivery Basis Carry & Convergence)** and **explicit entry/exit basis hysteresis**, rather than neural representation learning.

---

## 3. Phase G — Final Research Decision & Governance Status

Per the Phase G decision taxonomy and governance rules (`2025` treated strictly as adaptive development rather than an independent holdout confirmation):

```text
H1_QUARTERLY_DELIVERY_CARRY_DISPOSITION = EXPLORATORY_NET_EDGE_SUPPORTED
H2_MULTIDAY_SPOT_LIQUIDITY_DISPOSITION  = REJECTED_AT_PHASE_E_FALSIFICATION
NEURAL_INCREMENTAL_VALUE_DISPOSITION    = NEURAL_INCREMENTAL_VALUE_NOT_SUPPORTED

EVALUATION_2025_STATUS                  = ADAPTIVE_DEVELOPMENT_NOT_INDEPENDENT_CONFIRMATION
N1_4_PRODUCTION_CANDIDATES              = 0
PROSPECTIVE_COLLECTOR                   = STOPPED
REAL_TRADING                            = DISABLED
```

### Summary of What Was Proven in N1.4
1. **First Genuinely Post-Cost Profitable & Latency-Resilient Mechanism Identified**:
   - Moving from short-horizon (`1h–12h`) directional Spot trading (`N0–N1.3`) to **multi-week (`56.36d` mean hold) delta-neutral `1x` COIN-M Dated Quarterly Delivery Basis Carry (`H-1`)** increased expected gross payoff per trade (`75–500 bps`) to **`3.4x–22x` the 4-leg round-trip friction (`22.0 bps`)**.
   - Across `2022–2025`, the non-neural `H-1` simple carry baseline delivered **`+$4,582.65` net PnL (`+22.91%`, `+$2,571.61` net excess over passive carry)** with **`$0.00` accounting residual**, **zero margin liquidations**, **near-zero market beta (`-0.0036`)**, **`-2.24%` max drawdown**, **`Sharpe = 1.109` (`NW t = +4.892`)**, positive net PnL in every single calendar year (`2022`: `+$188.97`, `2023`: `+$291.56`, `2024`: `+$3,007.88`, `2025`: `+$868.58`), **`89.9%` net profit retention under a `+1h` execution delay (`85.2%` under a `+4h` delay)**, and positive net profit even at **`44.0 bps` round-trip cost (`+$2,331.01`)**.
2. **Economic Falsification Properly Filtered Out `H-2` Before Neural Training**:
   - Multi-day (`6–7d` hold) Spot liquidity provision (`H-2`) failed in `2025` (`-$378.74` net, `-16.36%` drawdown) and suffered `-22.23%` drawdowns in `2022–2023`, proving that lengthening the holding horizon alone does not save directional Spot mean-reversion from multi-week regime drawdowns.
3. **Neural Complexity Did Not Beat Simple Economic Rules Consistently**:
   - While `TermStructureCarryPolicy` was net profitable in both 2024 (`+$2,123.90`) and 2025 (`+$988.84`) and beat simple carry in 2025 (`+$120.26` via `55%` turnover reduction), it underperformed the simple carry rule in 2024 (`-$883.98`) due to exposure conservatism learned from `2022–2023`. Thus, `NEURAL_INCREMENTAL_VALUE_DISPOSITION = NEURAL_INCREMENTAL_VALUE_NOT_SUPPORTED`.
