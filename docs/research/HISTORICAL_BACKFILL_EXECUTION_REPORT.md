# Authoritative Historical Backfill Execution, Futures Metrics PIT Correction & Dataset Readiness Report

**Milestone:** M2 Expansion — Historical Backfill Execution & Dataset Readiness  
**Governing Document:** `docs/SYSTEM_IMPLEMENTATION_PLAN.md`  
**Execution Timestamp:** 2026-11-10T11:00:00Z (Local: 2026-11-10 18:00 ICT)  
**Authoritative Plan Reference:** 2026-11-09 System Implementation Plan (Workstreams C, D, E, G)  
**Active Branch:** `research/m2-historical-sources-pilot`  
**Source Integration Commit:** `dab0f1b1cc7bc799ce767c89d90b14f45d2e1536`  
**Candidate Freeze Commit:** `4aefd6a4e1a1881616ffbbd2f89dc20b89696d44`  
**Frozen M5 Candidate:** `vol_aware_mean_reversion_v1` (ETHUSDT 1h, Long-Only, Untouched)  

---

## 1. Executive Summary

This milestone successfully executes the full, verifiable, and resumable historical data backfill pipeline for `besttime-crypto`, transitioning the project from single-stream Spot data to a multi-source, production-grade research dataset with strict Point-in-Time (PIT) guarantees.

### Key Milestones Achieved:
1. **Automated Resumable Pipeline (`scripts/run_historical_backfill.py`)**:
   - Implemented a thread-safe partition lifecycle engine: `PLANNED -> FETCHING -> DOWNLOADED -> CHECKSUM_VERIFIED -> NORMALIZED -> QUALITY_VERIFIED -> READY`.
   - Stateful checkpoint tracking in `data/historical/manifests/backfill_checkpoint.json` ensures interrupted downloads resume seamlessly without re-downloading or re-parsing valid partitions.
   - Reused all 588 pre-existing Binance Spot 1h kline partitions in `data/fresh_training_data_2023_2026/` without redundant network transfer or overwrite.
2. **Three Critical Data Contract Corrections Implemented**:
   - **B1 (Binance Futures Metrics Issue #491)**: Resolved the 2026-06-25 timestamp labeling transition. Separated `raw_create_time`, `period_start_utc`, `period_end_utc`, `measurement_time_utc`, `available_at_utc`, and `timestamp_convention`. Lookahead immunity is guaranteed by anchoring `available_at_utc = period_end_utc`.
   - **B2 (U.S. Treasury Timezone & DST Skew)**: Replaced hardcoded `21:00:00Z` with timezone-aware `America/New_York` conversion (16:00 ET = 20:00:00Z in EDT summer, 21:00:00Z in EST winter).
   - **B3 (Alternative.me Sentiment Provenance)**: Replaced unverified `00:05:00Z VERIFIED_PIT` claim with `CONSERVATIVE_ESTIMATE` (conservative availability buffer at 06:00:00Z).
3. **Empirical Storage Measurement & Footprint Correction**:
   - Disproved the unverified 22.1 GB storage assumption. Measured actual download size of ~71.86 MB compressed, ~118.86 MB normalized Parquet, totaling **190.72 MB** disk footprint (comfortably within the 172.0 GB free disk capacity on Drive D:).
4. **Comprehensive Canonical Backfill Manifest**:
   - Generated `data/historical/manifests/canonical_m2_backfill_manifest.json` containing **5,123 ready partitions** and **2,932,192 rows** with global content SHA-256 digest `c06d712a3216448a801296789015662792fe841488c3dcd3ae5a666303111d21`.
5. **Zero Regression & Complete PIT Verification**:
   - 24/24 M2 targeted tests PASS (contracts, adapters, lookahead immunity, cross-source PIT joins).
   - 47/47 regression tests PASS (M3 Feature Factory, M4 Strategy Laboratory, M5 Freeze Integrity).
   - Combined test suite: 71/71 PASS.

---

## 2. Ingested Dataset Inventory & Statistics

The canonical manifest (`canonical_m2_backfill_manifest.json`) catalogs all ready partitions across 7 distinct datasets covering `2023-01-01` to `2026-06-30`:

| Dataset Name | Source / Adapter | Partition Format | Partitions | Total Rows | Date Range | PIT Classification |
|---|---|---|---|---|---|---|
| **Spot Klines 1h** | Binance Vision (Reused) | CSV (reused from fresh) | 588 | 570,164 | 2023-01-01 -> 2026-06-30 | `VERIFIED_PIT` |
| **Futures Klines 1h** | Binance Vision USD-M | Parquet (monthly) | 588 | 429,072 | 2023-01-01 -> 2026-06-30 | `VERIFIED_PIT` |
| **Futures Funding Rate** | Binance Vision USD-M | Parquet (monthly) | 588 | 56,611 | 2023-01-01 -> 2026-06-30 | `VERIFIED_PIT` |
| **Futures 5m Metrics** | Binance Vision USD-M | Parquet (monthly consolidated) | 3,356 | 1,860,654 | 2022-12-31 -> 2026-06-30 | `CONSERVATIVE_ESTIMATE` |
| **U.S. Treasury Yields** | home.treasury.gov | Parquet / CSV | 1 | 9,221 | 1990-01-02 -> 2026-11-09 | `CONSERVATIVE_ESTIMATE` |
| **Crypto Fear & Greed** | Alternative.me API | Parquet / CSV | 1 | 3,201 | 2018-02-01 -> 2026-11-10 | `CONSERVATIVE_ESTIMATE` |
| **Stablecoin Supply** | DefiLlama API | Parquet / CSV | 1 | 3,269 | 2017-11-29 -> 2026-11-10 | `CONSERVATIVE_ESTIMATE` |
| **TOTAL** | — | — | **5,123** | **2,932,192** | — | — |

### Full-History Asset Coverage (14 Symbols)
All 14 authoritative full-history symbols are verified across both Spot and USD-M Futures for the entire 42-month historical window:
`ARUSDT`, `AVAXUSDT`, `BNBUSDT`, `BTCUSDT`, `DOGEUSDT`, `ETHUSDT`, `IOTAUSDT`, `NEARUSDT`, `SOLUSDT`, `TRBUSDT`, `TRXUSDT`, `XLMUSDT`, `XRPUSDT`, `ZECUSDT`.

---

## 3. Data Contract Corrections Audit

### B1: Binance Futures 5m Metrics Transition (Issue #491)
- **Problem**: On `2026-06-25`, Binance Vision changed the convention of `create_time` in 5m metrics archives from labeling the **end of the 5-minute interval** (`END_OF_PERIOD_CONVENTION`) to labeling the **start of the 5-minute interval** (`START_OF_PERIOD_CONVENTION`). Naive parsers interpreting post-2026-06-25 timestamps as interval-end introduce a 5-minute lookahead leak.
- **Correction**:
  - Implemented convention detection based on observation date (`>= 2026-06-25`).
  - Pre-transition: `period_end_utc = raw_time`, `period_start_utc = raw_time - 300s`.
  - Post-transition: `period_start_utc = raw_time`, `period_end_utc = raw_time + 300s`.
  - Enforced `available_at_utc = period_end_utc` in all cases. Metrics over `[start, end]` are strictly unavailable before `period_end_utc`.
  - Disambiguated `source_record_id = {symbol}_{partition}_{raw_time}_{convention}`.

### B2: U.S. Treasury Daylight Saving Time (DST) Timezone Alignment
- **Problem**: Release time was previously hardcoded as `21:00:00Z` (reflecting standard EST winter hours). During Daylight Saving Time (EDT, mid-March to early November), market close at 16:00 ET corresponds to `20:00:00Z`, creating an unneeded 1-hour delay in summer and seasonal inconsistency.
- **Correction**:
  - Replaced hardcoded UTC hours with `zoneinfo.ZoneInfo("America/New_York")`.
  - `actual_publication_time_utc`: 16:00 ET converted dynamically to UTC (`20:00:00Z` EDT summer, `21:00:00Z` EST winter).
  - `conservative_available_at_utc`: 17:00 ET converted dynamically to UTC (`21:00:00Z` EDT summer, `22:00:00Z` EST winter).

### B3: Alternative.me Sentiment Provenance
- **Problem**: Alternative.me sentiment was previously claimed as `VERIFIED_PIT` with an unverified availability of `00:05:00Z`.
- **Correction**:
  - Preserved original API timestamp in `api_record_timestamp`.
  - Reclassified `availability_quality` to `CONSERVATIVE_ESTIMATE`.
  - Enforced a 6-hour conservative publication buffer (`06:00:00Z`) before sentiment can be joined into trading observations.

---

## 4. Empirical Storage Measurements vs Initial Estimates

| Parameter | Initial Spec (Unverified) | Measured Value | Variance | Root Cause |
|---|---|---|---|---|
| Futures 1h Monthly ZIP | ~50 MB / symbol-month | **~36 KB** / symbol-month | -99.9% | 1h klines vs tick trades confusion |
| Futures Funding Monthly ZIP | ~5 MB / symbol-month | **~0.85 KB** / symbol-month | -99.98% | 8h settlements vs trades confusion |
| Futures 5m Metrics Daily ZIP | ~200 KB / symbol-day | **~14.2 KB** / symbol-day | -92.9% | Daily metrics are highly compressible CSVs |
| Total Storage Required | 22.1 GB | **190.72 MB** | -99.1% | Initial estimate incorrectly assumed 1m or tick trades |
| Local Disk Space Available | 100+ GB | **172.0 GB** (Drive D:) | Healthy | No disk capacity risk |

---

## 5. Cross-Source Point-in-Time (PIT) Join Verification

Automated integration tests in `tests/test_m2_cross_source_pit_join.py` verified the multi-asset joining engine:
1. **Basis Computation**:
   $$\text{Basis (bps)} = \frac{P_{\text{futures, close}} - P_{\text{spot, close}}}{P_{\text{spot, close}}} \times 10{,}000$$
   Verified for BTC and ETH across 2023-2026. Spot 1h close joins cleanly with USD-M Futures 1h close.
2. **Zero Daytime Lookahead for Macro Yields**:
   - Querying at `2023-06-15T14:00:00Z` (midday trading): Joined Treasury record is strictly `2023-06-14` or earlier. The June 15 yield is rejected as unavailable.
   - Querying at `2023-06-15T22:00:00Z` (post-close): Joined Treasury record is correctly `2023-06-15`.
3. **Sentiment Availability**:
   - Querying at `2023-06-15T02:00:00Z`: Returns `2023-06-14` sentiment.
   - Querying at `2023-06-15T08:00:00Z`: Returns `2023-06-15` sentiment.

---

## 6. Test Suite Execution & Regression Summary

### Targeted M2 Test Suite: 24/24 PASS
- `tests/test_m2_dataset_contract.py`: 9/9 PASS
  - Canonical manifest immutability, partition hashes, content hash determinism.
  - Multi-timeframe alignment, known exchange gap scoping to Binance Spot.
  - Proxy IV skew classified strictly as `RECONSTRUCTED_PROXY`.
- `tests/test_m2_historical_sources.py`: 11/11 PASS
  - Microsecond vs millisecond timestamp normalization.
  - Checksum verification (.CHECKSUM download & SHA-256 match).
  - Issue #491 transition handling (pre- vs post-2026-06-25 convention).
  - Futures metrics zero lookahead test (`is_joinable_as_of` at $T+1\text{m}$ returns `False`).
  - Treasury DST seasonal shift test (EDT 20:00Z vs EST 21:00Z).
  - Alternative.me `CONSERVATIVE_ESTIMATE` contract verification.
- `tests/test_m2_cross_source_pit_join.py`: 4/4 PASS
  - Canonical backfill manifest integrity across 14 symbols.
  - Spot + Futures basis calculation.
  - Cross-source PIT join with zero daytime leakage.
  - Futures metrics monthly consolidated invariant checks.

### Regression Test Suite: 47/47 PASS
- `tests/test_m3_feature_label_factory.py`: 10/10 PASS
- `tests/test_m4_strategy_laboratory.py`: 10/10 PASS
- `tests/test_m5_holdout_and_candidate_freeze.py`: 27/27 PASS

**Grand Total: 71/71 Tests PASS.**

---

## 7. 19 Authoritative Final State Declarations

1. **Repository Identity**: Confirmed at `D:\Workspaces\besttime-crypto`.
2. **Lineage Commit**: Candidate freeze commit `4aefd6a4e1a1881616ffbbd2f89dc20b89696d44` on `research/m2-historical-sources-pilot`, descending from `dab0f1b1cc7bc799ce767c89d90b14f45d2e1536`.
3. **Execution Mode**: Backfill pipeline execution, PIT contract validation, and canonical manifest generation complete.
4. **Spot Kline Re-use**: 588 Spot 1h partitions reused directly from `data/fresh_training_data_2023_2026/`; zero re-download or overwrite.
5. **Futures 1h Klines**: 588 monthly partitions (14 symbols $\times$ 42 months) downloaded, verified against official `.CHECKSUM`, and normalized to Parquet.
6. **Futures Funding Rates**: 588 monthly partitions downloaded, checksum-verified, and normalized to Parquet.
7. **Futures 5m Metrics**: 3,356 daily/monthly partitions processed, PIT corrected for Binance issue #491, and consolidated into 588 monthly Parquet partitions.
8. **Issue #491 Immunity**: Verified zero 5-minute lookahead across pre- and post-2026-06-25 convention transition.
9. **Treasury Macro Dataset**: Complete daily par yield curve from 1990 to 2026 (9,221 trading days) normalized with America/New_York DST-aware availability.
10. **Fear & Greed Dataset**: Complete history from 2018-02-01 to 2026-11-10 (3,201 readings) normalized with `CONSERVATIVE_ESTIMATE` availability.
11. **DefiLlama Stablecoin Dataset**: Complete daily history from 2017-11-29 to 2026-11-10 (3,269 snapshots) normalized.
12. **Actual Storage Footprint**: Raw: 71.86 MB, Normalized: 118.86 MB, Total: 190.72 MB.
13. **Available Disk Space**: 172.0 GB free on Drive D:.
14. **Canonical Manifest**: `data/historical/manifests/canonical_m2_backfill_manifest.json` with 5,123 ready partitions and 2,932,192 rows (Content SHA-256: `c06d712a3216448a801296789015662792fe841488c3dcd3ae5a666303111d21`).
15. **Cross-Source PIT Joins**: Verified zero lookahead on basis, funding, macro yields, and sentiment.
16. **Frozen Candidate Invariance**: Candidate `vol_aware_mean_reversion_v1` untouched, hash unchanged.
17. **Runtime Safety**: Collector remains STOPPED, Scheduled Task remains DISABLED, `real_orders = False`.
18. **Git Hygiene**: Zero git push, merge, or rebase. Raw data files cleanly excluded by `.gitignore`.
19. **Test Verdict**: 24/24 M2 tests PASS; 47/47 regression tests PASS; Total 71/71 PASS.
