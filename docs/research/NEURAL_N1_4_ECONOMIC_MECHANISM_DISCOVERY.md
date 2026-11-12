# N1.4 — Greenfield Economic-First Alpha Discovery: Economic Mechanism Survey & Candidate Selection

- **Date**: 2026-11-11
- **Status**: `PHASE_A_B_C_COMPLETE`
- **Workspace**: `D:\Workspaces\besttime-crypto`
- **Package**: `neural_trading/n1_4/`
- **Predecessor Disposition**:
  - `N1_ECONOMIC_DISPOSITION = REJECTED_FOR_PRODUCTION_CANDIDACY`
  - `N1_2_ECONOMIC_DISPOSITION = REJECTED_FOR_PRODUCTION_CANDIDACY`
  - `H_B_POST_COST_DISPOSITION = REJECTED`
  - `H_B_HISTORICAL_L1_EVIDENCE = INSUFFICIENT`
  - `H_B_NEURAL_TRAINING = NOT_JUSTIFIED`
  - `N1_N1_3_PRODUCTION_CANDIDATES = 0`
  - `PROSPECTIVE_COLLECTOR = STOPPED`
  - `REAL_TRADING = DISABLED`

---

## 1. Phase A — Closure of N1.3 in `HISTORICAL_RESEARCH_REJECTED`

N1.3 is formally sealed in [`docs/research/NEURAL_N1_3_EXECUTABLE_CROSS_VENUE_EDGE.md`](file:///d:/Workspaces/besttime-crypto/docs/research/NEURAL_N1_3_EXECUTABLE_CROSS_VENUE_EDGE.md) under the terminal status `HISTORICAL_RESEARCH_REJECTED`. No further re-runs, feature re-scalings, or neural policy trainings are permitted on the N1.2/N1.3 `H-B` Cross-Venue Spot-Lead system.

### Recorded N1.3 Final Conclusions
1. **Quote currency contributed materially to raw premium**: Of the raw `H-B` cross-venue rank-IC at the 12h horizon (`+0.02521` in 2022–2023), **`84.2%`** was driven by the common `USDT/USD` quote-currency peg translation (`IC = +0.02123`), which carries zero cross-sectional alpha across `SYM/USDT` trading pairs.
2. **Quote-normalized 12h strategy failed even before fees**: Once normalized into true USD terms (`cb_usd / (bn_usdt * usdt_usd) - 1`), the `12h` cross-sectional dispersion strategy (`H_B_TRUE_USD_CS_12H`) was **gross negative** across 2022–2025 (`-$944.03` gross, `-$2,400.74` net, `-24.01%` cumulative net return).
3. **The 4h residual strategy did not clear execution costs**: While `H_B_RESIDUAL_CS_4H` achieved positive gross PnL (`+$2,135.42` cumulative 2022–2025, `3.05 bps` gross per trade), its `4h` rebalancing cadence generated `42.26x/yr` turnover and `$2,557.88` in execution friction (`14 bps` RT), leaving a negative net PnL of **`-$422.46` (`-4.22%`)** (`break-even RT cost = 11.75 bps < 14.0 bps`).
4. **One-hour delayed execution eliminated its remaining gross value**: Delaying execution by `+1h` collapsed cumulative gross PnL by **`83.3%`** (`+$2,135.42` $\to$ `+$355.83`, leaving `-$2,043.09` net), proving the residual cross-venue dispersion was a fast-decaying synchronization artifact rather than a durable economic transfer.
5. **No new neural model was justified**: Because no quote-normalized `H-B` specification cleared realistic execution costs in simple rule-based pilots, `H_B_NEURAL_TRAINING = NOT_JUSTIFIED`.

---

## 2. Why Prior N0–N1.3 Approaches Failed Economically

Across N0, N0.1, N0.2, N0.3, N1, N1.1, N1.2, and N1.3, every tested hypothesis shared two fatal structural assumptions:
1. **Short-Horizon (`1h–12h`) Directional Trading on a High-Friction Venue (`14 bps` Spot Taker RT)**:
   - At a `1h` to `12h` horizon, raw predictable price movements in liquid large-cap crypto are `1–4 bps` per rebalance event.
   - Paying `7 bps` per leg (`14 bps` round-trip) when expected gross payoff per trade is `< 4 bps` guarantees negative net expectation regardless of neural network architecture (TCN, GRU, Cross-Asset Attention, Stateful Gate).
2. **Spot Long-Only Execution Architecture (`beta in [0, 1]`)**:
   - Spot long-only portfolios cannot harvest structural carry, cannot isolate basis convergence from directional market drawdowns (`-65%` in 2022, `-29%` in 2025), and cannot earn positive cash yield when sitting in `USDT` during bear regimes without taking directional risk.

Consequently, **N1.4 starts from economic mechanisms first**:
- Who is the counterparty paying the expected return, and why do they continue paying it?
- Is the expected gross payoff per trade lifecycle **multiple times larger** (`5x–25x`) than the complete round-trip execution cost?
- Does the trade lifecycle operate over a multi-day to multi-week horizon (`3d–90d`) so that annual turnover stays low (`< 15x/yr`)?

---

## 3. Phase B — Survey of Candidate Economic Mechanisms (10 Mandatory Dimensions)

We survey four distinct crypto market mechanisms across all 10 required economic dimensions before selecting at most two candidates for Phase D–E falsification.

| Dimension | Candidate H-1: Dated Quarterly Delivery Basis Carry & Convergence (`SYMUSD_YYMMDD` / `SYMUSDT_YYMMDD`) | Candidate H-2: Multi-Day (`72h–168h`) Forced-Deleveraging Exhaustion & Spot Liquidity Provision | Candidate H-3: Perpetual Funding Rate Arbitrage (`Spot + Perp`) | Candidate H-4: Cross-DEX / CEX Latency & Statistical Arbitrage |
| :--- | :--- | :--- | :--- | :--- |
| **1. Economic Mechanism** (Who pays & why?) | Leveraged retail and directional funds demand embedded non-recourse/convex long leverage in **Dated Quarterly Delivery Futures** (`YYMMDD`). Because retail cannot easily borrow USD at institutional rates and prefers leveraged futures over spot, dated futures trade at a structural contango basis ($F_{t,T} > S_t$, `5%–25%` annualized). Arbitrageurs who buy Spot and short the `1x` COIN-M Dated Future lock in this basis. Unlike perpetuals, **dated delivery futures have zero 8h funding rate** and **contractually converge to the Spot Index TWAP ($F_{T,T} = S_T \implies b_T = 0.0\text{ bps}$) at `08:00 UTC` on expiry Friday**. | Over-leveraged directional longs are forced into margin liquidation cascades during multi-day market selloffs. Liquidation engines are price-insensitive forced sellers that depress spot prices below medium-term clearing value across 3–7 days. Patient liquidity providers buying Spot after extreme multi-day drawdown + volume climax + futures basis collapse demand a liquidity premium (`100–300 bps`) over the subsequent `72h–168h` recovery. | Leveraged perpetual futures traders pay 8h funding rates (`fundingRate`) to keep perpetual prices anchored to Spot. Cash-and-carry desks hold Long Spot + Short Perp to collect 8h funding payments. | Noise traders and slow automated market makers on secondary venues or AMMs leave temporary price dislocations (`5–20 bps`) lasting milliseconds to seconds after CEX block trades. |
| **2. Trade Lifecycle** | **Entry**: Enter `1x` delta-neutral pair (`Long 1.0x Spot Coin` deposited as `1x` inverse margin for `Short 1.0x COIN-M Dated Future SYMUSD_YYMMDD`) when contango basis $b_t = (F_{t,T}-S_t)/S_t \ge 75\text{ bps}$ and implied yield $\ge 5\%\text{ p.a.}$ (`14 <= DTE <= 175`).<br>**Hold**: Hold for `7d–90d` with zero ongoing funding cost.<br>**Exit**: Exit early when basis compresses to $b_t \le 15\text{ bps}$ (capturing roll-down early and freeing capital) **or** hold to `08:00 UTC` maturity settlement where $b_T = 0\text{ bps}$. | **Entry**: Enter Spot long when 72h drawdown is severe ($r_{72h} < -8\%$, `z < -1.5`), volume surges (`> 1.5x` 7d avg), and quarterly/perp basis compresses sharply (`z < -1.0`), signaling forced-liquidation climax.<br>**Hold**: Minimum `72h` (`3 days`) up to `168h` (`7 days`).<br>**Exit**: Exit after `72h–168h` when mean reversion completes or stop out on regime breakdown. | **Entry**: Enter Long Spot + Short Perp when trailing 8h funding > threshold.<br>**Hold**: Collect 8h funding intervals.<br>**Exit**: Unwind when funding flips negative for multiple intervals. | **Entry**: Sub-second order placement on lagging venue upon lead-venue orderbook sweep.<br>**Hold**: `50ms – 30s`.<br>**Exit**: Immediate unwind or inventory skew flatten. |
| **3. Market Structure** | **2-Leg Delta-Neutral Hedged Structure** (`Long Spot + Short 1x COIN-M Delivery Future`, or `50% Long Spot + 50% Short 1x USD-M Delivery Future`). Market beta $\beta \approx 0.0$. In COIN-M (`SYMUSD_YYMMDD`), the long spot coin itself serves as the `1x` collateral (`100%` capital efficiency, zero USD split required, liquidation price = $\infty$). | **Spot Long + Cash Reserve** (`0%` to `100%` dynamic exposure across liquid cross-section, max `25%` per symbol). | **2-Leg Delta-Neutral** (`50% Long Spot + 50% Short Perp` on USD-M, or `1x` COIN-M Perp). | **Multi-venue colocation / L2 orderbook maker-taker** across CEXs/DEXs. |
| **4. Expected Holding Horizon** | **`14 days` to `90 days`** (`336h–2,160h`). Rebalance checks occur on a `24h` cadence; positions are held across weeks. | **`3 days` to `7 days`** (`72h–168h`). | `7 days` to `60 days`. | `50 milliseconds` to `5 minutes`. |
| **5. Gross Payoff Distribution** | **Bounded, positively skewed, contractually anchored**: Entry at $b_0 \in [75, 550]\text{ bps}$ locked to exit at $b_{\text{exit}} \in [0, 15]\text{ bps}$ yields **`+60 to +535 bps` gross per trade lifecycle**. Exact USD equity evolution on `1x` COIN-M is $E_t = E_0 \frac{1+b_0}{1+b_t}$ (strictly positive whenever $b_t < b_0$). | **High variance, fat-tailed**: Successful liquidation rebounds pay `+150 to +400 bps` over 3–7 days, but multi-week structural cascades (e.g., LUNA May 2022, FTX Nov 2022, 2025 tariff/macro drawdowns) inflict `-500 to -1,500 bps` left-tail losses ("catching a falling knife"). | Moderate (`+5 to +30 bps` per week in bull markets; near `0` or negative in 2022/2025 bear markets when funding flips negative and basis widens against exit). | Small per trade (`+2 to +8 bps` gross), high Sharpe only if maker rebates are captured. |
| **6. Complete Execution Costs** | **4 legs per full round-trip** (`Buy Spot + Sell Dated Future` at entry; `Sell Spot + Buy/Settle Dated Future` at exit):<br>- Spot leg: `7.0 bps/leg` (`14.0 bps` RT)<br>- Dated Delivery Future leg: `4.0 bps/leg` (`1.5 bps` Binance CM/UM delivery fee + `2.5 bps` half-spread/impact = `8.0 bps` RT)<br>- **Total 4-leg RT friction = `22.0 bps` (`11.0 bps` per combined entry or exit)**.<br>- **Gross Payoff / Cost Ratio**: `75..450 bps` / `22 bps` = **`3.4x to 20.5x`**. | **2 legs per Spot round-trip**:<br>- `7.0 bps/leg` + `3.0 bps/leg` distressed liquidity impact = **`20.0 bps` RT**.<br>- Requires mean reversion > `+20 bps` net of left-tail drawdown losses. | **4 legs per round-trip** (`22.0 bps` RT) plus continuous 8h funding sign-flip whipsaws (`funding_level` explicitly rejected in `HMR-V4A`). | Requires VIP/Maker fee tiers (`0–1 bps`) and sub-millisecond colocation; impossible at retail/standard taker fees (`14 bps`). |
| **7. Capacity** | **High (`$10M–$100M+`)**: `BTCUSD_YYMMDD` and `ETHUSD_YYMMDD` quarterly delivery futures trade tens to hundreds of millions of USD daily on Binance, with multi-day entry windows that can be sliced via TWAP over hours. | **Moderate (`$1M–$10M`)**: Executing during liquidation climaxes faces widened books, though 72h–168h holding allows 1–4h TWAP entry. | **High (`$50M+`)**, but crowded by institutional Ethena/basis vaults in 2024–2025. | **Low (`$10k–$250k`)** per signals before exhausting top-of-book queue. |
| **8. Failure Mechanism** | 1. **Mark-price contango blowout mid-life**: If basis temporarily widens from `+100 bps` to `+600 bps` in a manic bull spike, unrealized MTM drawdown occurs (`E_t = E_0 (1+b_0)/(1+b_t)` drops `~4.7%`). However, in `1x` COIN-M where the physical Spot coin is posted as collateral, `1x` short inverse futures cannot be liquidated by Spot price rises, and the MTM drawdown deterministically recovers to `+b_0` at maturity $T$.<br>2. **Counterparty / Exchange credit risk** (mitigated by single-venue margin or tri-party custody).<br>3. **Flat term structure regime**: In deep bear/stagnant markets when basis stays `< 75 bps` across all symbols, the strategy sits in `100% Cash` earning `$0` rather than losing money. | **Multi-week structural solvency cascades**: When a selloff is driven by fundamental insolvency (LUNA, 3AC, FTX) or prolonged macro tightening rather than isolated margin exhaustion, prices continue falling `-15%` to `-40%` over 3–7 days after the initial climax, overwhelming the liquidity premium. | **Funding regime sign-flips & HMR-V4A governance block**: `funding_level` was already tested and rejected in `HMR-V4A` (`NO_GO` as directional predictor; crowded in 2024–2025). | **Adverse selection & latency decay**: Without L2/L3 orderbook snapshots and colocation, any signal observed on 1h/1m bars is already arbitraged away (`N1.3` proved `+1h` delay wipes out `83.3%` of cross-venue edge). |
| **9. Data Requirements** | - Historical 1h OHLCV of **Dated Quarterly Delivery Futures** (`CM` `SYMUSD_YYMMDD` and `UM` `SYMUSDT_YYMMDD`) across all 16 quarterly maturities (`220325` through `251226`, plus `260327` in Q4 2025 for bi-quarterly slope).<br>- Synchronized 1h Spot OHLCV (`SYMUSDT`) and `USDT-USD` quote rate.<br>- Exact delivery contract metadata (`expiry_utc = YY-MM-DD 08:00:00 UTC`, listing date, delisting date). | - Historical 1h Spot OHLCV (`2022–2025`, 8 symbols).<br>- Historical 1h Futures-Spot basis shock and volume surge series (`2022–2025`). | - 8h `fundingRate` and `markPriceKlines` (already rejected under `HMR-V4A`). | - Historical L2/L3 tick orderbook snapshots across venues (not available in free historical archives for 2022–2025). |
| **10. Neural Learning Opportunity** | **Term-Structure Carry Allocation & Early Compression Exit Policy (`TermStructureCarryPolicy`)**:<br>A rule-based cash-and-carry baseline uses fixed entry (`75 bps`) and exit (`15 bps`) thresholds with equal/yield weighting. A stateful neural policy taking the full cross-sectional term-structure state `[front_basis, annualized_yield, DTE, bi_quarterly_slope (back - front), basis_zscore, basis_momentum, current_weight, cash_prev]` can potentially learn:<br>1. **When to hold vs early-exit**: Harvesting compression at `+20..30 bps` when basis momentum stalls rather than waiting for full maturity (`08:00 UTC` weeks later), increasing capital velocity.<br>2. **Cross-sectional yield vs volatility ranking**: Allocating more capital to stable high-carry contracts (`BTC`, `ETH`, `BNB`) vs noisy altcoin contracts (`XRP`, `ADA`, `LTC`). | **Regime-Gated Liquidity Provision**: Learning when a 72h selloff is a temporary liquidation cascade vs a structural solvency collapse. However, if the underlying economic mechanism fails post-cost in Phase E, neural training is **prohibited** under Phase E/F gating. | **Blocked by HMR-V4A** (`funding_level` is a rejected feature in `HMR-V4A`). | **None on 1h/1m bars** (latency-bound problem, not a representation-learning problem). |

---

## 4. Phase C — Research Candidate Selection & HMR-V4A Governance Compliance

### 4.1 HMR-V4A Governance Audit
Per `docs/research/M2_HISTORICAL_SOURCES_PILOT.md` (`HMR-V4A`), the following features were previously evaluated and rejected for directional ML training and are **strictly excluded** from N1.4 neural training:
- Perpetual `fundingRate` (`funding_level`)
- `binance_open_interest` ( unavailable pre-2026 in historical archives)
- Perpetual `premiumIndexKlines` (`perp_premium`)
- `liquidationSnapshot` (unavailable in public archives)
- Single-asset UM `taker_buy_ratio`
- TradFi daily macro series (`SPX`, `NDX`, `DXY`, `VIX`)

### 4.2 Selected Candidates (At Most Two)

We select **two** candidates with orthogonal economic mechanisms and complete authoritative raw data availability (`2022–2025`):

1. **Primary Candidate `H-1` (`DATED_QUARTERLY_DELIVERY_BASIS_CARRY_AND_CONVERGENCE`)**:
   - **Why selected**: Never previously tested in `besttime-crypto` (neither in M2–M5 nor in N0–N1.3). Exploits a genuine structural transfer from retail leverage demand to delta-neutral arbitrageurs on **Dated Quarterly Delivery Futures** (`CM` `SYMUSD_YYMMDD` and `UM` `SYMUSDT_YYMMDD`), backed by a **deterministic contractual convergence anchor** ($F_{T,T} = S_T \implies b_T = 0.0\text{ bps}$ at `08:00 UTC` on expiry Friday) and **zero 8h funding payments**. Gross payoff per trade (`75–500 bps`) exceeds 4-leg round-trip friction (`22 bps`) by `3.4x–22x`.
2. **Secondary Candidate `H-2` (`STRUCTURAL_DELEVERAGING_LIQUIDITY_PROVISION_MULTI_DAY`)**:
   - **Why selected**: Tests whether moving from short horizons (`1h–12h` in N0–N1.3) to a **multi-day (`72h–168h`) holding horizon** on Spot liquidity provision after multi-day forced-deleveraging climaxes (`72h` return shock + volume surge + delivery basis collapse) can overcome `20 bps` stressed Spot execution friction, or whether directional Spot mean-reversion fails even at multi-day horizons.

Both candidates proceed to **Phase D (Raw Data Acquisition & Verification)** and **Phase E (Strict 13-Metric Post-Cost Economic Falsification)** before any neural network training is considered.
