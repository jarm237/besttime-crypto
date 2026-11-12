# N1.2 — Independent Alpha Mechanism Discovery Report

**Document ID**: `NEURAL-N1-2-ALPHA-MECHANISM-DISCOVERY-2026-11-11`  
**Status**: `COMPLETED — MECHANISMS EVALUATED ON FRESH TICK & CROSS-VENUE DATA`  
**Workspace**: `D:\Workspaces\besttime-crypto`  
**Research Package**: [`neural_trading/n1_2/`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_2/__init__.py)  
**Predecessor Closure**: [`docs/research/NEURAL_N1_1_ALPHA_ATTRIBUTION_AND_N2_FEASIBILITY.md`](file:///d:/Workspaces/besttime-crypto/docs/research/NEURAL_N1_1_ALPHA_ATTRIBUTION_AND_N2_FEASIBILITY.md)

---

## 1. Executive Summary & Phase A Closure Confirmation

Following the closure of **N1.1** (`N1_ECONOMIC_DISPOSITION = REJECTED_FOR_PRODUCTION_CANDIDACY`, `N1_H1_INCREMENTAL_VALUE = NOT_STABLE`, `N1_H2_DIRECTIONAL_VALUE = NOT_SUPPORTED`, `N2_ON_CURRENT_FEATURES = NOT_AUTHORIZED`), **Phase A** updated [`docs/research/NEURAL_N1_1_ALPHA_ATTRIBUTION_AND_N2_FEASIBILITY.md`](file:///d:/Workspaces/besttime-crypto/docs/research/NEURAL_N1_1_ALPHA_ATTRIBUTION_AND_N2_FEASIBILITY.md) without rerunning N1 training:
1. Assigned explicit canonical identities separating `N1_FOLD1_2022_ORIGINAL_REPORT_RUN` (`-$11,934.81` net PnL) from `N1_1_FOLD1_2022_AUDIT_TRACE_RUN` (`-$11,769.10` net PnL).
2. Fixed exact baseline references for all N1.1 Phase C ablations (`N1_1_FOLD1_2022_AUDIT_TRACE_RUN`, `N1_FOLD2_2024_CANONICAL_RUN`, `N1_FOLD3_2025_CANONICAL_RUN`).
3. Separated Carino timing contribution vs constant mean exposure ($\bar{E} \cdot \text{EW}$), Carino timing vs B&H exposure drift (`C2`), and total portfolio net PnL delta.

In **Phase B & Phase D**, we formulated and empirically tested two independent market-microstructure and cross-market hypotheses on **newly acquired, checksum-verified tick-by-tick and synchronized cross-venue datasets** (2022–2025, with 2022–2024 as discovery and 2025 as strict out-of-sample):
- **Hypothesis H-A (`H_A_PERSISTENT_TRADE_LEVEL_ORDER_FLOW_AND_LIQUIDITY_DISLOCATION`)**: Tick-by-tick Binance Spot `aggTrades` (`555,512,482` individual aggregated trades across `240` monthly archives, `8.30 GB` compressed, 100% SHA-256 verified) measuring institutional whale ($\ge \$25\text{k}$) vs retail ($< \$2\text{k}$) aggressor order flow, order-book sweep fragmentation (`last_trade_id - first_trade_id + 1`), continuation price impact asymmetry, and tick-level realized bid-ask bounce spread.
- **Hypothesis H-B (`H_B_CROSS_VENUE_COINBASE_AND_5M_PERP_SPOT_PRICE_DISCOVERY`)**:
  - **H-B1**: Synchronized **Coinbase Exchange USD Spot (`SYM-USD`)** vs **Binance USDT Spot (`SYMUSDT`)** (`267,029` Coinbase 1h candles across 8 major pairs, 2022–2025) measuring US fiat institutional price premium/discount and volume-share shocks relative to offshore USDT markets.
  - **H-B2**: High-frequency **5-minute (`5m`) Binance USD-M Perpetual vs 5-minute (`5m`) Binance Spot** (`768` monthly archives, `3,361,696` matched 5m bars across 8 pairs, 100% SHA-256 verified) measuring intraday basis velocity and last-15-minute perpetual-vs-spot aggressor lead-lag.

---

## 2. Phase B — Candidate Alpha Mechanisms & Selection Rationale

| Mechanism ID | Market Microstructure / Economic Rationale | Required Raw Observation Granularity | Authoritative Source Availability (2022–2025) | Phase B Selection Status |
| :--- | :--- | :--- | :--- | :--- |
| **H-A: Tick-Level Order-Flow & Sweep Fragmentation** | 1h klines conflate one $\$250\text{k}$ institutional sweep with 500 retail $\$500$ trades and hide how many resting limit orders were consumed (`last_trade_id - first_trade_id + 1`). Tick-by-tick `aggTrades` separate whale vs retail aggressor flow, multi-fill book sweeps, and tick-level price impact asymmetry. | Individual timestamped `aggTrades` (`agg_id, price, qty, first_id, last_id, ts, is_buyer_maker`) | **100% Available & Verified** (`data.binance.vision/data/spot/monthly/aggTrades`, 240 zips + `.CHECKSUM`) | **SELECTED (Direction 1)** |
| **H-B1: Cross-Venue Fiat USD (Coinbase) vs Offshore USDT (Binance) Price Discovery** | Regulated US fiat USD ramps (`Coinbase Exchange`) experience institutional fiat inflows/outflows that temporarily dislocate `SYM-USD` prices and volume share relative to offshore `SYMUSDT` Spot bars before cross-venue arbitrage closes the gap. | Synchronized 1h OHLCV + USD notional across `Coinbase SYM-USD` and `Binance SYMUSDT` | **100% Available & Verified** (`api.exchange.coinbase.com` REST archives + `data.binance.vision`, 8 pairs, 2022–2025) | **SELECTED (Direction 2A)** |
| **H-B2: 5-Minute (`5m`) Perpetual vs Spot Intraday Lead-Lag** | Leveraged news/informed flow executes first in liquid USD-M Perpetual futures. Intraday 5m basis velocity and last-15m perpetual taker imbalance lead subsequent Spot returns. | Synchronized `5m` USD-M Perpetual klines + taker buy volume vs `5m` Spot klines | **100% Available & Verified** (`data.binance.vision` `5m` monthly archives, 768 zips + `.CHECKSUM`) | **SELECTED (Direction 2B)** |
| **H-C: Top-of-Book L1 Quote Imbalance (`bookTicker`) & Forced Liquidations (`allForceOrders`)** | High-frequency L1 bid-ask size imbalance and forced liquidation cascades. | Tick L1 `bookTicker` and liquidation stream | **UNAVAILABLE (`HTTP 404`)** on `data.binance.vision` & public API (see [`n1_2_rejected_sources_probe.json`](file:///d:/Workspaces/besttime-crypto/research/neural_n1_2/manifests/n1_2_rejected_sources_probe.json)) | **REJECTED AT SOURCE AUDIT (No Fabrication Allowed)** |

---

## 3. Phase D — Empirical Microstructure & Causal Information Discovery (`t -> t+H`)

All features and targets are constructed strictly causally in [`neural_trading/n1_2/discovery.py`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_2/discovery.py) and evaluated in [`research/neural_n1_2/n1_2_phase_d_discovery_results.json`](file:///d:/Workspaces/besttime-crypto/research/neural_n1_2/n1_2_phase_d_discovery_results.json).

### 3.1 H-A Tick-by-Tick Microstructure Summary (`555,512,482` AggTrades, 2022–2025)

| Symbol | Hours Covered | Raw `aggTrades` Processed | Underlying Resting Limit Orders Swept (`\sum (last\_id - first\_id + 1)`) | Mean Resting Orders Swept per `aggTrade` | Median Realized Bid-Ask Bounce Spread (bps) | P90 Realized Bounce Spread (bps) | Whale ($\ge \$25\text{k}$) Volume Share | Retail ($< \$2\text{k}$) Volume Share |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `ADAUSDT` | 35,062 | 176,782,785 | 405,927,232 | 2.2962 | 1.742 bps | 3.437 bps | 10.23% | 32.00% |
| `ETCUSDT` | 35,062 | 62,311,830 | 128,289,713 | 2.0588 | 2.706 bps | 4.320 bps | 7.18% | 37.66% |
| `LINKUSDT` | 35,062 | 125,501,062 | 267,014,799 | 2.1276 | 1.905 bps | 6.850 bps | 12.67% | 34.45% |
| `TRXUSDT` | 35,062 | 130,204,629 | 222,064,567 | 1.7055 | 1.435 bps | 4.278 bps | 22.29% | 28.15% |
| `XLMUSDT` | 35,062 | 60,712,176 | 147,996,454 | 2.4377 | 5.991 bps | 9.600 bps | 5.11% | 44.89% |
| **Total / Mean** | **175,310** | **555,512,482** | **1,171,292,765** | **2.1085** | **2.756 bps** | **5.697 bps** | **11.50%** | **35.43%** |

> [!IMPORTANT]
> **Why Tick-by-Tick `aggTrades` Differ Fundamentally from 1h Klines**:
> Across the 555.5 million `aggTrades`, `1,171,292,765` individual resting limit orders were swept (`2.11` resting limit orders per `aggTrade`), and institutional whale trades ($\ge \$25\text{k}$) account for only `5.11%` (`XLMUSDT`) to `22.29%` (`TRXUSDT`) of total volume while retail trades ($< \$2\text{k}$) account for `28.15%` to `44.89%`. Furthermore, tick-to-tick buyer/seller flip prices reveal an additional realized bid-ask bounce spread of `1.44 bps` to `5.99 bps` (reaching `3.44 bps` to `9.60 bps` at P90) on top of exchange taker fees.

### 3.2 Separation of Directional Return Prediction across Horizons ($H \in \{1\text{h}, 4\text{h}, 12\text{h}, 24\text{h}\}$)

| Hypothesis / Feature | 1h Discovery IC ($t$-stat) | 4h Discovery IC ($t$-stat) | 12h Discovery IC ($t$-stat) | 24h Discovery IC ($t$-stat) | 1h OOS 2025 IC ($t$-stat) | 12h OOS 2025 IC ($t$-stat) | Sign Stability (Years $+$/4 at 1h) | Dominant Economic Mechanism Discovered |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **H-A: `ha_multifill_ofi`** (Multi-fill sweep $\ge 3$ orders) | **-0.02272 (-7.57)** | **-0.03566 (-5.68)** | **-0.03879 (-3.70)** | -0.00239 (-0.15) | **-0.01114 (-2.18)** | -0.01099 (-0.59) | 0/4 (4/4 negative) | **Short-horizon liquidity exhaustion / post-sweep mean reversion** |
| **H-A: `ha_whale_ofi`** (Whale $\ge \$25\text{k}$ signed flow) | **-0.01477 (-4.98)** | **-0.02614 (-4.23)** | **-0.03137 (-2.85)** | -0.02895 (-1.84) | -0.00648 (-1.25) | -0.01992 (-1.04) | 0/4 (4/4 negative) | **Post-whale sweep mean reversion (strong in 2022–2023, decays by 70% in 2024–2025)** |
| **H-A: `ha_whale_minus_retail`** (Whale vs Retail divergence) | **-0.01408 (-4.74)** | **-0.02614 (-4.40)** | **-0.03069 (-2.81)** | -0.01931 (-1.32) | **-0.01404 (-2.66)** | -0.01911 (-1.04) | 0/4 (4/4 negative) | **Contrarian reversion at 1h–12h across all 4 years** |
| **H-A: `ha_impact_asymmetry`** (Buy vs Sell tick impact) | **-0.01380 (-4.81)** | **-0.01562 (-2.48)** | **-0.02195 (-2.06)** | -0.00456 (-0.30) | **-0.01084 (-2.14)** | -0.01558 (-0.82) | 0/4 (4/4 negative) | **Illiquidity price pressure reversion** |
| **H-A: `ha_signed_sweep_imb`** (Order-count sweep imbalance) | -0.00062 (-0.21) | -0.00421 (-0.66) | +0.00692 (+0.65) | +0.01137 (+0.74) | +0.00448 (+0.82) | +0.03062 (+1.74) | 2/4 (sign flip) | **Regime-unstable (negative 2022–2023, positive 2024–2025)** |
| **H-B1: `hb1_cb_premium_dev_z`** (Coinbase USD vs Binance USDT price premium) | **+0.03419 (+14.59)** | **+0.02454 (+5.08)** | **+0.02582 (+3.22)** | +0.01735 (+1.46) | **+0.02553 (+6.30)** | -0.00065 (-0.05) | **4/4 positive** | **Genuine cross-venue price discovery lead (Coinbase USD leads Binance USDT at 1h–4h, decays by 12h in 2025)** |
| **H-B1: `hb1_cb_minus_bn_ret_z`** (Coinbase minus Binance 1h return) | **+0.02692 (+10.85)** | **+0.01759 (+3.61)** | +0.01126 (+1.41) | +0.02117 (+1.83) | **+0.01506 (+3.60)** | -0.00516 (-0.38) | **4/4 positive** | **Fast cross-venue return catch-up within 1h–4h** |
| **H-B1: `hb1_cb_signed_vol_shock`** (Coinbase USD volume-share shock) | **+0.00765 (+3.29)** | +0.00033 (+0.07) | +0.00345 (+0.42) | +0.00214 (+0.20) | +0.00410 (+0.96) | **-0.04651 (-3.27)** | 4/4 at 1h (flips at 12h) | **1h continuation followed by 12h reversal in 2025** |
| **H-B2: `hb2_last15m_perp_lead_z`** (Last-15m 5m Perp minus Spot return) | **+0.01073 (+4.42)** | +0.00767 (+1.62) | -0.00845 (-0.99) | -0.00988 (-0.84) | +0.00639 (+1.69) | +0.00153 (+0.11) | **4/4 positive at 1h** | **Very short-lived 1h perp-to-spot lead; zero edge at $\ge 4\text{h}$** |
| **H-B2: `hb2_basis_change_z`** (Intraday 5m basis velocity) | +0.00374 (+1.59) | +0.00830 (+1.80) | +0.00325 (+0.39) | -0.01465 (-1.19) | **+0.01123 (+2.76)** | +0.00416 (+0.28) | **4/4 positive at 1h** | **Weak 1h–4h basis momentum, noisy at 12h–24h** |

### 3.3 Separation of Directional Prediction vs Volatility Prediction vs Liquidity/Spread Prediction

Per Phase D rules, we explicitly separated directional return prediction from forward 4h volatility (`fwd_vol_4h`) and forward 4h liquidity/spread dislocation (`fwd_spread_4h`):

| Feature | Directional Return IC (4h Discovery $t$-stat) | Cross-Sectional Volatility IC (`fwd_vol_4h` $t$-stat) | Time-Series $|\text{Feature}| \to \text{fwd\_vol\_4h}$ Mean Corr | Cross-Sectional Spread/Liquidity IC (`fwd_spread_4h` $t$-stat) | Time-Series $|\text{Feature}| \to \text{fwd\_spread\_4h}$ Mean Corr | Primary Information Channel |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| `ha_whale_ofi` | -0.02614 (-4.23) | +0.01317 (+2.10) | +0.01443 | **+0.03308 (+5.11)** | -0.02399 | **Cross-sectional spread widening & short-term mean reversion** |
| `ha_multifill_ofi` | -0.03566 (-5.68) | **+0.01590 (+2.50)** | -0.03046 | +0.00355 (+0.52) | +0.01080 | **Short-term sweep exhaustion reversion + cross-sectional vol** |
| `ha_sweep_intensity_z` | +0.00242 (+0.40) | +0.01577 (+1.92) | +0.00880 | +0.00530 (+0.51) | **+0.01968** (5/5 assets $+$) | **Pure microstructure activity / spread predictor (non-directional)** |
| `hb1_cb_premium_dev_z` | **+0.02454 (+5.08)** | +0.00808 (+1.53) | +0.00054 | +0.00491 (+0.85) | -0.01975 | **Directional cross-venue price catch-up (1h–4h)** |
| `hb1_cb_signed_vol_shock` | +0.00033 (+0.07) | -0.00872 (-1.82) | **+0.10362** (7/8 assets $> +0.10$) | -0.00587 (-1.16) | **+0.05670** (ex-XRP) | **Time-series volatility & basis-dispersion trigger, NOT persistent direction** |
| `hb2_basis_change_z` | +0.00830 (+1.80) | -0.00190 (-0.42) | +0.01416 | -0.00094 (-0.20) | **+0.03307** (8/8 assets $+$) | **Time-series basis dispersion / liquidity stress predictor** |

---

## 4. Crucial Phase D Finding: Why High Statistical $t$-Stats Fail the Spot Long-Only Friction Hurdle

Phase D uncovers two genuine, statistically indisputable market microstructure phenomena:
1. **In H-A (Tick-by-Tick `aggTrades`)**: Aggressive multi-fill book sweeps (`ha_multifill_ofi`, $t = -7.57$ at 1h, $t = -5.68$ at 4h) and whale imbalances (`ha_whale_ofi`, $t = -4.98$ at 1h) do **not** produce momentum; instead, they reflect temporary order-book depletion that mean-reverts over the next 1h–12h across all 5 assets (`ADA, ETC, LINK, TRX, XLM`). However, the strength of this mean reversion decays by more than **65% from 2022–2023 to 2024–2025** (`ha_composite_score` 12h IC drops from `-0.04588` in 2022 to `-0.00904` in 2024 and `+0.00075` in 2025).
2. **In H-B (Cross-Venue Coinbase USD vs Binance USDT & 5m Perp Lead-Lag)**: When Coinbase `SYM-USD` trades at a positive return/premium relative to Binance `SYMUSDT` (`hb1_cb_premium_dev_z`, $t = +14.59$ at 1h, $t = +6.30$ in OOS 2025) or 5m Perpetuals lead Spot in the last 15 minutes of the hour (`hb2_last15m_perp_lead_z`, $t = +4.42$ at 1h), Binance Spot reliably catches up over the next **1h to 4h** across **all 8 assets** and **all 4 years (2022–2025)**.

**However, when translated into an implementable Spot Long-Only strategy on Binance (`14 bps` round-trip fee/slippage + `1.4 to 6.0 bps` realized bid-ask bounce spread)**:
- The cross-venue and 5m lead-lag signals have a **half-life of 1h to 4h**. In OOS 2025, `hb1_cb_premium_dev_z` has a strong 1h IC of `+0.02553` ($t = +6.30$), a weak 4h IC of `+0.00778` ($t = +0.90$), and **zero 12h IC (`-0.00065`, $t = -0.05$)**.
- Capturing a 1h–4h signal requires rebalancing every 4h–12h (`63x` to `255x` annualized turnover), which incurs **`$869` to `$3,659` in realized execution friction** on a `$20,000` portfolio (`4.3%` to `18.3%` annual drag), completely consuming the `+0.71%` to `+3.04%` gross implementable edge in OOS 2025.
- Conversely, slowing the rebalance horizon to 12h–24h reduces turnover, but by 12h the cross-venue price discovery gap has already been arbitraged away by low-latency market makers.

---

## 5. N1.3 Phase A1 Closure — Exact `aggTrades` Microstructure Semantics & Feature Renaming

Per N1.3 Phase A1, without rerunning H-A research (which remains `REJECTED_POST_COST`), we formally separate the four microstructure quantities and update the canonical feature names in [`neural_trading/n1_3/phase_a_reconciliation.py`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_3/phase_a_reconciliation.py):

1. **Four Distinct Microstructure Quantities**:
   - `aggregate_trade_events` (`count(agg_trade_id)`): Number of rows in the Binance `aggTrades` stream (`555,512,482` rows). Each row aggregates fills from a single taker order at the **same price** and within the **same timestamp unit**.
   - `underlying_execution_matches` (`sum(last_trade_id - first_trade_id + 1)`): Number of individual matching-engine fill events (`trade_id`s) compressed into an `aggTrade` row at that **single price level** (`1,171,292,765` matches, or `2.1085` matches per `aggTrade`). This must **not** be called the count of unique resting limit orders or multi-price-level sweeps.
   - `unique_resting_orders` (`count(distinct maker_order_id)`): True count of distinct resting limit orders on the book. **Unobservable** from `aggTrades` alone because `maker_order_id` is omitted, a single resting order can be partially filled across multiple timestamps, or iceberg/self-trade-prevention splits can generate multiple `trade_id`s.
   - `multi_price_level_sweeps` (`ts_k == ts_{k-1}`, `sign_k == sign_{k-1}`, $p_k \ne p_{k-1}$): A single aggressive order walking across multiple distinct price levels. Because Binance `aggTrades` splits into a new row whenever execution price changes, a multi-price-level sweep spans **multiple consecutive `aggTrade` rows**, whereas `last_trade_id - first_trade_id + 1` within one row measures **same-price match fragmentation**.

2. **Canonical Feature Rename Mapping (`FEATURE_RENAME_MAP_N1_2_TO_N1_3`)**:
   - `underlying_order_count` $\to$ `underlying_execution_match_count`
   - `buy_sweep_orders` $\to$ `buy_same_price_execution_matches`
   - `sell_sweep_orders` $\to$ `sell_same_price_execution_matches`
   - `ha_sweep_intensity_raw` / `ha_sweep_intensity_z` $\to$ `ha_same_price_match_fragmentation_raw` / `ha_same_price_match_fragmentation_z`
   - `ha_signed_sweep_imb_raw` / `ha_signed_sweep_imb` $\to$ `ha_signed_match_fragmentation_imb_raw` / `ha_signed_match_fragmentation_imb`
   - `ha_multifill_ofi_raw` / `ha_multifill_ofi` $\to$ `ha_multimatch_same_price_ofi_raw` / `ha_multimatch_same_price_ofi`
