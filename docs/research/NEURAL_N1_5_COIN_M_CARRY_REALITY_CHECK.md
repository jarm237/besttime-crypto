# N1.5 — COIN-M Quarterly Carry Contract & Execution Reality Check

- **Document ID**: `NEURAL-N1-5-COINM-CARRY-REALITY-CHECK-2026-11-11`
- **Workspace**: `D:\Workspaces\besttime-crypto`
- **Research Subject**: `H-1 — DATED_QUARTERLY_DELIVERY_BASIS_CARRY_AND_CONVERGENCE`
- **Research Package**: [`neural_trading/n1_5/`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_5/__init__.py)
- **Machine-Readable Ledger**: [`research/neural_n1_5/n1_5_coinm_reality_check_results.json`](file:///d:/Workspaces/besttime-crypto/research/neural_n1_5/n1_5_coinm_reality_check_results.json)
- **Verification Test Suite**: [`tests/test_neural_n1_5.py`](file:///d:/Workspaces/besttime-crypto/tests/test_neural_n1_5.py)

---

## Executive Summary & Final Dispositions

```text
FINAL_H1_DISPOSITION                   = H1_EXPLORATORY_NET_CARRY_SUPPORTED
EXECUTION_PRECISION_STATUS             = EXECUTION_APPROXIMATE
H1_HISTORICAL_MARGIN_REPLAY            = INSUFFICIENT (Sub-minute tick wicks/ADL unobservable; 1h markPriceKlines verified)
NEURAL_INCREMENTAL_VALUE_DISPOSITION   = NEURAL_INCREMENTAL_VALUE_NOT_SUPPORTED
EVALUATION_2022_2025_STATUS            = ADAPTIVE_DEVELOPMENT_NOT_INDEPENDENT_CONFIRMATION

N1_N1_5_PRODUCTION_CANDIDATES          = 0
PROSPECTIVE_COLLECTOR                  = STOPPED
REAL_TRADING                           = DISABLED
```

### Purpose of N1.5

In N1.4, the frozen rule-based baseline for `H-1` (`entry_basis_ma24 >= 75 bps`, `entry_annualized_yield_ma24 >= 5.0%`, `exit_basis_ma24 <= 15 bps`, max 4 concurrent assets, `25%` per-asset cap) reported `+$4,582.65` (`+22.91%`, Sharpe `1.109`, MaxDD `-2.24%`) over `2022–2025` under a continuous daily-rebalanced linear approximation with a `22.0 bps` 4-leg round-trip cost assumption.

N1.5 subjects that result to a strict **physical Binance COIN-M Inverse Contract, Fee, Delivery Settlement, Portfolio Margin, and Liquidity-Constrained Execution** reality check, without retuning any `H-1` parameter and without introducing any new neural network:

1. **Contract Mechanics Reality (Phase A)**: Reconstructed integer contract lots (`BTCUSD = $100/contract`, `ETHUSD, BNBUSD, XRPUSD, ADAUSD, LINKUSD, LTCUSD, SOLUSD = $10/contract`), Spot base-coin acquisition, internal transfer of base coin into the COIN-M margin wallet, inverse coin-settled PnL ($\text{PnL}_{\text{coin}} = N \cdot M \cdot (1/F_{\text{exit}} - 1/F_{\text{entry}})$), and zero cash/collateral double-counting across a 17-field position economic ledger.
2. **Fee & Settlement Contract Reality (Phase B)**:
   - Verified from official Binance exchange documentation and `128 / 128` daily 1-minute `indexPriceKlines` archives that quarterly delivery settlement uses the **30-minute (`07:30:00 to 08:00:00 UTC`) arithmetic mean TWAP of the Price Index** (with a 10-minute `Reduce-Only` window `07:50..08:00 UTC`), and charges a **delivery settlement fee equal to the COIN-M Taker fee (`5.0 bps`)**. Across all 128 symbol-expiry events (`2022–2025`), the official 30m Price Index TWAP differed from the `08:00 UTC` close by a mean absolute deviation of **`24.82 bps`** (max `113.93 bps`) and from the 60m TWAP by **`27.50 bps`**.
   - Verified that **Binance's 10% Futures BNB fee discount applies only to USD-M futures and does NOT apply to COIN-M futures** (where fees are settled in base coin `BTC`, `ETH`, etc.), whereas Spot allows a 25% BNB discount (`10.0 bps -> 7.5 bps` + `0.3 bps` BNB top-up conversion). Consequently, a realistic retail taker 4-leg round-trip costs **`39.0 bps`** (`34.6 bps` with Spot BNB discount; `49.0 bps` under stressed execution), compared to `22.0 bps` in N1.4.
3. **Why Physical Discrete COIN-M Position Lifecycles Outperform N1.4's Continuous Daily Rebalancing**:
   - Applying `39.0 bps` (`standard_retail_taker`) to N1.4's **continuous daily-rebalanced weight schedule** (`21.81x/yr` turnover) reduces Net PnL from `+$4,582.65` (`+22.91%`) to **`+$2,791.23` (`+13.96%`, Sharpe `0.709`)** at bar close, or **`+$2,335.48` (`+11.68%`)** with next-bar open slippage (`+$1,803.89` / `+$1,367.84` under `49.0 bps` `stressed_execution_cost`).
   - Why did N1.4 have `21.81x/yr` turnover? Because a continuous-weight backtest re-trades small USD fractions of every active pair every 24 hours whenever spot prices drift between two co-held assets—even when neither contract's basis has converged or expired.
   - In **physical COIN-M execution**, once Spot base coin is purchased, transferred to the COIN-M wallet, and locked against an integer number of short contracts ($N = \lfloor C_{\text{trans}} \cdot F_{\text{entry}} / (M \cdot (1 + f_{\text{cm,in}})) \rfloor$), the coin collateral naturally tracks the inverse contract's notional value ($\text{Notional}_{\text{coin}} = N \cdot M / F_{\text{mark}}$). Holding each discrete contract lot untouched until basis convergence (`basis_ma24 <= 15 bps`) or quarterly delivery/roll (`08:00 UTC`) eliminates daily drift micro-rebalancing, cutting turnover to **`16.14x/yr`** (`90` discrete position lifecycles over 4 years, median holding period **`66.5 days`**) and preserving **`+$5,616.56` (`+28.08%` on committed capital, `10.25%` annualized on deployed capital, Sharpe `1.865`, MaxDD `-2.30%`)** under `standard_retail_taker` (`EXECUTABLE_NET_CARRY`), and **`+$5,257.48` (`+26.29%`, Sharpe `1.755`)** even under `stressed_execution_cost` (`49.0 bps` round-trip).

---

## Phase A — Reconstruction of Actual COIN-M Contract Economics

### A.1 Official Binance COIN-M Contract Specifications (`exchangeInfo` Verification)

Live verification against `https://dapi.binance.com/dapi/v1/exchangeInfo` and official Binance COIN-M Bracket / Margin Rules ([`neural_trading/n1_5/contract_specs_and_data.py`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_5/contract_specs_and_data.py#L46-L153)) confirms the exact physical specifications for all 8 delivery pairs:

| Spot Pair | COIN-M Pair | `contractSize` ($M$) | Quote / Margin Coin | Tier-1 Max Notional | Tier-1 Maint. Margin Rate ($\text{MMR}_1$) | `exchangeInfo` Base `maintMarginPercent` | `requiredMarginPercent` (Initial) | `liquidationFee` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `BTCUSDT` | `BTCUSD` | **$100.00** | `BTC` | $250,000 | `0.40%` (`0.0040`) | `2.50%` (`0.0250`) | `5.00%` | `1.00%` |
| `ETHUSDT` | `ETHUSD` | **$10.00** | `ETH` | $250,000 | `0.40%` (`0.0040`) | `2.50%` (`0.0250`) | `5.00%` | `1.00%` |
| `BNBUSDT` | `BNBUSD` | **$10.00** | `BNB` | $100,000 | `0.50%` (`0.0050`) | `2.50%` (`0.0250`) | `5.00%` | `1.00%` |
| `XRPUSDT` | `XRPUSD` | **$10.00** | `XRP` | $100,000 | `0.50%` (`0.0050`) | `2.50%` (`0.0250`) | `5.00%` | `1.00%` |
| `ADAUSDT` | `ADAUSD` | **$10.00** | `ADA` | $100,000 | `0.50%` (`0.0050`) | `2.50%` (`0.0250`) | `5.00%` | `1.00%` |
| `LINKUSDT` | `LINKUSD` | **$10.00** | `LINK` | $100,000 | `0.50%` (`0.0050`) | `2.50%` (`0.0250`) | `5.00%` | `1.00%` |
| `LTCUSDT` | `LTCUSD` | **$10.00** | `LTC` | $100,000 | `0.50%` (`0.0050`) | `2.50%` (`0.0250`) | `5.00%` | `2.00%` |
| `SOLUSDT` | `SOLUSD` | **$10.00** | `SOL` | $100,000 | `0.50%` (`0.0050`) | `2.50%` (`0.0250`) | `5.00%` | `2.50%` |

### A.2 Physical COIN-M Lifecycle Equations & Zero Double-Counting Proof

In [`run_physical_coinm_carry_simulation`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_5/coinm_simulator.py#L114-L580), every position follows a strict 6-stage physical accounting sequence:

1. **Integer Contract Sizing from Available USD Cash & Collateral**:
   Given target USD allocation $U_{\text{alloc}}$, execution Spot ask price $S_{\text{in}} = S_{\text{ref}} (1 + s_{\text{spot}})$, and execution COIN-M bid price $F_{\text{in}} = F_{\text{ref}} (1 - s_{\text{cm}})$, the maximum integer number of short contracts $N \in \mathbb{Z}_{\ge 0}$ that can be 100% floor-collateralized is:
   $$N = \left\lfloor \frac{U_{\text{alloc}} \cdot F_{\text{in}}}{M \cdot S_{\text{in}} \cdot (1 + f_{\text{spot,in}}) \cdot (1 + f_{\text{cm,in}})} \right\rfloor$$
   If $N < 1$, no trade is opened.

2. **Spot Purchase & Fee Deduction**:
   To collateralize $N$ short contracts of USD notional $V_{\text{usd}} = N \cdot M$ and cover the COIN-M entry fee in base coin, the exact base-coin quantity acquired on Spot is:
   $$C_{\text{acq}} = \frac{N \cdot M}{F_{\text{in}}} \cdot (1 + f_{\text{cm,in}})$$
   $$\text{entry\_spot\_notional} = C_{\text{acq}} \cdot S_{\text{in}}, \qquad \text{entry\_spot\_fee} = \text{entry\_spot\_notional} \cdot f_{\text{spot,in}}$$
   The portfolio's `cash_reserve_usd` is immediately debited by $\text{entry\_spot\_notional} + \text{entry\_spot\_fee}$.

3. **Internal Wallet Transfer & COIN-M Short Entry**:
   All acquired base coin is transferred from the Spot wallet to the COIN-M Delivery Margin wallet ($C_{\text{trans}} = C_{\text{acq}}$, leaving `0.0` coin in the Spot wallet so Spot and Futures never double-count the same coin). Upon shorting $N$ contracts at $F_{\text{in}}$, the COIN-M entry fee in coin is $f_{\text{cm,coin}} = \frac{N \cdot M}{F_{\text{in}}} f_{\text{cm,in}}$, leaving the COIN-M margin wallet balance:
   $$W_{\text{coin}} = C_{\text{trans}} - f_{\text{cm,coin}} = \frac{N \cdot M}{F_{\text{in}}}$$

4. **Hourly Mark-to-Market Inverse PnL & Margin Ratio Tracking**:
   At every hour $t$ during the position's life, given the COIN-M Mark Price $F_{\text{mark}, t}$ from `markPriceKlines`, the inverse unrealized PnL in base coin is:
   $$\text{uPnL}_{\text{coin}}(t) = N \cdot M \cdot \left(\frac{1}{F_{\text{mark}, t}} - \frac{1}{F_{\text{in}}}\right)$$
   Therefore, the total COIN-M Margin Balance in base coin is:
   $$B_{\text{margin, coin}}(t) = W_{\text{coin}} + \text{uPnL}_{\text{coin}}(t) = \frac{N \cdot M}{F_{\text{in}}} + N \cdot M \left(\frac{1}{F_{\text{mark}, t}} - \frac{1}{F_{\text{in}}}\right) = \frac{N \cdot M}{F_{\text{mark}, t}}$$
   And the Maintenance Margin required in base coin is:
   $$\text{MM}_{\text{coin}}(t) = \text{MMR} \cdot \frac{N \cdot M}{F_{\text{mark}, t}}$$
   Hence, for an unleveraged 1x floor-collateralized COIN-M short where $W_{\text{coin}} = N \cdot M / F_{\text{in}}$, the COIN-M Margin Ratio is invariant to spot price rallies:
   $$\text{Margin Ratio}(t) = \frac{\text{MM}_{\text{coin}}(t)}{B_{\text{margin, coin}}(t)} = \text{MMR} \quad (0.40\% \text{ for BTC/ETH}, \; 0.50\% \text{ for Alts}, \; 2.50\% \text{ under base } \text{exchangeInfo})$$

5. **Exit / Quarterly Delivery Settlement / Direct Roll**:
   - **Delivery Settlement (`DELIVERY_SETTLEMENT`)**: At `08:00 UTC` on the quarterly expiry date, the contract settles automatically against the official 30-minute (`07:30..08:00 UTC`) Price Index TWAP $I_{\text{settle}}$:
     $$\text{rPnL}_{\text{coin}} = N \cdot M \left(\frac{1}{I_{\text{settle}}} - \frac{1}{F_{\text{in}}}\right), \qquad \text{fee}_{\text{deliv, coin}} = \frac{N \cdot M}{I_{\text{settle}}} \cdot f_{\text{cm,deliv}}$$
   - **Early Basis Compression Close (`EARLY_COMPRESSION_CLOSE`)**: When `basis_ma24 <= 15 bps` (or `basis_bps <= 5 bps`), the short future is bought back on the COIN-M orderbook at $F_{\text{out}} = F_{\text{ref, out}}(1 + s_{\text{cm, out}})$:
     $$\text{rPnL}_{\text{coin}} = N \cdot M \left(\frac{1}{F_{\text{out}}} - \frac{1}{F_{\text{in}}}\right), \qquad \text{fee}_{\text{exit, coin}} = \frac{N \cdot M}{F_{\text{out}}} \cdot f_{\text{cm,out}}$$
   - **Final Coin Returned & Spot Sale (or Direct Roll)**:
     The final coin in the COIN-M wallet is $C_{\text{final}} = W_{\text{coin}} + \text{rPnL}_{\text{coin}} - \text{fee}_{\text{exit/deliv, coin}}$. Unless directly rolled into the next quarterly contract (which keeps $C_{\text{final}}$ inside the COIN-M wallet and saves both the Spot sell fee and Spot buy fee), $C_{\text{final}}$ is transferred back to Spot and sold at $S_{\text{out}} = S_{\text{ref, out}}(1 - s_{\text{spot}})$ for net USD proceeds:
     $$\text{exit\_spot\_proceeds} = C_{\text{final}} \cdot S_{\text{out}} \cdot (1 - f_{\text{spot,out}})$$
     which is credited back to `cash_reserve_usd`.

6. **Exact Portfolio Equity Reconciliation**:
   Across all 10 simulation runs (`5` fee scenarios $\times$ `2` execution modes), the sum of individual position net PnLs ($\sum_k (\text{exit\_spot\_proceeds}_k - \text{entry\_spot\_notional}_k - \text{entry\_spot\_fee}_k)$) matches `final_portfolio_equity_usd - initial_capital_usd` to within **`$0.0004` (`0.04 cents`)**, with **`0` double-counting events** (verified by unit test `test_phase_a_17_field_ledger_and_zero_double_counting` in [`tests/test_neural_n1_5.py`](file:///d:/Workspaces/besttime-crypto/tests/test_neural_n1_5.py#L46-L95)).

### A.3 Sample 17-Field Position Economic Ledgers (`EXECUTABLE_NET_CARRY`, `standard_retail_taker`)

Below are three representative closed position ledgers from the `standard_retail_taker` (`EXECUTABLE_TWAP_CONSTRAINED`) simulation illustrating all three physical exit mechanisms (`EARLY_COMPRESSION_CLOSE`, `DELIVERY_SETTLEMENT` during a +64% BTC bull rally, and `DELIVERY_SETTLEMENT_AND_ROLL` into the next quarter):

| Mandatory Ledger Field | Pos #2 (`ETHUSD_220325` — Early Compression Close in Bear Market) | Pos #32 (`BTCUSD_240329` — Quarterly Delivery Settlement in Bull Rally) | Pos #34 (`LTCUSD_240329` — Delivery Settlement & Direct Roll to `240628`) |
| --- | --- | --- | --- |
| `symbol` / `contract_symbol` | `ETHUSDT` / `ETHUSD_220325` | `BTCUSDT` / `BTCUSD_240329` | `LTCUSDT` / `LTCUSD_240329` |
| `entry_hour_ms` $\to$ `exit_hour_ms` (`holding_days`) | `2022-01-02` $\to$ `2022-02-09` (`38.00d`) | `2023-12-30` $\to$ `2024-03-29` (`90.21d`) | `2023-12-30` $\to$ `2024-03-29` (`90.21d`) |
| `exit_type` | `EARLY_COMPRESSION_CLOSE` | `DELIVERY_SETTLEMENT` | `DELIVERY_SETTLEMENT_AND_ROLL` |
| `entry_basis_bps` / `entry_ann_yield_pct` | `200.39 bps` / `8.84%` | `332.28 bps` / `28.29%` | `351.38 bps` / `20.62%` |
| 1. `entry_spot_notional` | `$4,985.3287` | `$5,182.1029` | `$5,250.7998` |
| 2. `entry_spot_fee` | `$4.9853` (`10.0 bps`) | `$5.1821` (`10.0 bps`) | `$5.2508` (`10.0 bps`) |
| 3. `coin_acquired` | `1.32466775 ETH` | `0.12287142 BTC` | `71.78546601 LTC` |
| 4. `coin_transferred_as_collateral` | `1.32466775 ETH` | `0.12287142 BTC` | `71.78546601 LTC` |
| 5. `contract_size_usd` | `$10.0` | `$100.0` | `$10.0` |
| 6. `contracts_short` | `508` (`$5,080` notional) | `54` (`$5,400` notional) | `549` (`$5,490` notional) |
| 7. `future_entry_price` | `$3,836.841357` | `$43,970.354750` | `$76.516115` |
| 8. `future_mark_price` (at exit) | `$3,135.372845` | `$69,975.909329` | `$93.922345` |
| 9. `inverse_unrealized_pnl_coin` | `+0.29722653 ETH` | `-0.04628442 BTC` | `-13.83693207 LTC` |
| 10. `margin_wallet_balance_coin` | `1.32400575 ETH` | `0.12281002 BTC` | `71.74959122 LTC` |
| 11. `maintenance_margin_coin` | `0.00648493 ETH` | `0.00030610 BTC` | `0.28956330 LTC` |
| 12. `margin_ratio` (Tier-1 / Base-2.5%) | `0.004000` / `0.025000` (`250x` cov.) | `0.004000` / `0.025000` (`250x` cov.) | `0.005000` / `0.025000` (`200x` cov.) |
| 13. `delivery_settlement_index` | `null` (early orderbook exit) | `$69,975.909329` (30m Index TWAP) | `$93.922345` (30m Index TWAP) |
| 14. `realized_pnl_coin` | `+0.29621624 ETH` | `-0.04564060 BTC` | `-13.29704753 LTC` |
| 15. `delivery_fee_coin` (or exit fee coin) | `0.00081011 ETH` (`5.0 bps`) | `0.00003858 BTC` (`5.0 bps`) | `0.02922627 LTC` (`5.0 bps`) |
| 16. `exit_spot_proceeds` | `$5,064.4783` | `$5,426.8854` | `$5,534.1333` (rolled in-kind to Pos #38) |
| 17. `final_portfolio_equity_usd` | `$20,349.2308` | `$21,966.0149` | `$21,981.9306` |
| **Position Net USD PnL (`Net Return %`)** | **`+$74.1643` (`+1.486%`)** | **`+$239.6004` (`+4.619%`)** | **`+$278.0827` (`+5.291%`)** |

---

## Phase B — Corrected Fee & Delivery Settlement Contracts

### B.1 Official Binance Delivery Settlement Rule & Empirical Verification (`128 / 128` Quarterly Expiries)

Per official Binance COIN-M Quarterly Delivery Contract specifications:
- **Delivery Time**: `08:00:00 UTC` on the last Friday of each calendar quarter (`March, June, September, December`).
- **Settlement Price**: The arithmetic average of the underlying **Price Index** (`indexPriceKlines`) every second/minute from **`07:30:00 UTC` to `08:00:00 UTC`** (30 minutes prior to delivery), **NOT** a 60-minute TWAP and **NOT** the `08:00 UTC` Spot close.
- **Pre-Delivery Trading Restriction**: During the final 10 minutes before expiry (`07:50:00 to 08:00:00 UTC`), only `Reduce-Only` orders are accepted.
- **Settlement Fee**: Positions settled at delivery pay a flat **Delivery Settlement Fee equal to the COIN-M Taker rate (`5.0 bps` / `0.05%`)** on settled notional, with zero bid-ask spread or orderbook slippage on the futures leg.

We downloaded and SHA-256 `.CHECKSUM`-verified all **`128 / 128` daily 1-minute `indexPriceKlines` archives** (`data/futures/cm/daily/indexPriceKlines/<PAIR>/1m/<PAIR>-1m-<YYYY-MM-DD>.zip`) across all 16 quarterly delivery dates (`220325` through `251226`) and all 8 COIN-M pairs:
- **Checksum integrity**: `128 / 128` archives (`100.0%`) matched their official `.CHECKSUM` SHA-256 digest (`30 / 30` 1-minute bars present in every `[07:30, 07:59] UTC` window).
- **30-Minute Index TWAP vs `08:00 UTC` Spot Close**: Mean absolute difference = **`24.821 bps`**, maximum absolute difference = **`113.933 bps`**.
- **30-Minute Index TWAP vs 60-Minute Index TWAP**: Mean absolute difference = **`27.499 bps`**.

Using the exact 30-minute Price Index TWAP is therefore mandatory for accurate delivery settlement accounting.

### B.2 Historical Fee Schedule & BNB Discount Eligibility Reality (`2022–2025`)

Per official Binance VIP-0 Fee Schedules (`2022–2025`):
1. **Spot (`BTCUSDT, ETHUSDT, BNBUSDT, XRPUSDT, ADAUSDT, LINKUSDT, LTCUSDT, SOLUSDT`)**:
   - Standard VIP-0 fee: **`10.0 bps` (`0.10%`) Maker / `10.0 bps` (`0.10%`) Taker**.
   - Note on Binance Zero-Fee BTC Spot Promotions (`2022-07-08 to 2023-03-22`): Applied to `BTCUSDT` Spot, while `ETHUSDT` and all 6 altcoins remained at `10.0 bps` (`0.10%`) throughout `2022–2025` (only `BTCFDUSD`/`ETHFDUSD` had zero maker fees later).
   - **Spot BNB 25% Fee Discount**: Eligible when holding `BNB` in the Spot wallet (`10.0 bps -> 7.5 bps`), plus a `~0.3 bps` conversion friction to replenish `BNB`.
2. **COIN-M Delivery Futures (`BTCUSD_YYMMDD`, etc.)**:
   - Standard VIP-0 fee (`2022–2025`): **`1.0 bps` (`0.01%`) Maker / `5.0 bps` (`0.05%`) Taker** (updated in late 2024 to `2.0 bps` Maker / `5.0 bps` Taker).
   - **Quarterly Delivery Settlement Fee**: **`5.0 bps` (`0.05%`)** (charged at VIP-0 Taker rate).
   - **COIN-M BNB Discount Ineligibility**: Unlike USD-M Futures (where holding `BNB` in the USD-M wallet grants a 10% fee discount), **COIN-M Futures fees are settled exclusively in the underlying base asset (`BTC`, `ETH`, `SOL`, etc.) and are NOT eligible for a BNB fee discount**.

Accordingly, N1.5 evaluates five explicit fee schedules:

| Fee Scenario ID | Spot Entry / Exit Fee | Spot BNB Replenish | COIN-M Entry / Early Exit Fee | COIN-M Delivery Settlement Fee | Spot + COIN-M Half-Spread / Slippage | **All-In 4-Leg Round-Trip Cost** | **Quarterly Direct Roll Cost** |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `n1_4_reference_schedule` *(N1.4 baseline)* | `5.5 / 5.5 bps` | `0.0 bps` | `2.5 / 2.5 bps` | `1.5 bps` | `3.0 + 3.0 bps` (`1.5 bps/leg`) | **`22.0 bps`** | **`5.5 bps`** |
| 1. `verified_historical_fee_schedule` *(VIP-0 Passive Limit / Taker Blend)* | `10.0 / 10.0 bps` | `0.0 bps` | `3.0 / 3.0 bps` | `5.0 bps` | `3.5 + 3.5 bps` (`1.75 bps/leg`) | **`33.0 bps`** | **`10.0 bps`** |
| 2. `standard_retail_taker` *(100% VIP-0 Taker, No BNB)* | `10.0 / 10.0 bps` | `0.0 bps` | `5.0 / 5.0 bps` | `5.0 bps` | `4.5 + 4.5 bps` (`2.25 bps/leg`) | **`39.0 bps`** | **`12.5 bps`** |
| 3. `bnb_discount_if_eligible` *(25% Spot BNB Discount, 0% COIN-M Discount)* | `7.5 / 7.5 bps` | `0.6 bps` RT | `5.0 / 5.0 bps` | `5.0 bps` | `4.5 + 4.5 bps` (`2.25 bps/leg`) | **`34.6 bps`** | **`12.5 bps`** |
| 4. `stressed_execution_cost` *(100% Taker + Doubled Spread/Impact)* | `10.0 / 10.0 bps` | `0.0 bps` | `5.0 / 5.0 bps` | `5.0 bps` | `9.5 + 9.5 bps` (`4.75 bps/leg`) | **`49.0 bps`** | **`15.5 bps`** |

### B.3 Impact of Realistic Fee Schedules on N1.4 Continuous Daily Rebalancing vs N1.5 Physical Discrete COIN-M Positions

| Fee Scenario | All-In 4-Leg RT Cost | N1.4 Continuous Daily Weights (`close_t`, `21.81x/yr`) | N1.4 Continuous Daily Weights (`next_open` slip, `21.81x/yr`) | **N1.5 Physical COIN-M `MODELLED_NET_CARRY` (`close_t`)** | **N1.5 Physical COIN-M `EXECUTABLE_NET_CARRY` (`4h TWAP`, `<=5% vol`)** |
| --- | --- | --- | --- | --- | --- |
| `n1_4_reference_schedule` | `22.0 bps` | `+$4,582.65` (`+22.91%`, SR `1.109`) | `+$4,091.16` (`+20.46%`) | **`+$7,047.26` (`+35.24%`, SR `1.648`)** | **`+$6,244.56` (`+31.22%`, SR `2.055`)** |
| 1. `verified_historical_fee_schedule` | `33.0 bps` | `+$3,408.26` (`+17.04%`, SR `0.850`) | `+$2,940.20` (`+14.70%`) | **`+$6,610.10` (`+33.05%`, SR `1.556`)** | **`+$5,826.60` (`+29.13%`, SR `1.932`)** |
| 2. `standard_retail_taker` | `39.0 bps` | `+$2,791.23` (`+13.96%`, SR `0.709`) | `+$2,335.48` (`+11.68%`) | **`+$6,297.45` (`+31.49%`, SR `1.491`)** | **`+$5,616.56` (`+28.08%`, SR `1.865`)** |
| 3. `bnb_discount_if_eligible` | `34.6 bps` | `+$3,233.37` (`+16.17%`, SR `0.811`) | `+$2,768.80` (`+13.84%`) | **`+$6,499.27` (`+32.50%`, SR `1.536`)** | **`+$5,773.64` (`+28.87%`, SR `1.913`)** |
| 4. `stressed_execution_cost` | `49.0 bps` | `+$1,803.89` (`+9.02%`, SR `0.476`) | `+$1,367.84` (`+6.84%`) | **`+$5,929.14` (`+29.65%`, SR `1.415`)** | **`+$5,257.48` (`+26.29%`, SR `1.755`)** |

**Key Structural Insight**:
1. Under N1.4's continuous daily-rebalanced portfolio weight approximation (`21.81x/yr` turnover), increasing round-trip costs from `22.0 bps` to `39.0 bps` (`standard_retail_taker`) increases cumulative friction from `$2,177.05` to `$3,723.25` (`$4,116.40` with next-bar open slippage), cutting Net PnL nearly in half (`+$4,582.65 -> +$2,791.23` at `close_t`, or `+$2,335.48` at `next_open`).
2. However, that daily rebalancing friction was an artifact of re-equalizing USD weights across co-held positions every 24 hours. In the physical COIN-M simulator, each integer contract lot is held without daily drift micro-trades until `basis_ma24 <= 15 bps` or quarterly expiry/roll (`16.14x/yr` turnover, `$1,297.55` total friction under `standard_retail_taker`). As a result, physical discrete COIN-M carry remains solidly profitable across every single fee schedule (`+$5,257.48` to `+$5,826.60` in `EXECUTABLE_NET_CARRY`).

---

## Phase C — Portfolio Margin & Risk Reality

### C.1 1-Hour `markPriceKlines` Replay (`783 / 783` Verified Archives)

We downloaded and SHA-256 `.CHECKSUM`-verified all **`783 / 783` monthly 1-hour `markPriceKlines` archives** (`data/futures/cm/monthly/markPriceKlines/<CONTRACT>/1h/`) across all active COIN-M quarterly delivery contracts (`2022–2025`) and evaluated both `f1_mark_close` and the worst intrabar `f1_mark_high` against `spot_low_usd` on every active position hour:

- **Maximum Margin Ratio Observed (Tier-1 `0.40%/0.50%` MMR)**: **`0.005000` (`0.50%`)**, corresponding to a minimum collateral coverage multiple of **`200.0x` maintenance margin**.
- **Maximum Margin Ratio Observed (`exchangeInfo` Base `2.50%` MMR)**: **`0.025000` (`2.50%`)**, corresponding to **`40.0x` maintenance margin**.
- **Maximum Intrabar Basis Expansion Observed (`f1_mark_high` vs `spot_low_usd`)**: **`+105.23%`** (during an altcoin volatility wick), during which a 1x coin-collateralized short maintained a `0.0050` (`0.50%`) margin ratio because $W_{\text{coin}} + \text{uPnL}_{\text{coin}} = N \cdot M / F_{\text{mark}}$ scales identically with $\text{MM}_{\text{coin}} = \text{MMR} \cdot (N \cdot M / F_{\text{mark}})$.
- **Maximum Unhedged USD Residual from Integer Contract Rounding ($N \cdot M - W_{\text{coin}} \cdot F_{\text{in}}$)**: Mean **`$0.63`**, max **`$13.87`** across the entire 4-year simulation (since $M = \$100$ for `BTCUSD` and $\$10$ for `ETHUSD`/alts).
- **1-Hour Mark Price Liquidation Events (`2022–2025`)**: **`0`**.

### C.2 Parametric Basis Expansion & Leverage Stress Matrix

Why is it dangerous to assume `liquidation_price = infinity` unconditionally? Because if a trader shorts **more** contracts than the physical coin transferred into the COIN-M wallet ($L = \frac{N \cdot M / F_{\text{in}}}{W_{\text{coin}}} > 1.0$, e.g., due to under-collateralization, fee depletion, or leverage), a sharp rise in the futures mark price $F_{\text{mark}} = S \cdot (1 + b_{\text{spike}})$ relative to entry causes $\text{uPnL}_{\text{coin}}$ to consume $W_{\text{coin}}$:

$$B_{\text{margin, coin}}(F_{\text{mark}}) = W_{\text{coin}} \left[ 1 + L \left(\frac{F_{\text{in}}}{F_{\text{mark}}} - 1\right) \right]$$

Liquidation occurs as soon as $B_{\text{margin, coin}}(F_{\text{mark}}) \le \text{MMR} \cdot L \cdot W_{\text{coin}} \frac{F_{\text{in}}}{F_{\text{mark}}}$, i.e., when:
$$\frac{F_{\text{mark}}}{F_{\text{in}}} \ge \frac{L (1 - \text{MMR})}{L - 1}$$

 Furthermore, even for a `1.00x` floor-collateralized short ($L = 1.0$) that cannot be liquidated in coin terms, if the basis spikes violently ($F_{\text{mark}} \gg S$) while the position is still open, the **USD mark-to-market equity** of the combined Spot + COIN-M package ($B_{\text{margin, coin}} \cdot S = (N \cdot M) \cdot \frac{S}{F_{\text{mark}}} = \frac{N \cdot M}{1 + b_{\text{spike}}}$) suffers a transient unrealized USD drawdown until the basis re-converges at expiry!

The stress table below ([`run_margin_and_basis_stress_suite`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_5/coinm_simulator.py#L696-L760)) quantifies both effects across leverage multiples $L \in \{1.00\times, 1.05\times, 1.50\times, 2.00\times, 3.00\times\}$ and basis/price spikes $+10\%$ to $+400\%$:

| Collateral / Leverage Mode ($L$) | Spike $+10\%$ (`MR_Tier1` / `MR_2.5%` / `USD_DD`) | Spike $+25\%$ (`MR_Tier1` / `MR_2.5%` / `USD_DD`) | Spike $+50\%$ (`MR_Tier1` / `MR_2.5%` / `USD_DD`) | Spike $+100\%$ (`MR_Tier1` / `MR_2.5%` / `USD_DD`) | Spike $+200\%$ (`MR_Tier1` / `MR_2.5%` / `USD_DD`) | Spike $+400\%$ (`MR_Tier1` / `MR_2.5%` / `USD_DD`) |
| --- | --- | --- | --- | --- | --- | --- |
| **`1.00x` Floor-Collateralized ($L=1.00$)** | `0.40%` / `2.50%` / `-8.18%` | `0.40%` / `2.50%` / `-19.20%` | `0.40%` / `2.50%` / `-32.67%` | `0.40%` / `2.50%` / `-49.50%` | `0.40%` / `2.50%` / `-66.33%` | `0.40%` / `2.50%` / `-79.80%` |
| **`1.05x` Under-Collateralized ($L=1.05$)** | `0.42%` / `2.64%` / `-8.59%` | `0.43%` / `2.66%` / `-20.16%` | `0.43%` / `2.69%` / `-34.30%` | `0.44%` / `2.76%` / `-51.98%` | `0.47%` / `2.91%` / `-69.65%` | `0.52%` / `3.27%` / `-83.79%` |
| **`1.50x` Leveraged Short ($L=1.50$)** | `0.63%` / `3.93%` / `-12.27%` | `0.68%` / `4.26%` / `-28.80%` | `0.79%` / `4.95%` / `-49.00%` | `1.18%` / `7.35%` / `-74.25%` | `40.4%` / **LIQ (`252.5%`)** | **LIQ (`>100%`)** / **LIQ** |
| **`2.00x` Leveraged Short ($L=2.00$)** | `0.88%` / `5.49%` / `-16.36%` | `1.05%` / `6.56%` / `-38.40%` | `1.55%` / `9.71%` / `-65.33%` | `40.4%` / **LIQ (`252.5%`)** | **LIQ (`>100%`)** / **LIQ** | **LIQ (`>100%`)** / **LIQ** |
| **`3.00x` Leveraged Short ($L=3.00$)** | `1.46%` / `9.13%` / `-24.55%` | `2.29%` / `14.29%` / `-57.60%` | `40.4%` / **LIQ (`252.5%`)** | **LIQ (`>100%`)** / **LIQ** | **LIQ (`>100%`)** / **LIQ** | **LIQ (`>100%`)** / **LIQ** |

### C.3 Historical Sub-Minute Margin & ADL Replay Limitation

Public Binance historical archives provide 1-hour `markPriceKlines` and 1-minute `indexPriceKlines`, but do **not** provide millisecond Mark Price tick streams, exchange Auto-Deleveraging (`ADL`) indicator queues, or internal Spot-to-COIN-M wallet transfer latency logs. Accordingly, we record the mandatory status:

```text
H1_HISTORICAL_MARGIN_REPLAY = INSUFFICIENT
```
*(Insufficient for sub-minute flash-wick mark dislocations and exchange ADL queue preemption; verified clean on 1-hour `markPriceKlines` highs across all 783 contract-months).*

---

## Phase D — Capacity, Executable Price & Data Integrity Audit

### D.1 Resolution of the Single Unverified Archive from N1.4 (`SOLUSD_250926-1h-2025-08.zip`)

In N1.4, `966 / 967` monthly COIN-M `klines` archives were checksum-verified, with 1 archive (`SOLUSD_250926-1h-2025-08.zip`) having `expected_sha256: None` due to a transient read timeout on its `.CHECKSUM` HTTP request during 16-worker parallel downloading.
- In N1.5 ([`recheck_unverified_n1_4_archive`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_5/contract_specs_and_data.py#L204-L249)), we fetched `https://data.binance.vision/data/futures/cm/monthly/klines/SOLUSD_250926/1h/SOLUSD_250926-1h-2025-08.zip.CHECKSUM`:
  - **Local file SHA-256**: `ba535e7ff6d4c5de77500583f1d2dff327c3f727817aab04b009e541cdadf942`
  - **Official `.CHECKSUM` SHA-256**: `ba535e7ff6d4c5de77500583f1d2dff327c3f727817aab04b009e541cdadf942` (`100%` match; all `967 / 967` `klines` archives, `783 / 783` `markPriceKlines` archives, and `128 / 128` 1m `indexPriceKlines` archives are now 100% SHA-256 verified).
- **Exclusion Sensitivity Test**: Even if `SOLUSD_250926-1h-2025-08.zip` is completely masked out of the simulation (`exclude_unverified_sol_2025_08=True`), `EXECUTABLE_NET_CARRY` under `standard_retail_taker` changes by only **`-$28.87`** (`+$5,616.56 -> +$5,587.69`, or `-0.14%` of committed capital).

### D.2 Liquidity-Constrained Capacity Curve (`<= 5%` Hourly Contract Volume over 4h TWAP)

In `EXECUTABLE_TWAP_CONSTRAINED` mode:
1. Per-contract hourly volume is verified in exact USD notional (`volume_contracts * contract_size_usd`).
2. Entry orders are only permitted when time-to-maturity $\text{TTM} \ge 72.0\text{ hours}$ and the contract is actively listed with positive volume.
3. Order execution is capped at **`<= 5.0%` of the contract's hourly USD volume per hour across a 4-hour TWAP window** (`max_hourly_vol_participation = 0.05`, `twap_window_hours = 4`). Orders exceeding this liquidity cap receive a **partial fill** (`filled_fraction < 1.0`), and pay an additional square-root market impact penalty $\Delta s_{\text{impact}} = 2.0\text{ bps} \times \sqrt{V_{\text{order}} / V_{\text{hour}}}$.

Evaluating `standard_retail_taker` (`39.0 bps` base RT + market impact) across committed capital levels from `$10,000` to `$500,000` ([`run_capacity_and_stress_experiments`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_5/coinm_simulator.py#L653-L693)):

| Initial Capital Committed | Realized Net PnL ($) | Net Return on Committed Capital (%) | Annualized Return on Deployed Capital (%) | Mean Deployed Capital Fraction | Mean Order Fill Fraction | Partial Fill Events | Unfilled Order Events | Annualized Sharpe |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **$10,000** | `+$2,922.35` | `+29.22%` | `10.02%` | `72.89%` | `86.11%` | `24 / 90` | `0` | `1.635` |
| **$20,000** *(Baseline)* | **`+$5,616.56`** | **`+28.08%`** | **`10.25%`** | **`68.44%`** | **`73.94%`** | **`37 / 90`** | **`0`** | **`1.865`** |
| **$50,000** | `+$12,709.36` | `+25.42%` | `10.56%` | `60.16%` | `60.30%` | `49 / 90` | `0` | `1.909` |
| **$100,000** | `+$21,459.89` | `+21.46%` | `10.36%` | `51.73%` | `52.49%` | `54 / 90` | `0` | `1.845` |
| **$250,000** | `+$42,499.82` | `+17.00%` | `10.10%` | `42.06%` | `43.48%` | `65 / 90` | `0` | `1.832` |
| **$500,000** | `+$74,369.92` | `+14.87%` | `10.11%` | `36.76%` | `37.23%` | `69 / 90` | `0` | `1.863` |

**Capacity Finding**: While `BTCUSD` and `ETHUSD` quarterly contracts easily absorb `$50k–$250k+` per leg, secondary altcoin quarterly contracts (`ADAUSD`, `LINKUSD`, `LTCUSD`, `XRPUSD`) frequently experience thin off-peak hours where a `<= 5%` hourly volume cap restricts 4-hour TWAP fills (`mean_order_fill_fraction` drops from `86.11%` at `$10k` to `73.94%` at `$20k` and `52.49%` at `$100k`). Because historical L2 orderbooks (`depth`) and `bookTicker` quotes are not available in public archives for expired COIN-M delivery contracts, executable simulation is formally classified as:

```text
EXECUTION_PRECISION_STATUS = EXECUTION_APPROXIMATE
```

---

## Phase E — Re-Evaluation of Frozen H-1 Baseline (`MODELLED_NET_CARRY` vs `EXECUTABLE_NET_CARRY`)

### E.1 Complete Economic Scorecard (`$20,000` Initial Capital, `2022-01-01 to 2025-12-31`, Frozen H-1 Rules)

| Metric | `MODELLED_NET_CARRY` (`verified_historical_fee_schedule`, `33.0 bps`) | `MODELLED_NET_CARRY` (`standard_retail_taker`, `39.0 bps`) | **`EXECUTABLE_NET_CARRY` (`verified_historical_fee_schedule`, `33.0 bps`)** | **`EXECUTABLE_NET_CARRY` (`standard_retail_taker`, `39.0 bps`)** | **`EXECUTABLE_NET_CARRY` (`bnb_discount_if_eligible`, `34.6 bps`)** | **`EXECUTABLE_NET_CARRY` (`stressed_execution_cost`, `49.0 bps`)** |
| --- | --- | --- | --- | --- | --- | --- |
| **Initial Capital Committed** | `$20,000.00` | `$20,000.00` | **`$20,000.00`** | **`$20,000.00`** | **`$20,000.00`** | **`$20,000.00`** |
| **Final Portfolio Equity** | `$26,610.10` | `$26,297.45` | **`$25,826.60`** | **`$25,616.56`** | **`$25,773.64`** | **`$25,257.48`** |
| **Gross Economic Carry PnL** | `+$7,870.66` | `+$7,750.84` | **`+$6,936.76`** | **`+$6,914.11`** | **`+$6,931.72`** | **`+$6,867.28`** |
| **Total Fees & Slippage Paid** | `-$1,260.56` | `-$1,453.39` | **`-$1,110.16`** | **`-$1,297.55`** | **`-$1,158.09`** | **`-$1,609.80`** |
| $\quad$ *Spot Entry & Exit Fees* | `$756.26` | `$739.29` | `$650.86` | `$648.18` | `$506.94` | `$643.99` |
| $\quad$ *COIN-M Entry & Early Exit Fees* | `$225.15` | `$366.85` | `$191.64` | `$318.20` | `$319.03` | `$316.07` |
| $\quad$ *COIN-M Delivery Settlement Fees* | `$13.90` | `$13.86` | `$16.93` | `$16.84` | `$16.92` | `$16.76` |
| $\quad$ *Spread & Square-Root Impact* | `$265.24` | `$333.38` | `$250.72` | `$314.33` | `$315.19` | `$632.98` |
| **Realized Net PnL ($)** | **`+$6,610.10`** | **`+$6,297.45`** | **`+$5,826.60`** | **`+$5,616.56`** | **`+$5,773.64`** | **`+$5,257.48`** |
| **Net Return on Committed Capital** | **`+33.05%`** | **`+31.49%`** | **`+29.13%`** | **`+28.08%`** | **`+28.87%`** | **`+26.29%`** |
| **Net CAGR on Committed Capital (0% idle yield)** | **`7.39%/yr`** | **`7.08%/yr`** | **`6.60%/yr`** | **`6.38%/yr`** | **`6.54%/yr`** | **`6.00%/yr`** |
| **Mean Deployed Capital ($ / %)** | `$15,060.59` (`75.30%`) | `$15,007.47` (`75.04%`) | `$13,741.79` (`68.71%`) | `$13,687.12` (`68.44%`) | `$13,725.36` (`68.63%`) | `$13,600.75` (`68.00%`) |
| **Annualized Return on Deployed Capital** | **`10.97%/yr`** | **`10.48%/yr`** | **`10.59%/yr`** | **`10.25%/yr`** | **`10.51%/yr`** | **`9.66%/yr`** |
| **Combined CAGR (+2.5% idle USDT yield)** | `8.05%/yr` (`+$7,268.64`) | `7.74%/yr` (`+$6,952.06`) | `7.31%/yr` (`+$6,525.99`) | `7.10%/yr` (`+$6,318.13`) | `7.26%/yr` (`+$6,473.87`) | `6.74%/yr` (`+$5,962.63`) |
| **Annualized Sharpe / Sortino** | `1.556` / `1.978` | `1.491` / `1.897` | **`1.932` / `2.307`** | **`1.865` / `2.220`** | **`1.913` / `2.282`** | **`1.755` / `2.076`** |
| **Max Drawdown (%)** | `-2.39%` | `-2.39%` | **`-2.24%`** | **`-2.30%`** | **`-2.25%`** | **`-2.39%`** |
| **Empirical BTC Beta ($\beta_{\text{BTC}}$)** | `-0.0108` | `-0.0108` | **`-0.0108`** | **`-0.0108`** | **`-0.0108`** | **`-0.0108`** |
| **Position Lifecycles (`Early / Settle / Roll`)** | `78` (`70 / 6 / 3`) | `76` (`68 / 6 / 3`) | `89` (`80 / 7 / 3`) | `90` (`81 / 7 / 3`) | `89` (`80 / 7 / 3`) | `90` (`81 / 7 / 3`) |
| **Mean / Median Holding Period (Days)** | `58.29d` / `68.50d` | `59.37d` / `70.00d` | `57.40d` / `68.00d` | `57.13d` / `66.50d` | `57.40d` / `68.00d` | `57.13d` / `66.50d` |
| **Annualized Turnover** | `18.93x/yr` | `18.50x/yr` | `16.21x/yr` | `16.14x/yr` | `16.19x/yr` | `16.04x/yr` |
| **Ledger Reconciliation Residual ($)** | `-$0.0004` | `-$0.0001` | `+$0.0001` | `-$0.0002` | `+$0.0000` | `-$0.0001` |

### E.2 Annual Breakdown & Opportunity Cost Comparison (`EXECUTABLE_NET_CARRY`, `standard_retail_taker`)

| Year | Realized Net PnL ($) | Net Return on Committed Capital (%) | Mean Deployed Capital Fraction (%) | **Return on Deployed Capital (%)** | Annualized Sharpe | Max Drawdown (%) | Closed Position Lifecycles | US 3M T-Bill Avg Yield | Passive USDT Lending Avg Yield |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **2022** *(Crypto Bear / Deleveraging)* | **`+$470.38`** | `+2.35%` | `25.26%` | **`+9.31%`** | `0.945` | `-0.53%` | `10` | `2.02%` | `1.80%` |
| **2023** *(Low-Basis Consolidation)* | **`+$410.04`** | `+2.05%` | `72.15%` | **`+2.84%`** | `0.598` | `-2.30%` | `21` | `5.07%` | `2.50%` |
| **2024** *(ETF Bull Contango Expansion)* | **`+$3,499.49`** | `+17.50%` | `100.29%` | **`+17.45%`** | `3.441` | `-1.64%` | `26` | `5.25%` | `3.20%` |
| **2025** *(Late-Cycle Contango / Compression)* | **`+$1,252.91`** | `+6.26%` | `75.96%` | **`+8.25%`** | `1.988` | `-0.61%` | `31` | `3.05%` | `2.50%` |
| **Full 2022–2025 (`4.00 yrs`)** | **`+$5,616.56`** | **`+28.08%` (`6.38%` CAGR)** | **`68.44%`** | **`+10.25%/yr`** | **`1.865`** | **`-2.30%`** | **`90`** | **`3.85%/yr`** | **`2.50%/yr`** |

**Honest Opportunity Cost Assessment**:
- Over the full `2022–2025` cycle, `EXECUTABLE_NET_CARRY` (`standard_retail_taker`) generated **`10.25%/yr` annualized on actively deployed capital** and **`6.38%/yr` CAGR on total committed capital** assuming `0.0%` yield on idle cash (`7.10%/yr` CAGR when idle cash earns `2.5%/yr` passive USDT lending), outperforming both the 4-year average US 3-Month T-Bill yield (`3.85%/yr`) and passive USDT lending (`2.50%/yr`) with zero directional crypto market exposure ($\beta_{\text{BTC}} = -0.0108$).
- However, return generation is **strongly regime-dependent**:
  - In **2022**, quarterly contango disappeared after Q1 2022; the strategy stayed **`74.74%` in cash**, earning **`+9.31%` on deployed capital** (`+2.35%` on total committed capital) with a `-0.53%` max drawdown while Spot BTC fell `-64%`.
  - In **2023**, moderate contango returned (`72.15%` mean deployed capital) with thin basis spreads, earning **`+2.84%` on deployed capital** (`+2.05%` on committed capital)—which **underperformed** the 2023 US 3M T-Bill rate (`5.07%`), though remaining net positive after all retail taker fees.
  - In **2024 and 2025**, wide quarterly basis (`150–400+ bps`) generated **`+17.45%` and `+8.25%` on deployed capital** (`+17.50%` and `+6.26%` on committed capital), driving the bulk of the 4-year dollar profit.

### E.3 Statistical Uncertainty Across Position Lifecycles & Quarterly Expiry Cycles

Because quarterly delivery contracts share common expiry dates and holding periods averaging `57.1 days`, 7-day block bootstraps overstate effective sample size. N1.5 evaluates uncertainty at the two true structural units of the strategy ([`neural_trading/n1_5/coinm_simulator.py`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_5/coinm_simulator.py#L510-L535)):

| Fee Scenario (`EXECUTABLE_NET_CARRY`) | Closed Position Lifecycles ($N_{\text{pos}}$) | Position Lifecycle $t$-stat | Position Lifecycle 95% Bootstrap CI ($) | Quarterly Expiry Cycles ($N_{\text{qtr}}$) | Quarterly Cycle $t$-stat | Quarterly Cycle 95% Bootstrap CI ($) | Positive Quarters |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `verified_historical_fee_schedule` (`33.0 bps`) | `89` | **`7.138`** | **`[+$4,390.00, +$7,442.20]`** | `17` | **`3.217`** | **`[+$2,820.93, +$9,726.95]`** | `15 / 17` (`88.2%`) |
| `standard_retail_taker` (`39.0 bps`) | `90` | **`6.923`** | **`[+$4,086.06, +$7,170.00]`** | `17` | **`3.111`** | **`[+$2,609.02, +$9,493.06]`** | `13 / 17` (`76.5%`) |
| `bnb_discount_if_eligible` (`34.6 bps`) | `89` | **`7.103`** | **`[+$4,342.26, +$7,385.27]`** | `17` | **`3.187`** | **`[+$2,767.98, +$9,670.63]`** | `15 / 17` (`88.2%`) |
| `stressed_execution_cost` (`49.0 bps`) | `90` | **`6.555`** | **`[+$3,753.43, +$6,770.19]`** | `17` | **`2.943`** | **`[+$2,293.91, +$9,098.05]`** | `12 / 17` (`70.6%`) |

Even when aggregated into `17` non-overlapping quarterly expiry cycles (`220325` through `260327`), the lower bound of the 95% bootstrap confidence interval remains **`+$2,609.02`** under `standard_retail_taker` ($t = 3.111$) and **`+$2,293.91`** under `stressed_execution_cost` ($t = 2.943$).

---

## Phase F — Final Research Decision & Forward Observation Specification

### F.1 Final Decision

```text
FINAL_H1_DISPOSITION                   = H1_EXPLORATORY_NET_CARRY_SUPPORTED
EXECUTION_PRECISION_STATUS             = EXECUTION_APPROXIMATE
H1_HISTORICAL_MARGIN_REPLAY            = INSUFFICIENT
NEURAL_INCREMENTAL_VALUE_DISPOSITION   = NEURAL_INCREMENTAL_VALUE_NOT_SUPPORTED
EVALUATION_2022_2025_STATUS            = ADAPTIVE_DEVELOPMENT_NOT_INDEPENDENT_CONFIRMATION
```

Why is the verdict `H1_EXPLORATORY_NET_CARRY_SUPPORTED` (and **not** immediate production candidacy)?
1. **Economic Survival Confirmed**: The frozen `H-1` dated quarterly delivery basis carry mechanism survives physical COIN-M inverse contract sizing, base-coin collateral accounting, official 30-minute (`07:30..08:00 UTC`) Price Index TWAP settlement, `5.0 bps` COIN-M taker/settlement fees without BNB discount eligibility, and `<= 5%` hourly volume participation caps (`+$5,616.56` / `+28.08%` under `standard_retail_taker`, `+$5,257.48` / `+26.29%` under `stressed_execution_cost`, positive in all 4 calendar years `2022–2025`).
2. **Execution & Sub-Minute Margin Replay Remain Approximate**: Because public historical archives do not contain expired COIN-M L1/L2 orderbooks (`bookTicker`/`depth`) or sub-minute Mark Price tick streams, execution slippage (`EXECUTION_APPROXIMATE`) and sub-minute flash-wick margin / ADL behavior (`H1_HISTORICAL_MARGIN_REPLAY = INSUFFICIENT`) cannot be proven from historical archives alone.
3. **Zero Neural Incremental Value**: The edge is entirely structural (capturing the contango risk premium of dated inverse delivery futures and holding to convergence/settlement). As established in N1.4, neural policies do not improve upon the 3-parameter rule-based carry baseline (`NEURAL_INCREMENTAL_VALUE_NOT_SUPPORTED`).
4. **Adaptive Reuse of 2022–2025**: Because the `2022–2025` window was used across earlier research iterations, it is classified strictly as `ADAPTIVE_DEVELOPMENT_NOT_INDEPENDENT_CONFIRMATION`.

### F.2 Research-Only Forward Observation Specification (No Live Trading / No Paper Trading Daemon)

To resolve `EXECUTION_APPROXIMATE` and `H1_HISTORICAL_MARGIN_REPLAY = INSUFFICIENT` on out-of-sample data without risking capital or running an execution daemon, any future prospective validation of `H-1` requires a **passive, read-only market observation logger** (currently kept `STOPPED` per governance rules until explicitly authorized) that records:

1. **Synchronized L1 Bid/Ask Spread & Top-of-Book Depth (`bookTicker` & `depth5`)**:
   - Spot `GET /api/v3/ticker/bookTicker` (`bidPrice`, `bidQty`, `askPrice`, `askQty`) and COIN-M `GET /dapi/v1/ticker/bookTicker` (`BTCUSD_YYMMDD`, `ETHUSD_YYMMDD`, etc.) sampled every 60 seconds.
   - Measures the **exact executable entry basis** $\text{Basis}_{\text{exec, in}} = \frac{F_{\text{bid}} - S_{\text{ask}}}{S_{\text{ask}}}$ and **executable exit basis** $\text{Basis}_{\text{exec, out}} = \frac{F_{\text{ask}} - S_{\text{bid}}}{S_{\text{bid}}}$ against the `1.75–2.25 bps/leg` half-spread assumption.
2. **1-Second Mark Price, Index Price & ADL Quantile Stream (`markPriceUpdate`)**:
   - Captures sub-minute `markPrice` vs `indexPrice` dislocations during high-volatility cascades to measure the empirical distribution of intrabar basis spikes $F_{\text{mark}} / S - 1$.
3. **30-Minute Delivery Settlement Window (`07:30:00 to 08:00:00 UTC` on Quarterly Fridays)**:
   - Logs 1-second `indexPrice` ticks during the 30-minute settlement window and compares the computed arithmetic mean against Binance's official published delivery settlement price and the `07:50..08:00 UTC` `Reduce-Only` orderbook spread.
4. **Strict Non-Execution Guardrail**:
   - Zero API trading keys, zero order placement, `PROSPECTIVE_COLLECTOR = STOPPED`, and `REAL_TRADING = DISABLED`.
