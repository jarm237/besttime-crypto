# NEURAL N1 — Fresh Market Data Acquisition & Provenance Report

**Date**: 2026-11-11  
**Workspace**: `D:\Workspaces\besttime-crypto`  
**Acquisition Module**: [`neural_trading/n1/acquisition.py`](file:///d:/Workspaces/besttime-crypto/neural_trading/n1/acquisition.py)  
**Acquisition Script**: [`scripts/n1_acquire_market_data.py`](file:///d:/Workspaces/besttime-crypto/scripts/n1_acquire_market_data.py)  
**Authoritative Manifests**:
- [`research/neural_n1/manifests/n1_spot_klines_1h_manifest.json`](file:///d:/Workspaces/besttime-crypto/research/neural_n1/manifests/n1_spot_klines_1h_manifest.json)
- [`research/neural_n1/manifests/n1_um_bookdepth_manifest.json`](file:///d:/Workspaces/besttime-crypto/research/neural_n1/manifests/n1_um_bookdepth_manifest.json)

---

## 1. Why Fresh Acquisition Was Required

An audit of the prior N0–N0.3 data provenance revealed three material gaps:
1. The N0.2 report cited a non-existent directory (`data/historical/binance_spot_1h/`), whereas local files lived in `data/historical/raw/binance_spot/`.
2. The SHA-256 hashes recorded in `neural_n0_2_greenfield_market_data_manifest.json` were computed only on local CSV files and were **never cross-checked against Binance's published `.CHECKSUM` files**.
3. The N0–N0.3 dataset covered only 5 pairs over 2023–2025 and discarded all non-price columns (`volume`, `quote_volume`, `trades`, `taker_buy_base`, `taker_buy_quote`).

For N1, we executed an independent, byte-for-byte fresh download directly from `https://data.binance.vision` for both selected hypotheses (**H1** and **H2**), verifying every `.zip` payload against its companion `.zip.CHECKSUM` file published by Binance.

---

## 2. Mandatory Phase C Provenance Contract Fields

```text
================================================================================
N1 DATA ACQUISITION PROVENANCE CONTRACT
================================================================================
dataset_version               = n1-acq-v1
hard_end_boundary             = 2025-12-31 (2026 burned holdout never requested)
checksum_verification_policy  = SHA-256 of raw .zip matched against official .zip.CHECKSUM
total_verified_raw_archives   = 3,355 zip files (1,168 Spot monthly + 2,187 bookDepth daily)
checksum_mismatch_count       = 0
total_compressed_bytes        = 1,050,256,881 bytes (~1.05 GB)
================================================================================
```

### Dataset 1 — Multi-Regime Spot 1h Klines (`H1`)

| Contract Field | Specification |
| :--- | :--- |
| **`source_identity`** | `binance_vision_spot_monthly_klines` |
| **`official_download_location`** | `https://data.binance.vision/data/spot/monthly/klines/<SYMBOL>/1h/<SYMBOL>-1h-<YYYY-MM>.zip` (+ `.CHECKSUM`) |
| **`raw_payload_hash`** | Per-file SHA-256 digest of the raw `.zip` bytes, verified equal to the first field of `<SYMBOL>-1h-<YYYY-MM>.zip.CHECKSUM` (all 1,168 files recorded in `n1_spot_klines_1h_manifest.json`). |
| **`event_time`** | Kline `open_time` (UTC epoch; millisecond integer through `2024-12`, microsecond integer from `2025-01` onward, normalized to UTC seconds in `pit_dataset.py`). Covers $[t_0, t_0 + 3600\text{s})$. |
| **`available_at`** | Strictly $t_{\text{avail}} = t_0 + 3600\text{s}$ (bar close boundary; a 1h kline is complete only after `close_time`). |
| **`ingestion_time`** | `2026-11-11T06:32:49Z` – `2026-11-11T06:33:07Z` (per-file ISO-8601 UTC timestamp in manifest). |
| **`symbol_eligibility`** | 13 Spot USDT pairs (`BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `LTCUSDT`, `ADAUSDT`, `XRPUSDT`, `EOSUSDT`, `XLMUSDT`, `TRXUSDT`, `ETCUSDT`, `LINKUSDT`, `DOGEUSDT`, `SOLUSDT`). Includes `EOSUSDT` (delisted May 2025) to test delisting handling and reduce survivorship bias; dynamic active mask $\mathcal{U}_t$ requires a valid bar at $t$ and 168h trailing history. |
| **`missing_intervals`** | Pre-listing months verified via 6-month lookback probes (all returned HTTP 404). `EOSUSDT` returns HTTP 404 for `2025-06`..`2025-12` following delisting. Historical Binance exchange maintenance halts (e.g., 2018-02-08, 2018-07-04, 2019-05-15, 2020-02-19, 2021-04-25, 2023-03-24 13:00 UTC) appear as absent hourly rows and are left un-imputed (`NaN`). |
| **`revision_or_correction_policy`** | Raw `.zip` files and `.sha256` sidecars are immutable once written. If Binance republishes a monthly archive with a different `.CHECKSUM`, ingestion flags a version change and requires bumping `dataset_version`. |
| **`dataset_version`** | `n1-acq-v1` |

#### Per-Symbol Verified Coverage Summary (`H1`)

| Symbol | Verified Monthly Zips | First Month | Last Month | Pre/Post-Listing 404s | Checksum Failures | Compressed Bytes | Sample First-Month SHA-256 |
| :--- | ---: | :---: | :---: | ---: | ---: | ---: | :--- |
| `BTCUSDT` | 101 | `2017-08` | `2025-12` | 6 | 0 | 4,320,601 | `f4b8fb06d4be...` |
| `ETHUSDT` | 101 | `2017-08` | `2025-12` | 6 | 0 | 4,064,340 | `7ad6cf79eb7c...` |
| `BNBUSDT` | 98 | `2017-11` | `2025-12` | 6 | 0 | 3,576,505 | `94c94957e508...` |
| `LTCUSDT` | 97 | `2017-12` | `2025-12` | 6 | 0 | 3,515,268 | `1648e9877e1d...` |
| `ADAUSDT` | 93 | `2018-04` | `2025-12` | 6 | 0 | 3,307,999 | `af2c1c2f6d16...` |
| `XRPUSDT` | 92 | `2018-05` | `2025-12` | 6 | 0 | 3,308,307 | `d9f6f8191e27...` |
| `XLMUSDT` | 92 | `2018-05` | `2025-12` | 6 | 0 | 3,028,161 | `01e56e85374a...` |
| `EOSUSDT` | 85 | `2018-05` | `2025-05` | 13 (6 pre + 7 post) | 0 | 2,903,564 | `8a8d8f618987...` |
| `TRXUSDT` | 91 | `2018-06` | `2025-12` | 6 | 0 | 3,247,916 | `e31339eb776d...` |
| `ETCUSDT` | 91 | `2018-06` | `2025-12` | 6 | 0 | 3,068,686 | `e13b00dc7318...` |
| `LINKUSDT` | 84 | `2019-01` | `2025-12` | 6 | 0 | 2,940,303 | `46077030656d...` |
| `DOGEUSDT` | 78 | `2019-07` | `2025-12` | 6 | 0 | 2,794,330 | `4c890388b030...` |
| `SOLUSDT` | 65 | `2020-08` | `2025-12` | 6 | 0 | 2,341,224 | `9a8c5048a20d...` |
| **Total** | **1,168** | `2017-08` | `2025-12` | 85 | **0** | **42,417,204** | **100% Verified** |

---

### Dataset 2 — Daily Order-Book Depth Snapshots (`H2`)

| Contract Field | Specification |
| :--- | :--- |
| **`source_identity`** | `binance_vision_um_daily_bookDepth` |
| **`official_download_location`** | `https://data.binance.vision/data/futures/um/daily/bookDepth/<SYMBOL>/<SYMBOL>-bookDepth-<YYYY-MM-DD>.zip` (+ `.CHECKSUM`) |
| **`raw_payload_hash`** | Per-file SHA-256 digest of the raw `.zip` bytes, verified equal to `<SYMBOL>-bookDepth-<YYYY-MM-DD>.zip.CHECKSUM` (all 2,187 files recorded in `n1_um_bookdepth_manifest.json`). |
| **`event_time`** | Snapshot `timestamp` (`YYYY-MM-DD HH:MM:SS` UTC, ~30-second sampling cadence; 10 rows per snapshot for `percentage` $\in \{-5, -4, -3, -2, -1, +1, +2, +3, +4, +5\}$). |
| **`available_at`** | All snapshots with timestamp $\tau \in [t_0 - 3600\text{s}, t_0)$ are aggregated into an hourly observation available strictly at the hour boundary $t_0$. |
| **`ingestion_time`** | `2026-11-11T06:33:07Z` – `2026-11-11T06:34:47Z` (per-file ISO-8601 UTC timestamp in manifest). |
| **`symbol_eligibility`** | `BTCUSDT` and `ETHUSDT` USD-M perpetual order books, used strictly as exogenous liquidity state observables for Spot execution. |
| **`missing_intervals`** | Archive begins on `2023-01-01` (`2022-12-31` verified HTTP 404). Across 2023–2025 (1,096 calendar days): `BTCUSDT` is missing 3 dates (`2023-02-08`, `2023-02-09`, `2024-04-18`); `ETHUSDT` is missing 2 dates (`2023-02-08`, `2023-02-09`). Missing dates are left as `NaN` (never forward-filled across days or synthesized from OHLCV). |
| **`revision_or_correction_policy`** | Immutable raw `.zip` + `.sha256` storage; any upstream checksum change requires a new `dataset_version`. |
| **`dataset_version`** | `n1-acq-v1` |

#### Per-Symbol Verified Coverage Summary (`H2`)

| Symbol | Verified Daily Zips | First Date | Last Date | Missing Dates (HTTP 404) | Checksum Failures | Compressed Bytes | Completeness |
| :--- | ---: | :---: | :---: | :--- | ---: | ---: | ---: |
| `BTCUSDT` | 1,093 | `2023-01-01` | `2025-12-31` | `2023-02-08`, `2023-02-09`, `2024-04-18` | 0 | 494,876,404 | 99.73% |
| `ETHUSDT` | 1,094 | `2023-01-01` | `2025-12-31` | `2023-02-08`, `2023-02-09` | 0 | 512,963,273 | 99.82% |
| **Total** | **2,187** | `2023-01-01` | `2025-12-31` | 5 symbol-days | **0** | **1,007,839,677** | **99.77%** |
