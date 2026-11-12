# N1.3 — Cross-Venue Signal Identity & Executable Economic Edge

**Document ID**: `NEURAL-N1-3-EXECUTABLE-CROSS-VENUE-EDGE-2026-11-11`  
**Status**: `COMPLETED — H-B REJECTED POST-COST & HISTORICAL L1 EXECUTION DATA INSUFFICIENT`  
**Workspace**: `D:\Workspaces\besttime-crypto`  
**Research Package**: [`neural_trading/n1_3/`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_3/__init__.py)  
**Audit Runner**: [`scripts/n1_3_run_cross_venue_audit.py`](file:///d:/Workspaces/besttime-crypto/scripts/n1_3_run_cross_venue_audit.py)  
**Machine-Readable Results**: [`research/neural_n1_3/n1_3_executable_cross_venue_edge_results.json`](file:///d:/Workspaces/besttime-crypto/research/neural_n1_3/n1_3_executable_cross_venue_edge_results.json)

---

## 1. Executive Summary & Phase E Decision Gate

```text
PRIMARY_DECISION_GATE_OUTCOME       = H_B_REJECTED_POST_COST
HISTORICAL_L1_EXECUTION_DATA_STATUS = H_B_EXECUTION_DATA_INSUFFICIENT
BOUNDED_NEURAL_EXPERIMENT_AUTH      = FALSE (No new neural network authorized or trained in N1.3)
EVALUATION_2025_DESIGNATION         = ADAPTIVE_RESEARCH_DEV_2025 (Not independent OOS after cadence comparison)
PROSPECTIVE_COLLECTOR               = STOPPED
REAL_TRADING                        = DISABLED (real_orders = False)
```

> [!IMPORTANT]
> **Definitive Answer on H-B Economic Exploitability**:
> 1. **Quote-Currency Basis (`USDT-USD`) Dominates the Raw Cross-Venue Level Premium (`r = 0.8527`)**:
>    Acquiring and sealing `35,054` raw 1h `USDT-USD` candles (`2022–2025`) from Coinbase Exchange (`sha256 = 1d3b9a78f9c21979...`) proves that **85.27% of the correlation** in the raw `Coinbase USD / Binance USDT - 1` price premium is driven by the common `USDT-USD` quote-currency basis (`std = 7.634 bps`, `P01 = -16.92 bps`, `P99 = +19.22 bps`). A live top-of-book verification snapshot (`2026-11-11T09:35:12Z`) confirms this directly: when `USDT-USD` traded at `0.998795` (`-12.05 bps` discount), raw mid premiums across `BTC, ETH, SOL, LINK, LTC` appeared to be `-11.16 bps` to `-13.07 bps`, whereas after `USDT-USD` numeraire normalization the true venue-specific mid premiums collapsed to **`-1.02 bps` to `+0.90 bps`**.
> 2. **What Survives After `USDT-USD` Normalization (`quote_currency_adjusted` & `venue_specific_residual`)**:
>    - **Cross-Sectional Relative Rank IC Survives**: Because `USDT-USD` is a common multiplicative factor across all 8 assets at timestamp $t$, dividing out `USDT-USD` cleans rolling z-score scaling and slightly **improves** 1h cross-sectional Spearman IC (`+0.03419` $\to$ **`+0.03585` ($t = +15.40$)** in Discovery 2022–2024; `+0.02553` $\to$ **`+0.02598` ($t = +6.38$)** in 2025; and **`+0.02934` ($t = +7.09$)** for `venue_specific_residual_premium_z`).
>    - **Conditional Forward Payoffs Collapse Below Taker Fees**: Removing the `USDT-USD` basis cuts the 4h conditional forward payoff of extreme positive dislocations (`z >= 2.0`) in `adaptive_research_dev_2025` by **63.6%** — from `+33.741 bps` (`raw_premium_dev_z`) down to `+12.284 bps` (`quote_adj_premium_dev_z`) and **`+1.510 bps`** (`venue_specific_residual_premium_z`). At the trading threshold `z >= 1.0` in 2025, `quote_adj_premium_dev_z` earns only **`+1.114 bps` at 1h** and **`+2.291 bps` at 4h** (`+1.195 bps` at 1h and `+0.893 bps` at 4h for `venue_specific_residual_premium_z`) — **6x to 15x smaller than the `14.0 bps` round-trip Spot Taker fee**.
> 3. **Minimal Economic Falsification Verdict (`H_B_REJECTED_POST_COST`)**:
>    Without training any neural model or retuning parameters, the fixed hypothesis-specific simple baseline fails post-cost across both `2022–2023` and `2025 (Adaptive Research Development)` under **all three** signal definitions (`raw_unadjusted`, `quote_currency_adjusted`, `venue_specific_residual`), **all three** latency assumptions (`close_t`, `next_bar_open_slippage`, `1h_delay`), and both `12h` and `4h` cadences. Even at **`0.0 bps` zero transaction cost** in `adaptive_research_dev_2025`, `quote_currency_adjusted` (`12h: -$1,239.65`, `4h: -$761.86`) and `venue_specific_residual` (`12h: -$760.26`) lose money and underperform exposure-matched passive Equal-Weight (`break_even_round_trip_cost_bps = 0.00 bps` at 12h and `0.00–2.57 bps` at 4h vs required `14.0+ bps` Spot Taker friction).

---

## 2. Phase A — Closure of N1.2 Material Definitions

All Phase A definitions and reconciliations are implemented in [`neural_trading/n1_3/phase_a_reconciliation.py`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_3/phase_a_reconciliation.py) and updated in [`docs/research/NEURAL_N1_2_ALPHA_MECHANISM_DISCOVERY.md`](file:///d:/Workspaces/besttime-crypto/docs/research/NEURAL_N1_2_ALPHA_MECHANISM_DISCOVERY.md) and [`docs/research/NEURAL_N1_2_ECONOMIC_FEASIBILITY.md`](file:///d:/Workspaces/besttime-crypto/docs/research/NEURAL_N1_2_ECONOMIC_FEASIBILITY.md) without rerunning H-A research or retraining models.

### 2.1 Phase A1 — `aggTrades` Microstructure Semantics & Feature Renaming

| Quantity Identifier | Exact Mathematical Definition | Observability in Public `aggTrades` | Exact Microstructure Meaning & Why N1.2 Naming Overclaimed |
| :--- | :--- | :---: | :--- |
| `aggregate_trade_events` | $\text{count}(\text{agg\_trade\_id})$ | **EXACT** | Number of rows in the Binance `aggTrades` archive (`555,512,482` rows across 5 pairs). Each row aggregates fills from a single aggressor order that executed at the **exact same price** and within the **exact same timestamp unit**. |
| `underlying_execution_matches` | $\sum (\text{last\_trade\_id} - \text{first\_trade\_id} + 1)$ | **EXACT** | Number of individual matching-engine fill events (`trade_id`s) compressed into an `aggTrade` row at the **same price and timestamp** (`1,171,292,765` matches, `2.1085` per `aggTrade`). Calling this "unique resting limit orders" or "multi-price-level sweeps" overclaims what one `aggTrade` row contains. |
| `unique_resting_orders` | $\text{count}(\text{distinct maker\_order\_id})$ | **UNOBSERVABLE** (Requires L3 `maker_order_id`) | True count of distinct resting limit orders on the book. Cannot be equated to `last_trade_id - first_trade_id + 1` when one resting order is hit across multiple `aggTrades` or when iceberg replenishment / self-trade prevention splits fills. |
| `multi_price_level_sweeps` | Consecutive rows with $t_k = t_{k-1}$, $\text{sign}_k = \text{sign}_{k-1}$, $p_k \ne p_{k-1}$ | **ACROSS CONSECUTIVE ROWS ONLY** | A single aggressive order walking across multiple distinct price levels on the order book. Because Binance `aggTrades` starts a new row whenever price changes, a multi-price sweep produces **multiple consecutive `aggTrade` rows**, whereas `last_id - first_id + 1 >= 3` inside one row measures **same-price match fragmentation**. |

**Canonical Feature Rename Table (`FEATURE_RENAME_MAP_N1_2_TO_N1_3`)**:
- `underlying_order_count` $\to$ `underlying_execution_match_count`
- `buy_sweep_orders` $\to$ `buy_same_price_execution_matches`
- `sell_sweep_orders` $\to$ `sell_same_price_execution_matches`
- `ha_sweep_intensity_raw` / `ha_sweep_intensity_z` $\to$ `ha_same_price_match_fragmentation_raw` / `ha_same_price_match_fragmentation_z`
- `ha_signed_sweep_imb_raw` / `ha_signed_sweep_imb` $\to$ `ha_signed_match_fragmentation_imb_raw` / `ha_signed_match_fragmentation_imb`
- `ha_multifill_ofi_raw` / `ha_multifill_ofi` $\to$ `ha_multimatch_same_price_ofi_raw` / `ha_multimatch_same_price_ofi`

### 2.2 Phase A2 — Exact 5-Term Trade-Ledger Gross/Net Accounting Bridge

In N1.2, `gross_pnl_usd` reported `zero_friction_counterfactual_pnl` ($E^{\text{gross}}_T - E_0$), which compounds returns on a hypothetical zero-cost equity trajectory $E^{\text{gross}}_t$, whereas `net_pnl_usd` compounds returns on the actual post-cost capital base $E^{\text{net}}_t - c_t$. Consequently, the naive subtraction `zero_friction_counterfactual_pnl - transaction_friction_paid` differs from `realized_net_pnl` by the **capital-path compounding effect (`capital_path_effect`)**.

Let $E^{\text{net}}_t$ be actual net portfolio equity at bar $t$, $c_t$ be the dollar transaction friction paid at the start of bar $t$, and $r^{\text{port}}_t = \sum_i w_{t,i} (e^{r_{t,i}} - 1)$ be the bar portfolio return. Then:

$$
\begin{aligned}
\text{gross\_pnl\_same\_executed\_path} &= \sum_{t=0}^{T-1} (E^{\text{net}}_t - c_t) \cdot r^{\text{port}}_t \\
\text{zero\_friction\_counterfactual\_pnl} &= E^{\text{gross}}_T - E_0 = \sum_{t=0}^{T-1} E^{\text{gross}}_t \cdot r^{\text{port}}_t \\
\text{transaction\_friction\_paid} &= \sum_{t=0}^{T-1} c_t \\
\text{capital\_path\_effect} &= \text{gross\_pnl\_same\_executed\_path} - \text{zero\_friction\_counterfactual\_pnl} \\
\text{realized\_net\_pnl} &= \text{gross\_pnl\_same\_executed\_path} - \text{transaction\_friction\_paid} \\
&= \text{zero\_friction\_counterfactual\_pnl} + \text{capital\_path\_effect} - \text{transaction\_friction\_paid}
\end{aligned}
$$

When cumulative returns are positive (as in 2024), paying fees reduces the invested capital base ($E^{\text{net}}_t < E^{\text{gross}}_t$), so `capital_path_effect < 0`. When cumulative returns are negative or when high-friction drawdowns shrink capital before subsequent losing bars (as in `HB_2025_Simple_4h`), `capital_path_effect > 0` (`+$83.31`) because a smaller post-cost capital base loses fewer dollars on negative return bars.

| N1.2 Strategy Run | `zero_friction_counterfactual_pnl` | `capital_path_effect` | `gross_pnl_same_executed_path` | `transaction_friction_paid` | `realized_net_pnl` | Naive Discrepancy (`CF Gross - Cost - Net`) | Exact 5-Term Bridge Residual |
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

---

## 3. Phase B — Separating Venue Premium From Quote-Currency (`USDT-USD`) Basis

Implemented in [`neural_trading/n1_3/phase_b_quote_basis.py`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_3/phase_b_quote_basis.py) with sealed provenance in [`research/neural_n1_3/manifests/n1_3_coinbase_usdt_usd_manifest.json`](file:///d:/Workspaces/besttime-crypto/research/neural_n1_3/manifests/n1_3_coinbase_usdt_usd_manifest.json).

### 3.1 `USDT-USD` Raw Historical Data Provenance & PIT Alignment

- **Source & Endpoint**: Coinbase Exchange REST Archive (`https://api.exchange.coinbase.com/products/USDT-USD/candles?granularity=3600`).
- **Coverage & Integrity**: `35,054` 1h bars (`2022-01-01T00:00:00Z` to `2025-12-31T23:00:00Z`, `99.97%` coverage across the 4-year grid), `0` duplicate timestamps, `100%` strict monotonic timestamp order, `sha256 = 1d3b9a78f9c2197954586a2f15578f251b2b3461f2d9859fd1fa2bf88df93152`.
- **PIT Candle-Close Alignment Audit**:
  - Every Coinbase 1h candle timestamped by `open_time_sec` spans $[t - 3600\text{s}, t)$ and is aligned to `hour_close_ms = (open_time_sec + 3600) * 1000`.
  - Every Binance 1h kline spans `[open_time_ms, close_time_ms]` (`open_time_ms + 3,599,999 ms`) and is aligned to `hour_close_ms = open_time_ms + 3,600,000`.
  - `lookahead_rows_count = 0` across all `280,512` symbol-hour rows (`8` assets $\times$ `35,064` hours).

### 3.2 Three-Way Decomposition of the H-B Cross-Venue Signal

At each hour close $t$ and asset $i \in \{\text{ADA, BTC, DOGE, ETH, LINK, LTC, SOL, XRP}\}$, let $P^{\text{CB,USD}}_{i,t}$ be the Coinbase `ASSET-USD` close, $P^{\text{BN,USDT}}_{i,t}$ be the Binance `ASSETUSDT` close, and $P^{\text{USDT-USD}}_t$ be the Coinbase `USDT-USD` close. Then the Binance price expressed in true **USD numeraire** is $P^{\text{BN,USD-eq}}_{i,t} = P^{\text{BN,USDT}}_{i,t} \cdot P^{\text{USDT-USD}}_t$, yielding three distinct series:

1. **`raw_coinbase_binance_premium_bps`**:
   $$\text{Prem}^{\text{raw}}_{i,t} = 10^4 \times \left(\frac{P^{\text{CB,USD}}_{i,t}}{P^{\text{BN,USDT}}_{i,t}} - 1\right) \approx \text{Prem}^{\text{quote-adj}}_{i,t} + \text{Basis}^{\text{USDT-USD}}_t$$
2. **`quote_currency_adjusted_premium_bps`** (Common USD Numeraire):
   $$\text{Prem}^{\text{quote-adj}}_{i,t} = 10^4 \times \left(\frac{P^{\text{CB,USD}}_{i,t}}{P^{\text{BN,USDT}}_{i,t} \cdot P^{\text{USDT-USD}}_t} - 1\right)$$
3. **`venue_specific_residual_premium_bps`** (Idiosyncratic Asset-Specific Venue Dislocation):
   $$\text{Prem}^{\text{residual}}_{i,t} = \text{Prem}^{\text{quote-adj}}_{i,t} - \frac{1}{N_t}\sum_{j=1}^{N_t} \text{Prem}^{\text{quote-adj}}_{j,t}$$

**Empirical Level & Variance Decomposition (`267,013` Valid Multi-Venue Asset-Hours, 2022–2025)**:
- **`USDT-USD` Basis Distribution**: `mean = -0.324 bps`, `std = 7.634 bps`, `P01 = -16.923 bps`, `P05 = -9.900 bps`, `median = 0.000 bps`, `P95 = +7.000 bps`, `P99 = +19.223 bps`.
- **Correlation of Raw Premium with `USDT-USD` Basis**: **`r = +0.8527`** (`raw_premium_std = 9.020 bps` vs `quote_adjusted_premium_std = 4.651 bps` and `venue_specific_residual_std = 4.307 bps`). Thus **`73.4%` of the variance** (`1 - (4.651/9.020)^2`) of the raw Coinbase-vs-Binance price premium is pure `USDT-USD` stablecoin exchange-rate fluctuation rather than asset-specific order flow!
- **Correlation of Rolling Z-Score Features (`raw_premium_dev_z` vs `quote_adj_premium_dev_z`)**: **`r = +0.5877`** (`r = +0.5061` with `venue_specific_residual_premium_z`), showing that more than `41%` of the variation in the rolling z-score trigger used in N1.2 came from `USDT-USD` basis swings.

### 3.3 Predictive IC Before vs After Quote-Currency Normalization

| Signal Variant | Split | 1h Cross-Sectional IC ($t$-stat) | 1h Time-Series IC ($t$-stat) | 4h Cross-Sectional IC ($t$-stat) | 4h Time-Series IC ($t$-stat) | 12h Cross-Sectional IC ($t$-stat) | 24h Cross-Sectional IC ($t$-stat) | Positive Assets (`1h CS`) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`raw_premium_dev_z`** (Unadjusted) | Discovery `2022–2024` | `+0.03419` (`+14.59`) | `+0.02561` (`+12.22`) | `+0.02454` (`+5.08`) | `+0.01760` (`+4.04`) | `+0.02582` (`+3.22`) | `+0.01735` (`+1.46`) | `8 / 8` |
| **`quote_adj_premium_dev_z`** (USD Numeraire) | Discovery `2022–2024` | **`+0.03585` (`+15.40`)** | `+0.02405` (`+11.96`) | **`+0.02685` (`+5.63`)** | `+0.01319` (`+3.25`) | **`+0.02617` (`+3.22`)** | `+0.01319` (`+1.09`) | `8 / 8` |
| **`venue_specific_residual_premium_z`** | Discovery `2022–2024` | **`+0.03561` (`+15.23`)** | `+0.02411` (`+12.31`) | `+0.02521` (`+5.12`) | `+0.01696` (`+4.23`) | `+0.02267` (`+2.74`) | `+0.01493` (`+1.25`) | `8 / 8` |
| **`raw_cb_minus_bn_ret_z`** (Unadjusted 1h Ret) | Discovery `2022–2024` | `+0.02692` (`+10.85`) | `+0.01627` (`+6.53`) | `+0.01759` (`+3.61`) | `+0.01247` (`+2.90`) | `+0.01126` (`+1.41`) | `+0.02117` (`+1.83`) | `8 / 8` |
| **`quote_adj_cb_minus_bn_ret_z`** (USD Numeraire) | Discovery `2022–2024` | **`+0.02735` (`+11.09`)** | `+0.02350` (`+10.56`) | **`+0.01919` (`+4.06`)** | `+0.01614` (`+3.95`) | `+0.01259` (`+1.64`) | `+0.02165` (`+1.96`) | `8 / 8` |
| **`raw_composite_score`** (Unadjusted H-B) | Discovery `2022–2024` | `+0.03693` (`+15.45`) | `+0.02530` (`+11.53`) | `+0.02471` (`+5.18`) | `+0.01857` (`+4.22`) | `+0.02190` (`+2.72`) | `+0.01658` (`+1.41`) | `8 / 8` |
| **`quote_adj_composite_score`** (USD Numeraire) | Discovery `2022–2024` | **`+0.03846` (`+16.21`)** | `+0.02821` (`+13.48`) | **`+0.02678` (`+5.74`)** | `+0.01744` (`+4.26`) | `+0.02247` (`+2.79`) | `+0.01425` (`+1.22`) | `8 / 8` |
| **`residual_composite_score`** (Venue Residual) | Discovery `2022–2024` | **`+0.03771` (`+15.86`)** | `+0.02793` (`+13.68`) | `+0.02533` (`+5.25`) | `+0.02016` (`+4.98`) | `+0.01980` (`+2.42`) | `+0.01552` (`+1.33`) | `8 / 8` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **`raw_premium_dev_z`** (Unadjusted) | Dev `2025` | `+0.02553` (`+6.30`) | `+0.01440` (`+3.90`) | `+0.00778` (`+0.90`) | `+0.00916` (`+1.22`) | `-0.00065` (`-0.05`) | `-0.01105` (`-0.57`) | `8 / 8` |
| **`quote_adj_premium_dev_z`** (USD Numeraire) | Dev `2025` | **`+0.02598` (`+6.38`)** | `+0.01020` (`+2.85`) | **`+0.01070` (`+1.27`)** | `+0.00405` (`+0.55`) | `+0.00438` (`+0.34`) | `-0.00772` (`-0.40`) | `8 / 8` |
| **`venue_specific_residual_premium_z`** | Dev `2025` | **`+0.02934` (`+7.09`)** | `+0.00991` (`+2.86`) | `+0.00637` (`+0.77`) | `-0.00174` (`-0.25`) | `-0.00201` (`-0.16`) | `-0.01247` (`-0.67`) | `8 / 8` |
| **`raw_composite_score`** (Unadjusted H-B) | Dev `2025` | `+0.02660` (`+6.55`) | `+0.01494` (`+4.04`) | `+0.00965` (`+1.16`) | `+0.00807` (`+1.11`) | `-0.00858` (`-0.61`) | `-0.00885` (`-0.46`) | `8 / 8` |
| **`quote_adj_composite_score`** (USD Numeraire) | Dev `2025` | **`+0.02735` (`+6.72`)** | `+0.01552` (`+4.28`) | **`+0.01148` (`+1.41`)** | `+0.00688` (`+0.96`) | `-0.00478` (`-0.35`) | `-0.00643` (`-0.34`) | `8 / 8` |
| **`residual_composite_score`** (Venue Residual) | Dev `2025` | **`+0.02985` (`+7.30`)** | `+0.01505` (`+4.23`) | `+0.00836` (`+1.03`) | `+0.00264` (`+0.38`) | `-0.00956` (`-0.70`) | `-0.00988` (`-0.53`) | `8 / 8` |

### 3.4 Conditional 1h and 4h Forward Payoff (in bps) Before vs After Quote Normalization

| Signal Variant & Period | Condition `z >= 1.0` Event Count | `z >= 1.0` Mean 1h Forward Return (bps) | `z >= 1.0` Mean 4h Forward Return (bps) | Condition `z >= 1.5` Event Count | `z >= 1.5` Mean 1h Forward Return (bps) | `z >= 1.5` Mean 4h Forward Return (bps) | Condition `z >= 2.0` Event Count | `z >= 2.0` Mean 1h Forward Return (bps) | `z >= 2.0` Mean 4h Forward Return (bps) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`raw_premium_dev_z` (`2022–2024`)** | `26,184` | `+3.431 bps` | `+8.046 bps` | `12,690` | `+6.245 bps` | `+15.174 bps` | `6,089` | `+9.869 bps` | `+24.671 bps` |
| **`quote_adj_premium_dev_z` (`2022–2024`)** | `26,645` | `+4.374 bps` | `+9.419 bps` | `12,920` | `+7.107 bps` | `+14.085 bps` | `6,385` | `+9.671 bps` | `+20.733 bps` |
| **`venue_specific_residual_z` (`2022–2024`)** | `24,523` | `+3.568 bps` | `+8.983 bps` | `11,932` | `+5.534 bps` | `+12.011 bps` | `5,969` | `+8.332 bps` | `+18.969 bps` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **`raw_premium_dev_z` (`Dev 2025`)** | `8,383` | `+1.500 bps` | `+5.651 bps` | `3,897` | `+3.428 bps` | `+15.324 bps` | `1,724` | `+7.177 bps` | **`+33.741 bps`** |
| **`quote_adj_premium_dev_z` (`Dev 2025`)** | `8,889` | **`+1.114 bps`** | **`+2.291 bps`** | `4,209` | **`+1.797 bps`** | **`+6.020 bps`** | `1,978` | **`+3.005 bps`** | **`+12.284 bps`** |
| **`venue_specific_residual_z` (`Dev 2025`)** | `8,042` | **`+1.195 bps`** | **`+0.893 bps`** | `3,962` | **`+1.964 bps`** | **`+2.054 bps`** | `1,967` | **`+3.063 bps`** | **`+1.510 bps`** |

> [!WARNING]
> **Why Quote-Currency Normalization Is Decisive in 2025**:
> In `Dev 2025`, the raw unadjusted signal `raw_premium_dev_z >= 2.0` appeared to predict a `+33.741 bps` 4h forward return (`+15.324 bps` at `z >= 1.5`). Once the `USDT-USD` basis is removed, **that 4h payoff drops by 63.6% to `+12.284 bps` (`quote_adj_premium_dev_z`) and by 95.5% to `+1.510 bps` (`venue_specific_residual_premium_z`)!** The apparent large 4h payoff in raw 2025 data was heavily contaminated by macro `USDT-USD` discount/premium episodes (when all `SYMUSDT` pairs repriced simultaneously against `USDT`), not an idiosyncratic asset-level arbitrage gap. At the portfolio entry threshold (`z >= 1.0`), the quote-adjusted 1h payoff (`+1.114 bps`) and 4h payoff (`+2.291 bps`) are a small fraction of a single `14.0 bps` Spot Taker round-trip.

---

## 4. Phase C — Executable Price & Liquidity Feasibility Audit

Implemented in [`neural_trading/n1_3/phase_cd_execution_and_falsification.py`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_3/phase_cd_execution_and_falsification.py).

### 4.1 Historical L1 Bid/Ask & L2 Order-Book Archive Probes (`2022–2025`)

Per Phase C rules, we strictly distinguish candle closes (`last traded price` in `1h`/`5m` klines) and tick-bounce estimates (`ha_realized_bounce_spread_bps`) from **observed historical top-of-book L1 bid/ask quotes (`bookTicker`) and L2 order-book depth**:

| Venue & Feed Type | Authoritative Archive URL Probed | HTTP Status | Historical Availability Verdict |
| :--- | :--- | :---: | :--- |
| **Binance Spot Monthly `bookTicker` (L1 Bid/Ask)** | `https://data.binance.vision/data/spot/monthly/bookTicker/BTCUSDT/BTCUSDT-bookTicker-2024-01.zip` | `HTTP 404` | **UNAVAILABLE AT PUBLIC ARCHIVES** |
| **Binance Spot Daily `bookTicker` (L1 Bid/Ask)** | `https://data.binance.vision/data/spot/daily/bookTicker/BTCUSDT/BTCUSDT-bookTicker-2024-06-15.zip` | `HTTP 404` | **UNAVAILABLE AT PUBLIC ARCHIVES** |
| **Binance Spot Daily `bookDepth` (L2 Depth)** | `https://data.binance.vision/data/spot/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-2024-06-15.zip` | `HTTP 404` | **UNAVAILABLE AT PUBLIC ARCHIVES** |
| **Coinbase Exchange Historical Order Book** | `https://api.exchange.coinbase.com/products/BTC-USD/book/history` | `HTTP 404` | **UNAVAILABLE (Live Snapshot / WS Only)** |

Consequently, for historical L1/L2 quote replay across 2022–2025, **`H_B_EXECUTION_FEASIBILITY = H_B_EXECUTION_DATA_INSUFFICIENT`**.

### 4.2 Live Top-of-Book L1 & L2 Verification Snapshot (`CrossVenueForwardRecorder`)

To verify live executable spread, top-of-book liquidity, and `USDT-USD` conversion friction without touching the canonical M1–M5 collector or enabling real trading, we implemented the standalone research-only [`CrossVenueForwardRecorder`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_3/phase_cd_execution_and_falsification.py#L72-L193) and recorded a synchronized multi-venue L1/L2 snapshot (`research/neural_n1_3/forward_l1_recorder_sample/n1_3_cross_venue_l1_snapshot_sample.jsonl` at `2026-11-11T09:35:12Z`, when Coinbase `USDT-USD` bid/ask was `0.998790 / 0.998800`, mid `0.998795`, L1 spread `0.100 bps`):

| Asset | Binance L1 Bid / Ask (`USDT`) | Binance L1 Spread (bps) | Coinbase L1 Bid / Ask (`USD`) | Coinbase L1 Spread (bps) | Raw Unadjusted Mid Premium (bps) | **Quote-Adjusted (`USDT-USD`) Mid Premium (bps)** | **Executable Buy-Binance-Ask / Sell-Coinbase-Bid Edge Before Fees (bps)** |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `BTCUSDT` | `72816.71 / 72816.72` | `0.001 bps` | `72731.76 / 72731.77` | `0.001 bps` | `-11.666 bps` | **`+0.386 bps`** | `+0.380 bps` (Net `-13.62 bps` after 14 bps fees) |
| `ETHUSDT` | `2239.88 / 2239.89` | `0.045 bps` | `2237.14 / 2237.15` | `0.045 bps` | `-12.233 bps` | **`-0.181 bps`** | `-0.231 bps` (Net `-14.23 bps` after 14 bps fees) |
| `SOLUSDT` | `91.29 / 91.30` | `1.095 bps` | `91.17 / 91.19` | `2.193 bps` | `-12.596 bps` | **`-0.545 bps`** | `-2.194 bps` (Net `-16.19 bps` after 14 bps fees) |
| `LINKUSDT` | `9.21 / 9.22` | `10.852 bps` | `9.20 / 9.21` | `10.864 bps` | `-10.852 bps` | **`+1.201 bps`** | `-9.661 bps` (Net `-23.66 bps` after 14 bps fees) |
| `LTCUSDT` | `55.66 / 55.67` | `1.796 bps` | `55.58 / 55.60` | `3.598 bps` | `-13.473 bps` | **`-1.424 bps`** | `-4.126 bps` (Net `-18.13 bps` after 14 bps fees) |

---

## 5. Phase D — Minimal Economic Falsification (No Neural Retraining, No Parameter Retuning)

Per Phase D rules, we evaluated the **exact fixed simple baseline** (`z_threshold = 1.0`, `max_weight = 0.35`, `gross_cap = 1.0`, `hysteresis_l1 = 0.12`, initial capital `$20,000.00`) across three signal variants (`raw_unadjusted`, `quote_currency_adjusted`, `venue_specific_residual`), three latency modes (`close_t`, `next_bar_open_slippage`, `1h_delay`), and the `0..22 bps` round-trip cost frontier across `2022–2023`, `2024`, and `2025 (Adaptive Research Development)`.

### 5.1 Complete Economic Falsification Across Periods, Signal Variants, and Latency Modes (`14.0 bps` Round-Trip Base Fee)

| Period & Rebalance Cadence | Signal Variant | Latency Mode | Zero-Friction Counterfactual Gross PnL | Same-Path Gross PnL | Transaction Friction Paid | Capital-Path Effect | **Realized Net PnL** | **Net Excess vs Matched Passive EW** | Annual Turnover | Trade Leg Count | Net Sharpe (NW $t$-stat) | Break-Even RT Cost vs Matched EW |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`2022–2023` (12h)** | `raw_unadjusted` | `close_t` | `+$258.50` | `+$217.50` | `$1,599.03` | `-$41.00` | **`-$1,381.53`** | **`-$1,568.58`** | `65.17x` | `16,803` | `-0.278` (`-0.483`) | `0.57 bps` |
| **`2022–2023` (12h)** | `quote_currency_adjusted` | `close_t` | `-$1,472.73` | `-$1,520.92` | `$1,717.81` | `-$48.19` | **`-$3,238.73`** | **`-$3,435.93`** | `72.42x` | `18,622` | `-0.742` (`-1.269`) | `0.00 bps` |
| **`2022–2023` (12h)** | `venue_specific_residual` | `close_t` | `-$1,990.10` | `-$2,014.04` | `$1,413.85` | `-$23.93` | **`-$3,427.88`** | **`-$3,602.80`** | `59.43x` | `17,157` | `-0.881` (`-1.508`) | `0.00 bps` |
| **`2022–2023` (4h)** | `raw_unadjusted` | `close_t` | `+$7,642.19` | `+$5,857.11` | `$6,227.63` | `-$1,785.08` | **`-$370.52`** | **`-$598.18`** | `248.19x` | `24,992` | `-0.036` (`-0.064`) | `13.21 bps` |
| **`2022–2023` (4h)** | `quote_currency_adjusted` | `close_t` | `+$3,991.85` | `+$3,298.26` | `$5,197.08` | `-$693.59` | **`-$1,898.82`** | **`-$2,086.78`** | `209.61x` | `24,026` | `-0.415` (`-0.713`) | `9.67 bps` |
| **`2022–2023` (4h)** | `venue_specific_residual` | `close_t` | `+$2,568.83` | `+$2,025.65` | `$4,397.31` | `-$543.18` | **`-$2,371.66`** | **`-$2,553.01`** | `176.48x` | `23,016` | `-0.591` (`-0.980`) | `6.62 bps` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **`2024` (12h)** | `raw_unadjusted` | `close_t` | `+$4,074.59` | `+$3,981.86` | `$984.20` | `-$92.73` | **`+$2,997.66`** | **`+$1,605.35`** | `65.19x` | `8,470` | `+1.415` (`+1.441`) | `42.46 bps` |
| **`2024` (12h)** | `quote_currency_adjusted` | `close_t` | `+$4,356.88` | `+$4,231.93` | `$1,048.65` | `-$124.95` | **`+$3,183.28`** | **`+$1,685.61`** | `70.35x` | `9,205` | `+1.627` (`+1.685`) | `41.91 bps` |
| **`2024` (12h)** | `quote_currency_adjusted` | `next_bar_open_slippage` | `+$4,356.88` | `+$4,217.55` | `$1,170.93` | `-$139.33` | **`+$3,046.62`** | **`+$1,548.95`** | `70.35x` | `9,205` | `+1.564` (`+1.620`) | `41.91 bps` |
| **`2024` (12h)** | `quote_currency_adjusted` | `1h_delay` | `+$3,738.64` | `+$3,659.91` | `$1,063.61` | `-$78.73` | **`+$2,596.30`** | **`+$1,098.63`** | `70.26x` | `9,132` | `+1.431` (`+1.487`) | `—` |
| **`2024` (12h)** | `venue_specific_residual` | `close_t` | `+$3,961.75` | `+$3,874.27` | `$810.83` | `-$87.49` | **`+$3,063.43`** | **`+$1,792.43`** | `54.43x` | `7,907` | `+1.886` (`+2.052`) | `51.38 bps` |
| **`2024` (4h)** | `raw_unadjusted` | `close_t` | `+$5,011.68` | `+$4,573.44` | `$3,659.32` | `-$438.24` | **`+$914.13`** | **`-$888.05`** | `254.87x` | `12,662` | `+0.410` (`+0.460`) | `12.51 bps` |
| **`2024` (4h)** | `quote_currency_adjusted` | `close_t` | `+$4,970.77` | `+$4,398.75` | `$3,458.09` | `-$572.02` | **`+$940.66`** | **`-$822.77`** | `250.74x` | `13,138` | `+0.446` (`+0.494`) | `12.71 bps` |
| **`2024` (4h)** | `venue_specific_residual` | `close_t` | `+$4,414.77` | `+$4,032.55` | `$2,998.13` | `-$382.22` | **`+$1,034.42`** | **`-$598.58`** | `212.30x` | `12,623` | `+0.538` (`+0.623`) | `13.03 bps` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **`Dev 2025` (12h)** | `raw_unadjusted` | `close_t` | `+$141.14` | `+$140.33` | `$869.38` | `-$0.81` | **`-$729.05`** | **`-$560.61`** | `63.09x` | `8,203` | `-0.388` (`-0.380`) | `4.40 bps` |
| **`Dev 2025` (12h)** | `raw_unadjusted` | `next_bar_open_slippage` | `+$141.14` | `+$139.99` | `$952.81` | `-$1.14` | **`-$812.82`** | **`-$644.38`** | `63.09x` | `8,203` | `-0.438` (`-0.430`) | `4.40 bps` |
| **`Dev 2025` (12h)** | `raw_unadjusted` | `1h_delay` | `+$457.81` | `+$449.38` | `$875.01` | `-$8.43` | **`-$425.63`** | **`-$257.19`** | `63.06x` | `8,183` | `-0.205` (`-0.209`) | `—` |
| **`Dev 2025` (12h)** | **`quote_currency_adjusted`** | `close_t` | **`-$1,239.65`** | **`-$1,202.65`** | `$932.38` | `+$36.99` | **`-$2,135.03`** | **`-$1,947.73`** | `69.86x` | `9,209` | `-1.164` (`-1.113`) | **`0.00 bps`** |
| **`Dev 2025` (12h)** | **`quote_currency_adjusted`** | `next_bar_open_slippage` | **`-$1,239.65`** | **`-$1,199.52`** | `$1,022.28` | `+$40.13` | **`-$2,221.80`** | **`-$2,034.50`** | `69.86x` | `9,209` | `-1.216` (`-1.163`) | **`0.00 bps`** |
| **`Dev 2025` (12h)** | **`quote_currency_adjusted`** | `1h_delay` | **`-$1,158.89`** | **`-$1,133.50`** | `$924.20` | `+$25.39` | **`-$2,057.70`** | **`-$1,870.40`** | `69.82x` | `9,177` | `-1.106` (`-1.072`) | **`0.00 bps`** |
| **`Dev 2025` (12h)** | **`venue_specific_residual`** | `close_t` | **`-$760.26`** | **`-$738.02`** | `$737.57` | `+$22.24` | **`-$1,475.59`** | **`-$1,313.73`** | `54.12x` | `8,260` | `-0.891` (`-0.874`) | **`0.00 bps`** |
| **`Dev 2025` (12h)** | **`venue_specific_residual`** | `next_bar_open_slippage` | **`-$760.26`** | **`-$735.98`** | `$816.31` | `+$24.28` | **`-$1,552.29`** | **`-$1,390.43`** | `54.12x` | `8,260` | `-0.941` (`-0.923`) | **`0.00 bps`** |
| **`Dev 2025` (12h)** | **`venue_specific_residual`** | `1h_delay` | **`-$1,155.43`** | **`-$1,129.38`** | `$726.22` | `+$26.05` | **`-$1,855.61`** | **`-$1,693.75`** | `54.09x` | `8,239` | `-1.122` (`-1.111`) | **`0.00 bps`** |
| **`Dev 2025` (4h)** | `raw_unadjusted` | `close_t` | `+$607.51` | `+$690.82` | `$3,269.48` | `+$83.31` | **`-$2,578.66`** | **`-$2,361.93`** | `239.92x` | `13,087` | `-1.050` (`-1.009`) | `3.25 bps` |
| **`Dev 2025` (4h)** | `raw_unadjusted` | `1h_delay` | `-$1,156.17` | `-$1,007.36` | `$3,061.29` | `+$148.81` | **`-$4,068.65`** | **`-$3,851.92`** | `239.83x` | `12,962` | `-2.066` (`-2.108`) | `—` |
| **`Dev 2025` (4h)** | **`quote_currency_adjusted`** | `close_t` | **`-$761.86`** | **`-$574.04`** | `$3,390.10` | `+$187.83` | **`-$3,964.14`** | **`-$3,741.59`** | `260.07x` | `13,390` | `-1.679` (`-1.636`) | **`0.00 bps`** |
| **`Dev 2025` (4h)** | **`quote_currency_adjusted`** | `1h_delay` | **`-$2,378.91`** | **`-$2,107.82`** | `$3,203.68` | `+$271.09` | **`-$5,311.50`** | **`-$5,088.95`** | `260.02x` | `13,285` | `-2.757` (`-2.781`) | **`0.00 bps`** |
| **`Dev 2025` (4h)** | **`venue_specific_residual`** | `close_t` | `+$372.33` | `+$418.42` | `$2,755.04` | `+$46.09` | **`-$2,336.62`** | **`-$2,143.00`** | `203.82x` | `12,533` | `-1.326` (`-1.294`) | **`2.57 bps`** |
| **`Dev 2025` (4h)** | **`venue_specific_residual`** | `1h_delay` | **`-$955.83`** | **`-$853.41`** | `$2,634.31` | `+$102.42` | **`-$3,487.72`** | **`-$3,294.10`** | `203.78x` | `12,484` | `-2.117` (`-2.047`) | **`0.00 bps`** |

### 5.2 Cost Break-Even Frontier in `Adaptive Research Development 2025` (`0 bps` to `22 bps` Round-Trip)

| Round-Trip Cost (bps) | `raw_unadjusted` 12h Net PnL (Net Excess vs Matched EW) | `quote_currency_adjusted` 12h Net PnL (Net Excess vs Matched EW) | `venue_specific_residual` 12h Net PnL (Net Excess vs Matched EW) | `raw_unadjusted` 4h Net PnL (Net Excess vs Matched EW) | `quote_currency_adjusted` 4h Net PnL (Net Excess vs Matched EW) | `venue_specific_residual` 4h Net PnL (Net Excess vs Matched EW) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`0.0 bps`** | `+$141.14` (`+$262.96`) | **`-$1,239.65` (`-$1,103.21`)** | **`-$760.26` (`-$643.50`)** | `+$607.51` (`+$767.05`) | **`-$761.86` (`-$597.72`)** | `+$372.33` (`+$513.70`) |
| **`2.0 bps`** | `+$14.47` (`+$142.96`) | `-$1,370.24` (`-$1,226.53`) | `-$864.11` (`-$740.90`) | `+$118.98` (`+$286.70`) | `-$1,255.75` (`-$1,083.25`) | `-$38.69` (`+$110.15`) |
| **`4.0 bps`** | `-$111.41` (`+$23.74`) | `-$1,499.94` (`-$1,348.96`) | `-$967.40` (`-$837.75`) | `-$357.99` (`-$182.09`) | `-$1,736.96` (`-$1,556.11`) | `-$441.44` (`-$285.13`) |
| **`6.0 bps`** | `-$236.49` (`-$94.68`) | `-$1,628.73` (`-$1,470.48`) | `-$1,070.14` (`-$934.04`) | `-$823.66` (`-$639.59`) | `-$2,205.84` (`-$2,016.65`) | `-$836.06` (`-$672.28`) |
| **`8.0 bps`** | `-$360.80` (`-$212.33`) | `-$1,756.63` (`-$1,591.11`) | `-$1,172.32` (`-$1,029.78`) | `-$1,278.31` (`-$1,086.07`) | `-$2,662.69` (`-$2,465.15`) | `-$1,222.73` (`-$1,051.49`) |
| **`10.0 bps`** | `-$484.32` (`-$329.19`) | `-$1,883.64` (`-$1,710.86`) | `-$1,273.96` (`-$1,124.98`) | `-$1,722.19` (`-$1,521.78`) | `-$3,107.82` (`-$2,901.94`) | `-$1,601.61` (`-$1,422.91`) |
| **`14.0 bps` (Canonical)** | **`-$729.05` (`-$560.61`)** | **`-$2,135.03` (`-$1,947.73`)** | **`-$1,475.59` (`-$1,313.73`)** | **`-$2,578.66` (`-$2,361.93`)** | **`-$3,964.14` (`-$3,741.59`)** | **`-$2,336.62` (`-$2,143.00`)** |
| **`18.0 bps`** | `-$970.73` (`-$788.99`) | `-$2,382.94` (`-$2,181.13`) | `-$1,675.06` (`-$1,500.33`) | `-$3,395.06` (`-$3,162.02`) | `-$4,777.08` (`-$4,537.88`) | `-$3,042.29` (`-$2,833.77`) |
| **`22.0 bps`** | `-$1,209.38` (`-$1,014.35`) | `-$2,627.42` (`-$2,411.11`) | `-$1,872.39` (`-$1,684.80`) | `-$4,173.24` (`-$3,923.90`) | `-$5,548.86` (`-$5,293.02`) | `-$3,719.80` (`-$3,496.39`) |

---

## 6. Phase E — Decision Gate & Governance Disposition

1. **Primary Decision Gate Outcome**: **`H_B_REJECTED_POST_COST`**
   - Removing the `USDT-USD` quote-currency basis (`r = 0.8527` with raw premium) eliminates the positive grossPnL that `raw_unadjusted` appeared to show in `2022–2023` (`12h`) and `2025` (`12h` and `4h`). Specifically, in `adaptive_research_dev_2025`, normalizing for `USDT-USD` shifts `12h` zero-friction gross PnL from `+$141.14` to **`-$1,239.65`** (`-$760.26` for `venue_specific_residual`) and `4h` zero-friction gross PnL from `+$607.51` to **`-$761.86`** (`+$372.33` for `venue_specific_residual`, which breaks even at just `2.57 bps` round-trip cost vs `14.0 bps` Spot Taker fees).
   - Moreover, under a `1h_delay` execution latency, even `raw_unadjusted` `4h` gross PnL in 2025 flips from `+$607.51` to **`-$1,156.17`** (`-$4,068.65` net PnL), proving that the residual cross-venue catch-up is a sub-hour microstructure effect that cannot survive Spot Taker fees or decision latency.
2. **Secondary Execution Data Disposition**: **`H_B_EXECUTION_DATA_INSUFFICIENT`**
   - Public historical archives for **Binance Spot** (`bookTicker`, `bookDepth`) and **Coinbase Exchange** (`book/history`) do not exist (`HTTP 404`), and candle closes cannot be treated as guaranteed L1 fill prices. A standalone research-only [`CrossVenueForwardRecorder`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_3/phase_cd_execution_and_falsification.py#L72-L193) has been implemented and verified for any future sub-second L1/L2 microstructure research without touching the canonical M1–M5 collector.
3. **Neural Training & Production Governance**:
   - **Bounded Neural Experiment Authorized**: **`False`** (No new neural network was trained in N1.3, and none is authorized on H-B).
   - **Frozen M5 Baseline**: `vol_aware_mean_reversion_v1` (ETH_USDT) remains untouched.
   - **Prospective Collector**: `STOPPED`
   - **Real Trading**: `DISABLED` (`real_orders = False`)

---

## 7. N1.4 Phase A Closure — Final Historical Research Rejection Seal

Per N1.4 Phase A, **N1.3 (`H-B` Cross-Venue Signal Identity & Executable Economic Edge)** is permanently closed in the **`HISTORICAL_RESEARCH_REJECTED`** state without rerun:

```text
H_B_POST_COST_DISPOSITION     = REJECTED
H_B_HISTORICAL_L1_EVIDENCE    = INSUFFICIENT
H_B_NEURAL_TRAINING           = NOT_JUSTIFIED
N1_N1_3_PRODUCTION_CANDIDATES = 0
PROSPECTIVE_COLLECTOR         = STOPPED
REAL_TRADING                  = DISABLED
```

1. **Quote currency contributed materially to raw premium**: `USDT-USD` exchange-rate basis drives `r = 0.8527` (`73.4%` of variance) of the raw `Coinbase USD / Binance USDT - 1` price premium (`raw std = 9.020 bps` vs `quote_adjusted std = 4.651 bps`).
2. **Quote-normalized 12h strategy failed even before fees**: In `adaptive_research_dev_2025`, normalizing for `USDT-USD` flips `12h` zero-friction counterfactual gross PnL from `+$141.14` to **`-$1,239.65`** (`-$760.26` for `venue_specific_residual`), with a `0.00 bps` cost break-even frontier.
3. **The 4h residual strategy did not clear execution costs**: While `venue_specific_residual` at `4h` produced `+$372.33` zero-friction gross PnL (`+$418.42` same-path gross PnL), it required `203.82x` annual turnover (`$2,755.04` friction at `14 bps` RT), yielding **`-$2,336.62` net PnL** and breaking even at only **`2.57 bps`** round-trip cost.
4. **One-hour delayed execution eliminated its remaining gross value**: Under `1h_delay` execution latency, `4h` `venue_specific_residual` gross PnL collapsed from `+$372.33` to **`-$955.83`** (`-$3,487.72` net PnL), and `raw_unadjusted` `4h` gross PnL collapsed from `+$607.51` to **`-$1,156.17`**.
5. **No new neural model was justified**: Because executable post-cost economic value is negative across all normalized variants and realistic latency/cost regimes, neural policy training on H-B is permanently rejected.
