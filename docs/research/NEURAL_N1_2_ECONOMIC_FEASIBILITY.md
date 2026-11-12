# N1.2 — Post-Cost Economic Feasibility & Neural Policy Evaluation Report

**Document ID**: `NEURAL-N1-2-ECONOMIC-FEASIBILITY-2026-11-11`  
**Status**: `COMPLETED — NEGATIVE POST-COST ECONOMIC VERDICT (NO PRODUCTION CANDIDACY)`  
**Workspace**: `D:\Workspaces\besttime-crypto`  
**Experiment Module**: [`neural_trading/n1_2/experiment.py`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_2/experiment.py)  
**Machine-Readable Results**: [`research/neural_n1_2/n1_2_phase_ef_economic_results.json`](file:///d:/Workspaces/besttime-crypto/research/neural_n1_2/n1_2_phase_ef_economic_results.json)

---

## 1. Executive Decision & Disposition

```text
N1_2_HA_AGGTRADES_DISPOSITION       = REJECTED_POST_COST (Short-horizon sweep reversion decays below friction)
N1_2_HB_CROSS_VENUE_DISPOSITION     = REJECTED_POST_COST (Positive gross edge +$607.51..+$5,011.68, but Negative net PnL after 14 bps RT friction)
N1_2_NEURAL_POLICY_DISPOSITION      = REJECTED_FOR_PRODUCTION_CANDIDACY (Hysteresis suppresses turnover to ~14x/yr but collapses active alpha to passive beta)
PROSPECTIVE_COLLECTOR               = STOPPED
REAL_TRADING                        = DISABLED (real_orders = False)
```

> [!IMPORTANT]
> **Core Economic Conclusion of N1.2**:
> Fresh tick-by-tick `aggTrades` (`555.5M` trades) and synchronized cross-venue/cross-market feeds (`Coinbase USD` + `5m Perp/Spot`) contain **statistically real, highly significant short-horizon predictive information** ($t = -7.57$ for multi-fill book sweeps at 1h; $t = +14.59$ in discovery and $t = +6.30$ in OOS 2025 for Coinbase-vs-Binance price dislocations at 1h).
>
> Furthermore, unlike N0.3 and N1, the **H-B Cross-Venue Simple Baseline** generates **positive implementable gross excess over exposure-matched Equal-Weight** in **both** Discovery 2024 (`+$2,631.39` at 12h; `+$3,143.66` at 4h) and Out-of-Sample 2025 (`+$262.96` at 12h; `+$767.05` at 4h), with positive gross PnL (`+$141.14` to `+$607.51`) even during the `-29.18%` 2025 bear market.
>
> **However, this short-horizon alpha is structurally unharvestable on a Spot Long-Only Taker execution venue (`14 bps` round-trip fee/slippage)**:
> - At `12h` rebalance (`63.09x` turnover in OOS 2025), `+$141.14` of gross PnL is overwhelmed by `$869.38` of execution friction, yielding **`-$729.05` net PnL** (`-$560.61` net excess vs exposure-matched EW).
> - At `4h` rebalance (`239.92x` turnover in OOS 2025), gross PnL rises to `+$607.51` (`+$767.05` gross excess vs matched EW), but execution friction rises to `$3,269.48`, yielding **`-$2,578.66` net PnL**.
> - When `MicrostructureDislocationPolicy` (the bounded Phase E neural policy) is trained with explicit post-cost hysteresis to avoid that friction, it learns to throttle turnover down to `12.19x–13.96x/yr` (`~$200` friction), which **preserves capital relative to the high-turnover simple baseline (`-$1,574.10` vs `-$2,578.66`)** but reduces the portfolio to a near-passive `~37%` Equal-Weight allocation with **no statistically significant net excess over Exposure-Matched Equal-Weight (`-$159.85` on H-B OOS 2025, `+$28.42` on H-A OOS 2025)**.

---

## 2. Phase E — Bounded Neural Architecture (`MicrostructureDislocationPolicy`)

Per Phase D/E rules, we did **not** build a deep black-box network to force-fit weak features. Instead, to test whether a learned cost-aware gate could solve the fundamental **horizon-vs-turnover dilemma** discovered in Phase D (where alpha lives at `1h–4h` but Taker friction requires `< 15x` annual turnover), we implemented [`MicrostructureDislocationPolicy`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_2/experiment.py#L36-L86):
1. **Cross-Sectional Relative Encoder**: Concatenates raw causal features $x_{t,i}$ with cross-sectionally demeaned shocks $x_{t,i} - \bar{x}_t$ across two `LayerNorm + SiLU` layers (`hidden_dim = 24`).
2. **Aggregate Risk-Budget Head**: Maps pooled cross-sectional embeddings into a scalar portfolio exposure budget $B_t \in [0, 1]$, leaving $1 - \sum_i w_{t,i}$ in Cash.
3. **Stateful Hysteresis Gate**: Blends proposed weights $w^{\text{prop}}_t$ with drifted previous weights $w^{\text{prev}}_t$ via a conviction gate $g_t = \sigma((\max_i s_{t,i} - \bar{s}_t) \cdot 1.5 - 0.5)$ and a hard L1 rebalance filter ($\|w^{\text{prop}}_t - w^{\text{prev}}_t\|_1 \ge 0.10$), trained end-to-end on post-cost Sharpe + Sortino utility.

---

## 3. Phase F — Complete 10-Metric Economic Scorecard

All experiments use identical initial capital (`$20,000.00`), Spot long-only constraints ($w_i \in [0, 0.35]$, $\sum_i w_i \le 1.0$), and exact fee accounting (`7 bps` per leg = `14 bps` round-trip base cost; **H-A** additionally charges the asset-specific tick-derived realized half-spread from `ha_realized_bounce_spread_bps`, adding `~0.7 to 3.0 bps` per leg).

### 3.1 Hypothesis H-A (`aggTrades` Order-Flow & Exhaustion-Reversion, 5 Spot Assets, `14 bps RT + Realized Bounce Spread`)

#### A. Discovery CV Split (`Train: 2022–2023` $\to$ `Eval: 2024`, `8,784` bars)

| Policy / Benchmark | 1. Predictive IC (12h $t$-stat) | 2. Implementable Gross PnL (Gross Excess vs Matched EW) | 3. Realized Execution Cost | 4. Net Economic Value (Net Excess vs Matched EW / Sharpe) | 5. Annual Turnover | 6. Max Drawdown | 7. Mean Risk Exposure | 8. Asset Consistency ($+$ / Total) | 9. Regime Consistency ($+$ Half-Years) | 10. Economic Uncertainty (NW $t$-stat / 95% CI) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Cash** | 0.00000 (0.00) | `$0.00` (`-$18,191.17`) | `$0.00` | **`$0.00`** (`-$17,234.90` / `0.000`) | `0.00x` | `0.00%` | `0.0000` | `0 / 5` | `0 / 2` | `0.000` (`[$0, $0]`) |
| **Passive EW (100% Exp)** | 0.00000 (0.00) | `+$18,191.17` (`$0.00`) | `$618.87` | **`+$17,234.90`** (`$0.00` / `1.239`) | `29.50x` | `-51.08%` | `1.0000` | `5 / 5` | `1 / 2` | `+1.272` (`[-$9,369, +$44,034]`) |
| **Passive EW (Matched to Simple `9.77%`)** | 0.00000 (0.00) | `+$1,770.96` (`$0.00`) | `$78.71` | **`+$1,687.45`** (`$0.00` / `1.219`) | `4.50x` | `-6.13%` | `0.0977` | `5 / 5` | `1 / 2` | `+1.252` (`[-$943, +$4,277]`) |
| **Passive EW (Matched to Neural `35.64%`)** | 0.00000 (0.00) | `+$6,644.65` (`$0.00`) | `$254.77` | **`+$6,334.04`** (`$0.00` / `1.228`) | `13.73x` | `-21.12%` | `0.3564` | `5 / 5` | `1 / 2` | `+1.261` (`[-$3,395, +$15,642]`) |
| **Simple Baseline (Momentum Sign)** | -0.01879 (-0.94) | `+$656.23` (`-$1,096.29`) | `$1,621.15` | **`-$1,042.21`** (`-$2,712.08` / `-0.434`) | `97.71x` | `-13.62%` | `0.0967` | `2 / 5` | `1 / 2` | `-0.463` (`[-$4,976, +$3,076]`) |
| **Simple Baseline (Exhaustion-Reversion Sign)** | +0.01879 (+0.94) | `+$1,123.01` (`-$647.95`) | `$1,793.13` | **`-$726.54`** (`-$2,413.99` / `-0.316`) | `103.93x` | `-8.96%` | `0.0977` | `3 / 5` | `0 / 2` | `-0.357` (`[-$4,142, +$2,866]`) |
| **Neural Policy Pilot (`MicrostructureDislocationPolicy`)** | -0.00668 (-0.37) | `+$6,733.42` (`+$88.77`) | `$255.38` | **`+$6,420.65`** (`+$86.61` / `1.236`) | `13.74x` | `-21.19%` | `0.3564` | `5 / 5` | `1 / 2` | `+1.269` (`[-$3,375, +$15,767]`) |

#### B. Out-of-Sample Split (`Train: 2022–2024` $\to$ `Eval: 2025`, `8,758` bars)

| Policy / Benchmark | 1. Predictive IC (12h $t$-stat) | 2. Implementable Gross PnL (Gross Excess vs Matched EW) | 3. Realized Execution Cost | 4. Net Economic Value (Net Excess vs Matched EW / Sharpe) | 5. Annual Turnover | 6. Max Drawdown | 7. Mean Risk Exposure | 8. Asset Consistency ($+$ / Total) | 9. Regime Consistency ($+$ Half-Years) | 10. Economic Uncertainty (NW $t$-stat / 95% CI) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Cash** | 0.00000 (0.00) | `$0.00` (`+$6,904.99`) | `$0.00` | **`$0.00`** (`+$7,197.28` / `0.000`) | `0.00x` | `0.00%` | `0.0000` | `0 / 5` | `0 / 2` | `0.000` (`[$0, $0]`) |
| **Passive EW (100% Exp)** | 0.00000 (0.00) | `-$6,904.99` (`$0.00`) | `$422.13` | **`-$7,197.28`** (`$0.00` / `-0.251`) | `26.96x` | `-50.72%` | `1.0000` | `1 / 5` (`TRX`) | `0 / 2` | `-0.258` (`[-$31,241, +$23,962]`) |
| **Passive EW (Matched to Simple `11.14%`)** | 0.00000 (0.00) | `-$415.83` (`$0.00`) | `$86.85` | **`-$500.38`** (`$0.00` / `-0.273`) | `5.23x` | `-6.94%` | `0.1114` | `1 / 5` | `0 / 2` | `-0.281` (`[-$3,516, +$2,633]`) |
| **Passive EW (Matched to Neural `30.38%`)** | 0.00000 (0.00) | `-$1,402.39` (`$0.00`) | `$203.78` | **`-$1,590.29`** (`$0.00` / `-0.266`) | `12.27x` | `-18.13%` | `0.3038` | `1 / 5` | `0 / 2` | `-0.274` (`[-$9,557, +$7,214]`) |
| **Simple Baseline (Momentum Sign)** | -0.00608 (-0.32) | `-$2,102.10` (`-$1,677.96`) | `$1,864.31` | **`-$3,834.35`** (`-$3,324.35` / `-1.354`) | `121.07x` | `-22.43%` | `0.1133` | `2 / 5` | `0 / 2` | `-1.213` (`[-$10,558, +$2,485]`) |
| **Simple Baseline (Exhaustion-Reversion Sign)** | +0.00608 (+0.32) | **`-$62.64` (`+$353.19`)** | `$1,974.30` | **`-$1,977.14`** (`-$1,476.76` / `-0.878`) | `120.44x` | `-16.01%` | `0.1114` | `2 / 5` (`LINK, TRX`) | `0 / 2` | `-0.885` (`[-$6,294, +$2,379]`) |
| **Neural Policy Pilot (`MicrostructureDislocationPolicy`)** | +0.02679 (+1.43) | `-$1,374.39` (`+$28.00`) | `$202.75` | **`-$1,561.87`** (`+$28.42` / `-0.264`) | `12.19x` | `-17.92%` | `0.3038` | `1 / 5` | `0 / 2` | `-0.272` (`[-$9,445, +$7,142]`) |

---

### 3.2 Hypothesis H-B (Cross-Venue Coinbase USD vs Binance USDT + 5m Perp Lead-Lag, 8 Spot Assets, `14 bps RT`)

#### A. Discovery CV Split (`Train: 2022–2023` $\to$ `Eval: 2024`, `8,784` bars)

| Policy / Benchmark | 1. Predictive IC (12h $t$-stat) | 2. Implementable Gross PnL (Gross Excess vs Matched EW) | 3. Realized Execution Cost | 4. Net Economic Value (Net Excess vs Matched EW / Sharpe) | 5. Annual Turnover | 6. Max Drawdown | 7. Mean Risk Exposure | 8. Asset Consistency ($+$ / Total) | 9. Regime Consistency ($+$ Half-Years) | 10. Economic Uncertainty (NW $t$-stat / 95% CI) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Cash** | 0.00000 (0.00) | `$0.00` (`-$23,617.24`) | `$0.00` | **`$0.00`** (`-$22,722.36` / `0.000`) | `0.00x` | `0.00%` | `0.0000` | `0 / 8` | `0 / 2` | `0.000` (`[$0, $0]`) |
| **Passive EW (100% Exp)** | 0.00000 (0.00) | `+$23,617.24` (`$0.00`) | `$576.42` | **`+$22,722.36`** (`$0.00` / `1.425`) | `29.53x` | `-46.94%` | `1.0000` | `8 / 8` | `2 / 2` | `+1.548` (`[-$5,383, +$45,834]`) |
| **Passive EW (Matched to Simple 12h `6.87%`)** | 0.00000 (0.00) | `+$1,443.20` (`$0.00`) | `$48.77` | **`+$1,392.31`** (`$0.00` / `1.405`) | `3.38x` | `-3.77%` | `0.0687` | `8 / 8` | `2 / 2` | `+1.527` (`[-$389, +$3,128]`) |
| **Passive EW (Matched to Neural 12h `47.63%`)** | 0.00000 (0.00) | `+$10,881.39` (`$0.00`) | `$287.08` | **`+$10,510.36`** (`$0.00` / `1.418`) | `17.22x` | `-24.44%` | `0.4763` | `8 / 8` | `2 / 2` | `+1.541` (`[-$2,609, +$21,787]`) |
| **Simple Baseline (12h Rebalance)** | +0.01461 (+1.07) | **`+$4,074.59` (`+$2,631.39`)** | `$984.20` | **`+$2,997.66`** (**`+$1,605.35`** / `1.415`) | `65.19x` | `-6.05%` | `0.0687` | `7 / 8` | `2 / 2` | `+1.441` (`[-$1,044, +$6,840]`) |
| **Simple Baseline (4h Rebalance)** | +0.01461 (+1.07) | **`+$5,011.68` (`+$3,143.66`)** | `$3,659.32` | **`+$914.13`** (`-$888.05` / `0.410`) | `254.87x` | `-13.90%` | `0.0884` | `8 / 8` | `1 / 2` | `+0.460` (`[-$3,459, +$5,580]`) |
| **Neural Policy Pilot (12h Rebalance)** | -0.02871 (-1.93) | `+$12,019.21` (`+$1,137.82`) | `$294.13` | **`+$11,628.97`** (`+$1,118.61` / `1.493`) | `17.47x` | `-23.42%` | `0.4763` | `8 / 8` | `2 / 2` | `+1.628` (`[-$2,116, +$22,862]`) |

#### B. Out-of-Sample Split (`Train: 2022–2024` $\to$ `Eval: 2025`, `8,758` bars)

| Policy / Benchmark | 1. Predictive IC (12h $t$-stat) | 2. Implementable Gross PnL (Gross Excess vs Matched EW) | 3. Realized Execution Cost | 4. Net Economic Value (Net Excess vs Matched EW / Sharpe) | 5. Annual Turnover | 6. Max Drawdown | 7. Mean Risk Exposure | 8. Asset Consistency ($+$ / Total) | 9. Regime Consistency ($+$ Half-Years) | 10. Economic Uncertainty (NW $t$-stat / 95% CI) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Cash** | 0.00000 (0.00) | `$0.00` (`+$5,835.55`) | `$0.00` | **`$0.00`** (`+$6,082.66` / `0.000`) | `0.00x` | `0.00%` | `0.0000` | `0 / 8` | `0 / 2` | `0.000` (`[$0, $0]`) |
| **Passive EW (100% Exp)** | 0.00000 (0.00) | `-$5,835.55` (`$0.00`) | `$341.03` | **`-$6,082.66`** (`$0.00` / `-0.120`) | `25.14x` | `-53.70%` | `1.0000` | `4 / 8` | `0 / 2` | `-0.121` (`[-$30,459, +$26,913]`) |
| **Passive EW (Matched to Simple 12h `6.81%`)** | 0.00000 (0.00) | `-$121.82` (`$0.00`) | `$47.16` | **`-$168.44`** (`$0.00` / `-0.143`) | `3.35x` | `-4.55%` | `0.0681` | `4 / 8` | `0 / 2` | `-0.144` (`[-$2,099, +$1,811]`) |
| **Passive EW (Matched to Neural 12h `36.95%`)** | 0.00000 (0.00) | `-$1,232.50` (`$0.00`) | `$196.85` | **`-$1,414.25`** (`$0.00` / `-0.132`) | `13.90x` | `-23.10%` | `0.3695` | `4 / 8` | `0 / 2` | `-0.133` (`[-$11,321, +$9,881]`) |
| **Simple Baseline (12h Rebalance)** | -0.00858 (-0.61) | **`+$141.14` (`+$262.96`)** | `$869.38` | **`-$729.05`** (`-$560.61` / `-0.388`) | `63.09x` | `-9.34%` | `0.0681` | `3 / 8` (`ADA, BTC, SOL`) | `0 / 2` | `-0.380` (`[-$4,112, +$2,775]`) |
| **Simple Baseline (4h Rebalance)** | -0.00858 (-0.61) | **`+$607.51` (`+$767.05`)** | `$3,269.48` | **`-$2,578.66`** (`-$2,361.93` / `-1.050`) | `239.92x` | `-20.54%` | `0.0850` | `4 / 8` (`ADA, BTC, LINK, SOL`) | `0 / 2` | `-1.009` (`[-$7,674, +$2,458]`) |
| **Neural Policy Pilot (12h Rebalance)** | +0.01566 (+1.13) | `-$1,393.21` (`-$160.71`) | `$196.37` | **`-$1,574.10`** (`-$159.85` / `-0.161`) | `13.96x` | `-23.16%` | `0.3695` | `4 / 8` | `0 / 2` | `-0.162` (`[-$11,539, +$9,773]`) |
| **Neural Policy Pilot (4h Rebalance)** | +0.01497 (+1.11) | `-$1,387.72` (`-$157.11`) | `$194.86` | **`-$1,567.62`** (`-$155.37` / `-0.162`) | `13.88x` | `-23.07%` | `0.3691` | `4 / 8` | `0 / 2` | `-0.164` (`[-$11,460, +$9,687]`) |

---

## 4. Synthesis of Findings & Architectural Implications

1. **Why Cross-Venue Price Discovery (`H-B1`) Has Real Gross Edge But Fails Net of Taker Fees**:
   - In Discovery 2024 (`12h` rebalance), `H-B1` (`hb1_composite_score`) achieved `+$4,074.59` gross PnL (`+$2,631.39` gross excess over matched EW) and `+$2,997.66` net PnL (`+$1,605.35` net excess over matched EW) after `$984.20` in fees (`65.19x` turnover).
   - In OOS 2025, `H-B1` **continued to generate positive gross PnL** (`+$141.14` at 12h and `+$607.51` at 4h, outperforming exposure-matched EW by `+$262.96` and `+$767.05` before fees), proving that the cross-venue price discovery mechanism is not an in-sample artifact.
   - However, because the cross-venue dislocation compressed in magnitude from 2022–2024 to 2025 (`hb1_cb_premium_dev_z` 1h IC moved from `+0.0446` in 2022 to `+0.0255` in 2025, and 12h IC decayed to zero), the gross profit per trade in 2025 (`~2.2 bps` per one-way rebalance at 12h, or `~2.5 bps` at 4h) fell well below the `7.0 bps` per-leg Spot Taker fee hurdle.
2. **Why `aggTrades` Order-Flow Dislocation (`H-A`) Fails Post-Cost**:
   - Tick-by-tick `aggTrades` reveal strong short-horizon liquidity exhaustion (`ha_multifill_ofi` $t = -7.57$ at 1h). Using the exhaustion-reversion sign (`ha_reversion_composite_score`) in OOS 2025 produces `+$353.19` of gross excess over matched EW (`-$62.64` gross PnL vs `-$415.83` matched EW), but requires `120.44x` annual turnover costing `$1,974.30` (`14 bps RT` + tick bounce spread), resulting in `-$1,977.14` net PnL.
3. **Why Neural Cost-Hysteresis Cannot Manufacture Net Alpha From Sub-Fee Gross Edge**:
   - When `MicrostructureDislocationPolicy` is trained with explicit transaction cost penalties (`7.5 bps` per leg), gradient descent discovers that trading a `2.5 bps` gross signal at a `7.0 bps` per-leg cost has negative expected value. Consequently, the neural network increases its hysteresis gate to hold a slow-moving `~30–37%` Equal-Weight basket (`~13x` turnover), which avoids the `-$1,977` to `-$2,578` fee bleed of the high-turnover rules, but delivers zero active selection edge (`-$159.85` to `+$28.42` net excess vs exposure-matched EW).

---

## 5. N1.3 Phase A2 Closure — Exact 5-Term Gross/Net Trade-Ledger Accounting Bridge & Governance State

Per N1.3 Phase A2 ([`neural_trading/n1_3/phase_a_reconciliation.py`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_3/phase_a_reconciliation.py)), the apparent difference between `gross_pnl_usd - realized_execution_cost_usd` and `net_pnl_usd` in Section 3 is caused by compounding on two different capital paths (`zero_friction_counterfactual_pnl` compounds on an uncharged equity base $E^{\text{gross}}_t$, whereas `realized_net_pnl` compounds on the post-cost equity base $E^{\text{net}}_t - c_t$). Defining:
- `gross_pnl_same_executed_path` $= \sum_{t=0}^{T-1} (E^{\text{net}}_t - c_t) \cdot r^{\text{port}}_t$
- `zero_friction_counterfactual_pnl` $= E^{\text{gross}}_T - E_0$
- `transaction_friction_paid` $= \sum_{t=0}^{T-1} c_t$
- `capital_path_effect` $= \text{gross\_pnl\_same\_executed\_path} - \text{zero\_friction\_counterfactual\_pnl}$
- `realized_net_pnl` $= \text{gross\_pnl\_same\_executed\_path} - \text{transaction\_friction\_paid} = \text{zero\_friction\_counterfactual\_pnl} + \text{capital\_path\_effect} - \text{transaction\_friction\_paid}$

reconciles every N1.2 run across 2024 and 2025 to **`$0.00` residual**:

| Run ID | `zero_friction_counterfactual_pnl` | `capital_path_effect` | `gross_pnl_same_executed_path` | `transaction_friction_paid` | `realized_net_pnl` | Naive Gap (`CF Gross - Cost - Net`) | Exact Bridge Residual |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `HA_2024_Simple_Momentum` | `+$656.23` | `-$77.29` | `+$578.94` | `$1,621.15` | `-$1,042.21` | `+$77.29` | **`$0.00`** |
| `HA_2024_Simple_Reversion` | `+$1,123.01` | `-$56.42` | `+$1,066.59` | `$1,793.13` | `-$726.54` | `+$56.42` | **`$0.00`** |
| `HA_2024_Neural_Policy` | `+$6,733.42` | `-$57.39` | `+$6,676.03` | `$255.38` | `+$6,420.65` | `+$57.39` | **`$0.00`** |
| `HA_2025_Simple_Momentum` | `-$2,102.10` | `+$132.06` | `-$1,970.04` | `$1,864.31` | `-$3,834.35` | `-$132.06` | **`$0.00`** |
| `HA_2025_Simple_Reversion` | `-$62.64` | `+$59.80` | `-$2.84` | `$1,974.30` | `-$1,977.14` | `-$59.80` | **`$0.00`** |
| `HA_2025_Neural_Policy` | `-$1,374.39` | `+$15.27` | `-$1,359.12` | `$202.75` | `-$1,561.87` | `-$15.27` | **`$0.00`** |
| `HB_2024_Simple_12h` | `+$4,074.59` | `-$92.73` | `+$3,981.86` | `$984.20` | `+$2,997.66` | `+$92.73` | **`$0.00`** |
| `HB_2024_Simple_4h` | `+$5,011.68` | `-$438.24` | `+$4,573.44` | `$3,659.32` | `+$914.13` | `+$438.23` | **`$0.00`** |
| `HB_2024_Neural_12h` | `+$12,019.21` | `-$96.11` | `+$11,923.10` | `$294.13` | `+$11,628.97` | `+$96.11` | **`$0.00`** |
| `HB_2025_Simple_12h` | `+$141.14` | `-$0.81` | `+$140.33` | `$869.38` | `-$729.05` | `+$0.81` | **`$0.00`** |
| `HB_2025_Simple_4h` | `+$607.51` | `+$83.31` | `+$690.82` | `$3,269.48` | `-$2,578.66` | `-$83.31` | **`$0.00`** |
| `HB_2025_Neural_12h` | `-$1,393.21` | `+$15.48` | `-$1,377.73` | `$196.37` | `-$1,574.10` | `-$15.48` | **`$0.00`** |

- **Evaluation Window Labeling Note**: Because both `12h` and `4h` rebalance cadences were evaluated on 2025 in Section 3.2B, any subsequent comparison or selection across cadences treats `2025` as **Adaptive Research Development (`adaptive_research_dev_2025`)**, not an untouched independent holdout.
- **N1.2 Disposition**: `REJECTED_FOR_PRODUCTION_CANDIDACY`
- **Frozen M5 Production / Paper Baseline**: `vol_aware_mean_reversion_v1` (ETH_USDT) remains untouched.
- **Prospective Collector**: `STOPPED`
- **Real Trading**: `DISABLED` (`real_orders = False`)
