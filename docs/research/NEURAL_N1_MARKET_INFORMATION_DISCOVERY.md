# NEURAL N1 — Independent Market Information Discovery & Hypothesis Specification

**Date**: 2026-11-11  
**Workspace**: `D:\Workspaces\besttime-crypto`  
**Research Namespace**: `neural_trading/n1/`  
**Phase Scope**: Phase A Closure & Phase B Independent Market Information Hypotheses

---

## 1. Phase A — Closure of N0.3 Without Reopening Research

Before opening N1, the economic attribution and conclusions of `docs/research/NEURAL_N0_3_DECISION_HORIZON_AND_POLICY_LEARNING.md` (and two unsupported narrative statements in N0.2) were corrected directly in-place without retraining N0.3:

```text
Neural gross PnL       = -3112.94
Passive gross PnL      = -3106.84
Gross excess           = -6.10

Neural friction        = 490.70
Passive friction       = 10.30
Incremental friction   = 480.40

Net excess             = -486.50
```

- **Disposition**: `REJECTED_FOR_PRODUCTION_CANDIDACY` (unchanged).
- **Corrected Scope of Conclusion**: The negative N0–N0.3 outcome applies strictly to the specific 4-channel close-to-close return representation (`1h`, `4h`, `12h`, `24h` log returns over a 48-hour window on 5 Binance Spot pairs, evaluated on a reused 2025 development path). It does **not** establish that Spot OHLCV data as a whole—which also records traded volume, quote volume, trade counts, taker buy base/quote volumes, and intrabar range structure—or cross-sectional multi-asset relationships lack predictive value.

---

## 2. Prior Repository Evidence & Governance Boundaries (HMR-V4A / V4B / V4C)

To avoid silently recycling rejected features under new names, we audited the prior `research/historical_market_replay_v4/` archive before formulating N1 hypotheses:

| Prior Program | Information Family | Source | Prior Verdict | Governance Rule for N1 |
| :--- | :--- | :--- | :--- | :--- |
| `HMR-V4A-1` | Perpetual Funding Rate (`funding_level`, deltas, z-scores) | Binance USD-M Funding | **REJECT** (unstable across periods; Period C negative) | Excluded from N1 training. |
| `HMR-V4B-1` | Open Interest (`binance_open_interest`) | Binance USD-M OI | **BLOCKED_PROVENANCE** (`historical_start = null` in public archive) | Excluded; no multi-year raw archive on `data.binance.vision`. |
| `HMR-V4B-2B` | Perpetual-Spot Premium Index (`perp_premium_*`) | Binance `premiumIndexKlines` | **REJECT_NO_ECONOMIC_INFORMATION** (max spread 0.67 bps < cost floor) | Excluded from N1 acquisition. |
| `HMR-V4B-3A` | Forced Liquidations (`liquidationSnapshot`) | Binance USD-M Liquidations | **REJECT_INCOMPLETE_LIQUIDATION_OBSERVABILITY** (archive 404 after 2024-03-31; 1s stream throttling) | Excluded; verified 404 on `data.binance.vision`. |
| `HMR-V4B-4B` | Single-Asset UM Taker Flow (`TF1..TF5`) | Binance USD-M `aggTrades` | **REJECT_NO_ECONOMIC_INFORMATION** (raw spread ≤ 0.73 bps; 0.00 bps conditioned) | Single-asset perpetual directional flow rejected; not reused. |
| `HMR-V4C-1B` | Daily Macro Risk (`VIX`, `SPX`, `DXY`, `US10Y`) | TradFi Daily Close | **REJECT_NO_ECONOMIC_INFORMATION** (0.00 bps conditioned spread) | Excluded. |

---

## 3. Systematic Evaluation of Candidate Market Information Families

Every candidate family is evaluated against the seven mandatory Phase B criteria:
1. **Economic / Microstructural Mechanism** (why it may precede price or risk changes)
2. **Appropriate Prediction Horizon**
3. **Exploitable Trading Action**
4. **Authoritative Raw Historical Data Source**
5. **Historical Point-in-Time (PIT) Limitations**
6. **Execution Cost & Liquidity Assumptions**
7. **Falsification Protocol**

---

### Family 1 — Cross-Sectional Market Structure & Spot Aggressor Volume/Range Dispersion *(Selected as Hypothesis H1)*

1. **Mechanism**:
   - In crypto spot markets, retail and institutional capital rotates across large-cap pairs unevenly, while market-wide deleveraging events cause sudden spikes in **cross-sectional return dispersion**, **market breadth collapse** (fraction of assets advancing with positive taker buy imbalance), and **volume-weighted BTC/ETH leadership vs altcoin lag**.
   - Furthermore, raw Spot klines contain three microstructure observables that N0–N0.3 discarded completely:
     - **Spot Taker Buy Imbalance**: $I_{i,t}^{\text{spot}} = \frac{2 \cdot V_{i,t}^{\text{taker\_buy\_quote}} - V_{i,t}^{\text{quote}}}{V_{i,t}^{\text{quote}}}$, measuring net aggressive buyer vs seller pressure settled in spot USDT (without perpetual leverage distortion).
     - **Trade Participation Shock**: log ratio of trade count $N_{i,t}^{\text{trades}}$ and average trade size $V_{i,t}^{\text{quote}} / N_{i,t}^{\text{trades}}$ relative to trailing 7-day baseline, separating whale-driven institutional accumulation from fragmented retail churn.
     - **Intrabar Range & Parkinson Volatility Expansion**: $\ln(H_{i,t}/L_{i,t})$ and upper/lower shadow asymmetry $\frac{(C_{i,t} - L_{i,t}) - (H_{i,t} - C_{i,t})}{H_{i,t} - L_{i,t}}$, capturing intrabar rejection of highs/lows.
   - Across a broad multi-asset cross-section (13 pairs spanning 2018–2025, including delisted `EOSUSDT`), cross-sectional breadth and aggressor dispersion can signal both **(a) aggregate market crash risk** (when to move portfolio weight into Cash) and **(b) relative cross-sectional continuation/reversal** (which assets to overweight).
2. **Prediction Horizon**:
   - **12h to 24h** portfolio holding horizon (observed at 1h close boundaries, executed on multi-hour horizons so turnover remains bounded relative to 14 bps round-trip spot costs).
3. **Trading Action**:
   - **Market Exposure Scaling (Cash vs Risky Basket)**: Increase Cash allocation when cross-sectional breadth collapses, cross-sectional dispersion spikes with negative spot aggressor flow, or Parkinson volatility expands downward.
   - **Cross-Sectional Tilting**: Overweight liquid pairs exhibiting strong relative spot aggressor accumulation and low downside tail volatility; HOLD when expected incremental return is smaller than the 14 bps round-trip cost hurdle.
4. **Authoritative Raw Source**:
   - Official Binance public archive: `https://data.binance.vision/data/spot/monthly/klines/<SYMBOL>/1h/<SYMBOL>-1h-<YYYY-MM>.zip` with companion `.CHECKSUM` (SHA-256) files.
   - Multi-regime span: **2017-08 through 2025-12** across 13 Spot USDT pairs (`BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `LTCUSDT`, `ADAUSDT`, `XRPUSDT`, `EOSUSDT` [delisted in 2025, included to reduce survivorship bias], `XLMUSDT`, `TRXUSDT`, `ETCUSDT`, `LINKUSDT`, `DOGEUSDT`, `SOLUSDT`).
5. **Historical PIT Limitations**:
   - A 1h kline with `open_time` $t_0$ and `close_time` $t_0 + 3599999\text{ ms}$ is strictly final only at $t_{\text{avail}} = t_0 + 1\text{h}$. No feature from bar $t_0$ may be used before $t_0 + 1\text{h}$.
   - Different assets list at different dates (e.g., `BTCUSDT` 2017-08, `SOLUSDT` 2020-08) and `EOSUSDT` ceases spot trading in May 2025. Cross-sectional statistics at time $t$ must be computed **only over the active eligible set $\mathcal{U}_t$** that has both a valid bar at $t$ and trailing lookback history, with inactive assets masked out of the portfolio simplex.
   - Residual survivorship limitation: while `EOSUSDT` is included, the 13-pair list was still chosen with knowledge of which major pairs existed on Binance by 2020.
6. **Execution Cost & Liquidity Assumptions**:
   - Spot execution at 7 bps per leg (5 bps fee + 1 bps slippage + 1 bps half-spread = **14 bps round-trip** baseline; **28 bps round-trip** stress).
   - Minimum trade notional filter and position concentration cap (max 35% per asset, min 5% Cash).
7. **Falsification Protocol**:
   - **Phase D Gate**: On chronological pre-2025 development folds (2018–2020, 2021–2022, 2023–2024), test whether H1 features produce:
     1. Statistically and economically meaningful conditional forward return spreads (Q5 − Q1) or downside risk/drawdown reduction at 12h/24h horizons that survive block-bootstrap confidence intervals and multiple-testing correction (Benjamini–Hochberg FDR $\le 0.10$), **and**
     2. Positive net economic value after deducting implied turnover $\times$ 7 bps/leg.
   - If neither directional excess return nor risk-adjusted drawdown reduction clears the cost hurdle across development regimes, **falsify and reject H1**.

---

### Family 2 — Order-Book Depth Asymmetry & Liquidity Thinning *(Selected as Hypothesis H2)*

1. **Mechanism**:
   - Limit order book depth within $\pm 1\%$ to $\pm 5\%$ of mid-price measures the resting liquidity supply available to absorb market orders:
     - **Depth Imbalance**: $D_{i,t}^{(k\%)} = \frac{\text{Notional}_{+k\%, i, t} - \text{Notional}_{-k\%, i, t}}{\text{Notional}_{+k\%, i, t} + \text{Notional}_{-k\%, i, t}}$ (or bid-minus-ask depth asymmetry $\frac{B_{k\%} - A_{k\%}}{B_{k\%} + A_{k\%}}$ where $-k\%$ is bid support below mid and $+k\%$ is ask resistance above mid).
     - **Near-Touch vs Deep-Book Slope**: ratio of $\pm 1\%$ notional depth to $\pm 5\%$ notional depth, measuring whether market makers are pulling quotes away from the touch.
     - **Liquidity Thinning Shock**: z-score of total $\pm 1\%$ depth relative to trailing 7-day rolling depth.
   - When resting bid support ($-1\%$) thins sharply or ask resistance ($+1\%$) stacks heavily relative to bid depth, subsequent market sell orders cause disproportionate downward price slippage and volatility cascades.
2. **Prediction Horizon**:
   - **4h to 12h** for both directional return skew and realized volatility / downside tail risk prediction.
3. **Trading Action**:
   - Reduce risky exposure (shift to Cash) when total near-touch depth thins or bid-vs-ask depth asymmetry turns strongly negative; scale into BTC/ETH when bid support thickens and depth slope normalizes.
4. **Authoritative Raw Source**:
   - Official Binance public archive: `https://data.binance.vision/data/futures/um/daily/bookDepth/<SYMBOL>/<SYMBOL>-bookDepth-<YYYY-MM-DD>.zip` with companion `.CHECKSUM` files.
   - Raw snapshots record `timestamp` (~30-second interval), `percentage` ($\in \{-5, -4, -3, -2, -1, +1, +2, +3, +4, +5\}$), `depth` (base units), and `notional` (USDT).
   - **Never tested in HMR-V4A/V4B/V4C**.
5. **Historical PIT Limitations**:
   - **Coverage Start Limitation**: Probing `data.binance.vision` confirmed that `bookDepth` starts on **2023-01-01** (`2022-12-31` returns HTTP 404). Thus H2 covers 2023-01-01 to 2025-12-31 (3 years), whereas H1 covers 2017-08 to 2025-12 (8+ years).
   - **Cross-Venue Observability**: `bookDepth` is published for Binance USD-M perpetual order books, whereas N1 portfolio execution is Spot. It is treated strictly as an exogenous liquidity state variable for `BTCUSDT` and `ETHUSDT`.
   - **Aggregation PIT Rule**: All ~30-second snapshots with timestamp $\tau \in [t_0, t_0 + 1\text{h})$ are aggregated into an hourly summary available strictly at $t_0 + 1\text{h}$ (last snapshot before hour close, intra-hour mean imbalance, intra-hour depth minimum).
6. **Execution Cost & Liquidity Assumptions**:
   - Evaluated against 14 bps round-trip (baseline) and 28 bps round-trip (stress) Spot execution costs. Because order-book imbalance often mean-reverts quickly, turnover required to trade it is a primary risk and is measured explicitly in Phase D.
7. **Falsification Protocol**:
   - Test on 2023–2024 development segments (H1 2023, H2 2023, H1 2024, H2 2024) across `BTCUSDT` and `ETHUSDT`:
     1. Does depth asymmetry or depth thinning predict conditional forward returns (4h, 12h, 24h), downside semi-deviation, or realized volatility beyond trailing spot volatility?
     2. Given the autocorrelation decay of depth imbalance, is the implied turnover low enough for net return after 14 bps round-trip cost to remain positive?
   - If the conditional return spread is smaller than the turnover-adjusted transaction cost or unstable across 2023 vs 2024 segments, **falsify H2 for directional trading** (and test whether its volatility/tail-risk signal adds value solely as a slow exposure filter).

---

### Family 3 — Spot/Perpetual Basis & Derivatives Positioning *(Evaluated, Not Selected for Fresh Acquisition)*

1. **Mechanism**: Deviations between perpetual futures price and spot index price reflect leveraged demand imbalance and arbitrage capital constraints.
2. **Horizon**: 8h–48h.
3. **Action**: Basis convergence or regime de-risking when basis is extreme.
4. **Raw Source**: Binance `premiumIndexKlines` (`data/futures/um/monthly/premiumIndexKlines/`).
5. **PIT Limitations**: High PIT quality (1h bars from 2020-01), but already audited in `HMR-V4B-2B-r1`.
6. **Cost Hurdle**: In `HMR-V4B-2B-r1`, the maximum conditioned return spread across 8h, 18h, and 48h horizons was **0.67 bps**—less than 5% of a single 14 bps round-trip cost.
7. **Falsification / Disposition**: **Already falsified in `HMR-V4B-2B-r1`** (`REJECT_NO_ECONOMIC_INFORMATION`). Per Phase C governance rules, not recycled into N1.

---

### Family 4 — Open Interest, Funding Schedules & Liquidation Events *(Evaluated, Not Selected)*

1. **Mechanism**: Crowded leveraged positioning (high OI + extreme funding) creates vulnerability to forced liquidation cascades.
2. **Horizon**: 4h–24h.
3. **Action**: Contrarian de-risking or post-liquidation reversal entry.
4. **Raw Source**: Binance USD-M funding rate history, OI metrics, and `liquidationSnapshot`.
5. **PIT & Archive Limitations**:
   - Funding rates (`HMR-V4A-1`) failed cross-period stability (Period C spread was negative for all 5 funding features).
   - Liquidation snapshots (`HMR-V4B-3A`) return **HTTP 404 after 2024-03-31** on `data.binance.vision` and suffer from 1-second WebSocket throttling (only 1 order per second pushed).
   - Open Interest (`HMR-V4B-1`) is blocked on historical archive provenance.
6. **Cost Hurdle**: High-frequency liquidation spikes require sub-hour execution with high slippage during cascades.
7. **Falsification / Disposition**: **Excluded per Phase C governance rule** ("Funding/OI rejected in HMR-V4A are not automatically permitted into ML training; do not synthesize liquidation events from OHLCV").

---

### Family 5 — Tick-Level Spot Trades (`aggTrades`) *(Evaluated, Subsumed at 1h by H1)*

1. **Mechanism**: Signed trade-by-trade order flow toxicity (VPIN, Kyle's lambda, large print bursts).
2. **Horizon**: 5m–4h.
3. **Action**: Short-horizon execution timing or market-making inventory skew.
4. **Raw Source**: `data.binance.vision/data/spot/monthly/aggTrades/` (~567 MB per single symbol-month; >300 GB across universe).
5. **PIT Limitations**: Exact millisecond timestamps, but hourly taker buy base/quote volumes and trade counts are **already exact sufficient statistics of 1h signed trade flow** and are included directly in the Spot 1h kline archive (columns 8, 9, 10). Furthermore, 15m directional taker flow was already rejected in `HMR-V4B-4B` (0.00 bps conditioned spread against a 14 bps cost hurdle).
6. **Cost Hurdle**: At 14 bps round-trip taker cost, sub-hour directional churn is economically unviable.
7. **Falsification / Disposition**: Exact 1h aggressor buy notional and trade counts are tested inside **H1** across 2017–2025; multi-hundred-GB tick downloads for sub-hour churn are not pursued.

---

### Family 6 — Macro / News Events with Historical Publication Timestamps *(Evaluated, Not Selected)*

1. **Mechanism**: Scheduled macro releases (CPI, FOMC, NFP) and regulatory/ETF announcements shift institutional risk appetite.
2. **Horizon**: 1d–10d.
3. **Action**: Pre-event volatility de-risking or post-announcement drift.
4. **Raw Source**: ALFRED / FRED vintage macro releases and SEC EDGAR / news wires.
5. **PIT Limitations**: Free public news archives rarely preserve exact second-level first-publication timestamps without survivorship or backfill edits; slow daily macro indicators (`VIX`, `SPX`, `DXY`, `US10Y`) were already tested in `HMR-V4C-1B` and yielded 0.00 bps conditioned spread.
6. **Cost Hurdle**: Low turnover, but low sample size of discrete macro events per year leads to high estimation variance.
7. **Falsification / Disposition**: Not selected for N1 initial acquisition; H1 and H2 provide far higher verifiable PIT density from official exchange archives.

---

## 4. Summary of Selected Hypotheses for Phase C & Phase D

| ID | Selected Hypothesis | Raw Authoritative Source | Symbols | Time Span | Core Observables Tested |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **H1** | **Cross-Sectional Market Structure, Spot Aggressor Imbalance & Range/Participation Dispersion** | `data.binance.vision/data/spot/monthly/klines/<SYM>/1h/` (+ SHA-256 `.CHECKSUM`) | 13 Spot USDT pairs (incl. delisted `EOSUSDT`) | **2017-08 to 2025-12** (8.3 years, multi-regime) | Cross-sectional return dispersion, market breadth, spot taker-buy imbalance, trade-size shock, Parkinson/Garman-Klass vol, shadow asymmetry, relative momentum vs beta |
| **H2** | **Order-Book Depth Asymmetry & Near-Touch Liquidity Thinning** | `data.binance.vision/data/futures/um/daily/bookDepth/<SYM>/` (+ SHA-256 `.CHECKSUM`) | `BTCUSDT`, `ETHUSDT` | **2023-01-01 to 2025-12-31** (3.0 years; archive start) | $\pm 1\%$ vs $\pm 5\%$ bid/ask depth imbalance, near-touch depth slope, 7d liquidity thinning z-score, intra-hour depth instability |
