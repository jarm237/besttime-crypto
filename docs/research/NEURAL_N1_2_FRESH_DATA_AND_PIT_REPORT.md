# N1.2 — Fresh Data Acquisition & Point-in-Time (PIT) Provenance Report

**Document ID**: `NEURAL-N1-2-FRESH-DATA-AND-PIT-REPORT-2026-11-11`  
**Status**: `COMPLETED — 100% CHECKSUM & 10-FIELD PROVENANCE VERIFIED`  
**Workspace**: `D:\Workspaces\besttime-crypto`  
**Acquisition Module**: [`neural_trading/n1_2/acquisition.py`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_2/acquisition.py)  
**Runner Script**: [`scripts/n1_2_acquire_fresh_data.py`](file:///d:/Workspaces/besttime-crypto/scripts/n1_2_acquire_fresh_data.py)

---

## 1. Executive Summary of Fresh Data Acquisition

In accordance with **N1.2 Phase C (Objective-Driven Fresh Data Acquisition)**, we acquired three independent, high-resolution raw datasets directly from authoritative exchange archives without synthesizing order flow or recycling rejected HMR-V4A features:

| Dataset ID | Target Hypothesis | Authoritative Source Endpoint | Coverage & Granularity | Raw Volume Processed | Checksum / Integrity Verification | Canonical Manifest Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`N1_2_HA_SPOT_AGGTRADES_2022_2025`** | **H-A** (Tick-Level Order-Flow & Sweep Dislocation) | `https://data.binance.vision/data/spot/monthly/aggTrades/<SYM>/` | 5 Spot symbols (`ADA, ETC, LINK, TRX, XLM`), `2022-01..2025-12` (240 monthly archives), tick-by-tick `aggTrades` | **555,512,482** raw tick `aggTrades` (`8,700,611,361` bytes = `8.30 GB` compressed) | **240 / 240 (`100%`)** verified against official `.CHECKSUM` SHA-256 | [`n1_2_aggtrades_manifest.json`](file:///d:/Workspaces/besttime-crypto/research/neural_n1_2/manifests/n1_2_aggtrades_manifest.json) |
| **`N1_2_HB1_COINBASE_USD_1H_2022_2025`** | **H-B1** (Cross-Venue Fiat USD vs Offshore USDT Discovery) | `https://api.exchange.coinbase.com/products/<SYM>-USD/candles?granularity=3600` | 8 USD Spot pairs (`BTC, ETH, SOL, LTC, LINK, ADA, XRP, DOGE`), `2022-01-01..2025-12-31`, 1h candles | **267,029** raw 1h USD candles (`8` raw JSON payload archives saved) | **8 / 8 (`100%`)** raw JSON payload SHA-256 sealed | [`n1_2_coinbase_cross_venue_manifest.json`](file:///d:/Workspaces/besttime-crypto/research/neural_n1_2/manifests/n1_2_coinbase_cross_venue_manifest.json) |
| **`N1_2_HB2_BINANCE_5M_PERP_VS_SPOT_2022_2025`** | **H-B2** (5m Perpetual vs 5m Spot Intraday Lead-Lag) | `https://data.binance.vision/data/futures/um/monthly/klines/<SYM>/5m/` & `data/spot/monthly/klines/<SYM>/5m/` | 8 symbols (`BTC, ETH, SOL, LTC, LINK, ADA, XRP, DOGE`), `2022-01..2025-12` (384 symbol-months = 768 archives), `5m` bars | **3,361,696** synchronized 5m Perp + Spot bar pairs (`6,723,392` 5m bars) | **768 / 768 (`100%`)** verified against official `.CHECKSUM` SHA-256 | [`n1_2_5m_perp_spot_manifest.json`](file:///d:/Workspaces/besttime-crypto/research/neural_n1_2/manifests/n1_2_5m_perp_spot_manifest.json) |

Summary artifact: [`research/neural_n1_2/manifests/n1_2_acquisition_summary.json`](file:///d:/Workspaces/besttime-crypto/research/neural_n1_2/manifests/n1_2_acquisition_summary.json).

---

## 2. Mandatory 10-Field Point-in-Time (PIT) Provenance Contract Verification

Every single archive record across all three manifests (`240` records in `n1_2_aggtrades_manifest.json`, `8` records in `n1_2_coinbase_cross_venue_manifest.json`, and `384` records in `n1_2_5m_perp_spot_manifest.json`) is programmatically verified by [`tests/test_neural_n1_2.py`](file:///d:/Workspaces/besttime-crypto/tests/test_neural_n1_2.py) to contain all 10 mandatory contract fields:

| Mandatory Field | Implementation & Verification Rule in `neural_trading/n1_2/acquisition.py` | Example Verified Value (`ADAUSDT-aggTrades-2024-01`) |
| :--- | :--- | :--- |
| 1. `source` | Exact authoritative HTTPS URL of the raw archive or REST endpoint | `https://data.binance.vision/data/spot/monthly/aggTrades/ADAUSDT/ADAUSDT-aggTrades-2024-01.zip` |
| 2. `original_timestamp` | Exact UTC timestamp span (`first_trade_ts..last_trade_ts`) inside the raw payload | `2024-01-01T00:00:00Z..2024-01-31T23:59:59Z` |
| 3. `actual_availability_timestamp` | Point-in-time close timestamp when the bar/archive becomes causally available for decision making | `2024-02-01T00:00:00Z` (each 1h bucket closes at `hour_close_ms = ((ts_ms // 3600000) + 1) * 3600000`, `0 ms` lookahead) |
| 4. `ingestion_timestamp` | Exact UTC wall-clock timestamp when the file was fetched and verified | `2026-11-11T08:25:14Z` |
| 5. `raw_payload` | Archive filename, compressed byte size, exact row/candle count, schema, and derived parquet path | `{"archive_name": "ADAUSDT-aggTrades-2024-01.zip", "compressed_bytes": ..., "raw_aggtrade_rows": ...}` |
| 6. `source_checksum` | Authoritative SHA-256 extracted from `.CHECKSUM` (or sealed REST payload digest) | Official 64-hex SHA-256 string from `.zip.CHECKSUM` |
| 7. `local_sha256` | Locally computed SHA-256 digest of the downloaded raw bytes (`assert local_sha256 == source_checksum`) | Matching 64-hex SHA-256 string (`checksum_verified: true`) |
| 8. `trading_eligibility` | Explicit eligibility scope (`SIGNAL_ONLY` for Coinbase USD; `ELIGIBLE_RESEARCH_AND_BACKTEST_LONG_ONLY_SPOT` for Binance Spot) | `ELIGIBLE_RESEARCH_AND_BACKTEST_LONG_ONLY_SPOT` |
| 9. `missing_intervals` | Exact count of expected vs actual 1h/5m bars and any exchange maintenance/outage intervals | `{"expected_hourly_bars": 744, "actual_hourly_bars": 744, "missing_hourly_bars": 0}` |
| 10. `execution_constraints` | Venue rules, short-selling prohibition (`False`), fee/slippage (`14 bps RT`), and cross-venue latency rules | `{"venue": "BINANCE_SPOT", "short_selling_allowed": false, "round_trip_fee_slippage_bps": 14.0}` |

---

## 3. Critical Technical Audit Findings During Acquisition

### 3.1 Microsecond Timestamp Transition in 2025 Binance Spot Archives
During tick-by-tick ingestion of `2025` Spot `aggTrades` and `5m` Spot klines, we detected that Binance migrated Spot archive timestamps from **13-digit milliseconds (`1735689600000`)** to **16-digit microseconds (`1735689600000000`)** starting in January 2025.
- **Resolution in [`acquisition.py`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_2/acquisition.py#L194-L196)**: All raw timestamps are normalized via `ts_ms = np.where(ts_raw > 10**14, ts_raw // 1000, ts_raw)` prior to hour bucketing. Without this normalization, 2025 timestamps would overflow by $1000\times$ and corrupt point-in-time alignment.

### 3.2 Exchange Maintenance & Venue Outage Accounting (`missing_intervals`)
- **Binance Spot Maintenance Windows (2022–2023)**: Across the 4-year span (`35,064` calendar hours), each Binance Spot symbol has `35,062` active hours (`2` missing hours corresponding to the documented 2023-03-24 Binance system maintenance window). No synthetic bars were interpolated across maintenance windows.
- **Coinbase Exchange `SYM-USD` Coverage (`2022–2025`)**:
  - `BTC-USD`, `ETH-USD`, `LTC-USD`, `LINK-USD`, `ADA-USD`, `DOGE-USD` have `35,038` to `35,041` hourly bars out of `35,064` (`99.93%` completeness; ~23 hours of scheduled Coinbase maintenance over 4 years).
  - `SOL-USD` has `34,885` bars (`99.49%` completeness).
  - `XRP-USD` has `21,908` bars (`62.48%` completeness) because Coinbase suspended `XRP-USD` trading during the SEC litigation period prior to relisting in July 2023. During all hours where `XRP-USD` is absent on Coinbase, the cross-venue feature builder sets `XRP` cross-venue shocks to neutral (`0.0`) rather than fabricating prices.

### 3.3 Documented Rejection of Unsuitable Sources (`bookTicker` & `allForceOrders`)
Per Phase C rules (*"Nếu nguồn thiếu lịch sử quan trọng hoặc không cho phép tái hiện thông tin có sẵn tại thời điểm giao dịch, kết luận source không phù hợp"*), [`probe_unsuitable_sources()`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1_2/acquisition.py#L99-L137) probed and formally rejected:
1. `data.binance.vision/data/futures/um/daily/bookTicker/...` (`HTTP 404 Not Found` across 2023 and 2024 dates — historical L1 `bookTicker` archives were removed by Binance).
2. `data.binance.vision/data/spot/daily/bookTicker/...` (`HTTP 404 Not Found`).
3. `fapi.binance.com/fapi/v1/allForceOrders` (`HTTP 404` / restricted from public historical backfill).

All four probes and their formal rejection dispositions are recorded in [`research/neural_n1_2/manifests/n1_2_rejected_sources_probe.json`](file:///d:/Workspaces/besttime-crypto/research/neural_n1_2/manifests/n1_2_rejected_sources_probe.json).

---

## 4. Canonical Panel Artifacts on Disk

| Panel File | SHA-256 Digest | Rows | Schema Summary |
| :--- | :--- | :---: | :--- |
| [`data/neural_n1_2/n1_2_ha_aggtrades_hourly_panel.parquet`](file:///d:/Workspaces/besttime-crypto/data/neural_n1_2/n1_2_ha_aggtrades_hourly_panel.parquet) | `47b51b43e0d770bd3163db237cc65fb107b5dcedc2e6df3333715951a087f8d2` | `175,310` | 5 symbols $\times$ 35,062 hours; 25 columns of tick-aggregated whale/retail OFI, sweep order counts, bounce spreads, and tick price impacts |
| [`data/neural_n1_2/n1_2_hb1_coinbase_1h_panel.parquet`](file:///d:/Workspaces/besttime-crypto/data/neural_n1_2/n1_2_hb1_coinbase_1h_panel.parquet) | `ae3e7ea90c727885216ff9c4c5bef3e327bc370ef7cf3fb1cbca3ad0138108db` | `267,029` | 8 symbols (`SYM-USD`), 1h OHLC, base volume, USD notional, `hour_close_ms` |
| [`data/neural_n1_2/n1_2_hb2_5m_perp_spot_hourly_panel.parquet`](file:///d:/Workspaces/besttime-crypto/data/neural_n1_2/n1_2_hb2_5m_perp_spot_hourly_panel.parquet) | `7012f48344df440bf1a3c05d9f99deac8873e0992978ad17f9331b55594ed971` | `280,496` | 8 symbols $\times$ 35,062 hours; 27 columns of 5m Perp vs Spot basis open/close/min/max, last-15m lead-lag, and 5m realized variance |
