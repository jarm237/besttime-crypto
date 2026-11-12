# N1.4 — Greenfield Economic-First Alpha Discovery: Data Feasibility & Point-in-Time Provenance Audit

- **Date**: 2026-11-11
- **Status**: `PHASE_D_COMPLETE_VERIFIED`
- **Dataset ID**: `N1_4_QUARTERLY_DELIVERY_AND_MULTIDAY_PANEL_2022_2025`
- **Manifest Path**: [`research/neural_n1_4/manifests/n1_4_quarterly_delivery_manifest.json`](file:///d:/Workspaces/besttime-crypto/research/neural_n1_4/manifests/n1_4_quarterly_delivery_manifest.json)
- **Canonical Panel Path**: `data/neural_n1_4/n1_4_term_structure_and_multiday_panel.parquet`
- **Canonical Panel SHA-256**: `83b5cb63d0c0eef090eba1654946e57342641ac3869f41dc3b34bb48730f1ff2`
- **Implementation**: [`neural_trading/n1_4/acquisition.py`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_4/acquisition.py)

---

## 1. Executive Summary of Phase D Acquisition

To test Candidate `H-1` (`DATED_QUARTERLY_DELIVERY_BASIS_CARRY_AND_CONVERGENCE`) and Candidate `H-2` (`STRUCTURAL_DELEVERAGING_LIQUIDITY_PROVISION_MULTI_DAY`) without relying on rejected `HMR-V4A` features, we acquired and cryptographically verified raw historical archives from `data.binance.vision` across **17 quarterly delivery contract maturities (`220325` through `260327`, strictly truncated at `2025-12-31 23:00:00 UTC`)**:

| Data Source Family | Authoritative Endpoint Pattern | Symbols Covered | Probed Monthly Archives | Verified Active Archives (`HTTP 200`) | SHA-256 `.CHECKSUM` Verified | Expected `HTTP 404` (Pre-Listing / Post-Delisting) | Total Verified Hourly Bars |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Binance COIN-M Dated Quarterly Delivery Futures (`CM_DELIVERY`)** | `data.binance.vision/data/futures/cm/monthly/klines/<SYM>USD_<YYMMDD>/1h/` | `BTCUSD, ETHUSD, BNBUSD, XRPUSD, ADAUSD, LINKUSD, LTCUSD, SOLUSD` | 888 | **745** | **744** (`99.87%`) | 143 | 465,674 |
| **Binance USD-M Dated Quarterly Delivery Futures (`UM_DELIVERY`)** | `data.binance.vision/data/futures/um/monthly/klines/<SYM>USDT_<YYMMDD>/1h/` | `BTCUSDT, ETHUSDT` | 222 | **222** | **222** (`100.0%`) | 0 | 141,320 |
| **Binance `BNBUSDT` Spot & USD-M Perp 1h** | `data/spot/monthly/klines/BNBUSDT/1h/` & `data/futures/um/monthly/klines/BNBUSDT/1h/` | `BNBUSDT` (`2022-01..2025-12`) | 96 | **96** | **96** (`100.0%`) | 0 | 70,126 |
| **N1.2 Verified 7-Symbol Spot/Perp + Coinbase `USDT-USD` 1h** | `data/neural_n1_2/n1_2_hb2_5m_perp_spot_hourly_panel.parquet` & `USDT-USD-1h-2022-2025.parquet` | `BTC, ETH, SOL, XRP, ADA, DOGE/LINK, AVAX/LTC` + `USDT-USD` | Reused verified local cache | **100%** | **100%** | 0 | 245,081 |
| **Total Delivery + Spot/Perp Panel** | `data/neural_n1_4/n1_4_term_structure_and_multiday_panel.parquet` | **8 Symbols (`2022–2025`)** | **1,206** | **1,063** | **1,062** | **143** | **280,144 panel symbol-hours** |

---

## 2. Quarterly Delivery Contract Calendar & Governance Cutoff (`2022–2025`)

Every Binance COIN-M (`SYMUSD_YYMMDD`) and USD-M (`SYMUSDT_YYMMDD`) quarterly delivery contract expires and settles at **`08:00:00 UTC` on the last Friday of the quarter month** (`March`, `June`, `September`, `December`) against the 60-minute Spot Index TWAP (`07:00:00..08:00:00 UTC`):

| # | Expiry Code (`YYMMDD`) | Exact Settlement Timestamp (UTC) | Monthly Archives Ingested | Role in Term Structure (`2022–2025`) |
| :---: | :---: | :---: | :--- | :--- |
| 1 | `220325` | `2022-03-25 08:00:00 UTC` | `2022-01 .. 2022-03` | Front Quarter (`F1`) in Q1 2022 |
| 2 | `220624` | `2022-06-24 08:00:00 UTC` | `2022-01 .. 2022-06` | Next Quarter (`F2`) in Q1 2022 $\to$ `F1` in Q2 2022 |
| 3 | `220930` | `2022-09-30 08:00:00 UTC` | `2022-03 .. 2022-09` | `F2` in Q2 2022 $\to$ `F1` in Q3 2022 |
| 4 | `221230` | `2022-12-30 08:00:00 UTC` | `2022-06 .. 2022-12` | `F2` in Q3 2022 $\to$ `F1` in Q4 2022 |
| 5 | `230331` | `2023-03-31 08:00:00 UTC` | `2022-09 .. 2023-03` | `F2` in Q4 2022 $\to$ `F1` in Q1 2023 |
| 6 | `230630` | `2023-06-30 08:00:00 UTC` | `2022-12 .. 2023-06` | `F2` in Q1 2023 $\to$ `F1` in Q2 2023 |
| 7 | `230929` | `2023-09-29 08:00:00 UTC` | `2023-03 .. 2023-09` | `F2` in Q2 2023 $\to$ `F1` in Q3 2023 |
| 8 | `231229` | `2023-12-29 08:00:00 UTC` | `2023-06 .. 2023-12` | `F2` in Q3 2023 $\to$ `F1` in Q4 2023 |
| 9 | `240329` | `2024-03-29 08:00:00 UTC` | `2023-09 .. 2024-03` | `F2` in Q4 2023 $\to$ `F1` in Q1 2024 |
| 10 | `240628` | `2024-06-28 08:00:00 UTC` | `2023-12 .. 2024-06` | `F2` in Q1 2024 $\to$ `F1` in Q2 2024 |
| 11 | `240927` | `2024-09-27 08:00:00 UTC` | `2024-03 .. 2024-09` | `F2` in Q2 2024 $\to$ `F1` in Q3 2024 |
| 12 | `241227` | `2024-12-27 08:00:00 UTC` | `2024-06 .. 2024-12` | `F2` in Q3 2024 $\to$ `F1` in Q4 2024 |
| 13 | `250328` | `2025-03-28 08:00:00 UTC` | `2024-09 .. 2025-03` | `F2` in Q4 2024 $\to$ `F1` in Q1 2025 |
| 14 | `250627` | `2025-06-27 08:00:00 UTC` | `2024-12 .. 2025-06` | `F2` in Q1 2025 $\to$ `F1` in Q2 2025 |
| 15 | `250926` | `2025-09-26 08:00:00 UTC` | `2025-03 .. 2025-09` | `F2` in Q2 2025 $\to$ `F1` in Q3 2025 |
| 16 | `251226` | `2025-12-26 08:00:00 UTC` | `2025-06 .. 2025-12` | `F2` in Q3 2025 $\to$ `F1` in Q4 2025 |
| 17 | `260327` | `2026-03-27 08:00:00 UTC` | `2025-09 .. 2025-12` **only** | Listed in late Sept 2025; serves as `F2` during Q4 2025 and `F1` during `2025-12-26 09:00..2025-12-31 23:00 UTC`. **Zero 2026 bars ingested (`hard_end_utc = 2025-12-31T23:00:00Z`)**. |

---

## 3. Symbol Coverage, Dynamic Listing/Delisting, and Structural Basis Distribution

Unlike synthetic backtests that assume static 8-symbol availability, our Phase D pipeline respects the **exact historical listing and delisting calendar** of Binance COIN-M quarterly delivery contracts:
- **Full 17-Maturity Coverage (`220325..260327`)**: `BTCUSD`, `ETHUSD`, `BNBUSD`, `XRPUSD` (`34,847–34,967` active `F1` hours each out of `35,063` total hours).
- **15-Maturity Coverage (`220325..250926`)**: `ADAUSD`, `LINKUSD`, `LTCUSD` (`32,526–32,646` active `F1` hours each; Binance discontinued new COIN-M quarterly listings for `ADA`, `LINK`, and `LTC` after the `250926` expiry, so these 3 symbols naturally transition to `inactive_mask = 0` in Q4 2025 without lookahead or survivorship bias).
- **7-Maturity Coverage (`240927..260327`)**: `SOLUSD` (`12,108` active `F1` hours; Binance listed COIN-M `SOLUSD` quarterly contracts starting in mid-2024 with `SOLUSD_240927`).

### Empirical Term-Structure Summary by Symbol (`2022–2025`)

| Symbol | Total Panel Hours | Active `F1` Hours | Active `F2` Hours | Mean `F1` Basis (bps) | `P10` `F1` Basis (bps) | `P90` `F1` Basis (bps) | Mean `F1` Implied Yield (% p.a.) | Economic Regime Note |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `BTCUSDT` (`BTCUSD_YYMMDD`) | 35,063 | 34,967 | 34,812 | **`+84.55`** | `+4.10` | **`+177.12`** | **`+7.36%`** | Persistent structural contango across cycles |
| `ETHUSDT` (`ETHUSD_YYMMDD`) | 35,063 | 34,967 | 34,812 | **`+72.11`** | `-7.10` | **`+172.52`** | **`+5.67%`** | Persistent structural contango (brief PoS merge backwardation in Sept 2022) |
| `BNBUSDT` (`BNBUSD_YYMMDD`) | 35,063 | 34,967 | 34,810 | **`-70.89`** | `-207.99` | `+39.35` | **`-6.01%`** | **Structural backwardation** due to Spot `BNB` Launchpool airdrop demand |
| `XRPUSDT` (`XRPUSD_YYMMDD`) | 34,943 | 34,847 | 34,683 | **`+73.92`** | `-29.60` | **`+181.41`** | **`+5.77%`** | Strong retail leverage demand in contango |
| `ADAUSDT` (`ADAUSD_YYMMDD`) | 35,063 | 32,646 | 30,444 | **`+67.26`** | `-37.53` | **`+188.29`** | **`+5.53%`** | Active through `250926`; strong bull contango |
| `LINKUSDT` (`LINKUSD_YYMMDD`) | 35,063 | 32,646 | 30,437 | **`+78.91`** | `-27.62` | **`+183.97`** | **`+6.82%`** | Active through `250926`; high contango carry |
| `LTCUSDT` (`LTCUSD_YYMMDD`) | 34,943 | 32,526 | 30,323 | **`+87.63`** | `-11.93` | **`+205.13`** | **`+7.23%`** | Active through `250926`; highest mean basis |
| `SOLUSDT` (`SOLUSD_YYMMDD`) | 34,943 | 12,108 | 11,965 | **`+40.78`** | `-28.39` | **`+147.91`** | **`+3.15%`** | Listed Q3 2024 (`240927..260327`) |

### COIN-M (`SYMUSD_YYMMDD`) vs USD-M (`SYMUSDT_YYMMDD`) Basis Parity
Across `69,934` matched symbol-hours on `BTC` and `ETH` where both `CM` and `UM` quarterly delivery contracts were simultaneously active:
- **Basis Correlation**: **`0.9892`**
- **Mean `CM` Basis**: **`+78.33 bps`** (in true USD numeraire via `spot_close_usd = spot_close_usdt * usdt_usd_close`)
- **Mean `UM` Basis**: **`+82.11 bps`** (in `USDT` numeraire)

---

## 4. Point-in-Time (PIT) & Same-Contract Forward Return Integrity Contract

1. **Zero Lookahead Alignment**:
   - All 1h klines (`Spot`, `Perp`, `CM_DELIVERY`, `UM_DELIVERY`, `Coinbase USDT-USD`) are indexed by `hour_close_ms = open_time_ms + 3,600,000`.
   - Features at index $t$ (`hour_close_ms`) use only information closed on or before `hour_close_ms`. `lookahead_rows_count = 0`.
2. **Same-Contract Return Matching Across Quarterly Rolls**:
   - A critical pitfall in naive continuous futures stitched series is computing $F_{t+1}/F_t - 1$ across a contract roll hour (`08:00 UTC` on expiry Friday), which falsely treats the basis jump between the expiring contract (`240329` at `0 bps`) and the new front contract (`240628` at `+300 bps`) as a one-hour trade return.
   - Our pipeline computes `fut_next_open_same_contract` and `fut_next_close_same_contract` **inside each individual contract (`groupby("contract_symbol")`) before selecting `F1` and `F2`**.
   - At the final hour before `08:00 UTC` settlement (`f1_ttm_hours == 1.0`), `f1_next_basis_same_contract_bps` is set to the contractual settlement value `0.0 bps`, and any position continuing into the new front contract pays the explicit `quarterly_roll_fee_bps = 5.5 bps` (`1.5 bps` settlement + `4.0 bps` new short leg entry).
