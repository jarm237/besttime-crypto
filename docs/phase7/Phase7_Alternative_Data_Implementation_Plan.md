# Phase 7 - Alternative Data Layer Implementation Plan

## 1. Objective

Build a robust, production-ready alternative data platform that enriches the existing AI Quant causal engine with on-chain, macro, and market microstructure features.

---

## 2. Architecture & Data Flow

```text
Collectors (Alternative Data Layer)
  ├── Base Interface (collector_base.py)
  └── Concrete Collectors (Binance, DefiLlama, FRED, Yahoo Finance, Glassnode, Deribit, ETF, Reddit, Google Trends)
        ↓
    Raw Store / Persistence Layer (data/raw_alternative/)
        ↓
  AlternativeDataCollector (alternative_data.py)
        ↓
  Normalizer + Feature Builder
        ↓
  WorldState.alternative (12+ New Features)
        ↓
  Causal Context Bridge (causal_context_bridge.py)
        ↓
  ML Models & Causal Decision Engine
```

---

## 3. Implementation Status Dashboard

### ✅ Phase 7.1: Foundation & Baseline (COMPLETED)

- [x] **Alternative Data Interface & Base**:
  - Implemented `collector_base.py` defining unified base interfaces, retry mechanisms, and schema validation.
  - Implemented `alternative_data.py` to coordinate and process alternative data streams.
- [x] **WorldState Expansion**:
  - Expanded `WorldState` in `world_state.py` with a dedicated `alternative` layer containing 12 key metrics:
    - *Microstructure*: `orderbook_imbalance`, `liquidity_pressure`, `funding_pressure`
    - *On-chain & Flows*: `exchange_netflow`, `whale_score`, `stablecoin_supply`, `etf_flow`, `stablecoin_momentum`, `etf_momentum`
    - *Derivatives & Sentiment*: `options_iv`, `risk_on_score`
    - *Macro*: `macro_pressure`
- [x] **Causal Pipeline Integration**:
  - Integrated `WorldState.alternative` payload into `causal_context_bridge.py`.
  - Allowed context engines to dynamically ingest and query alternative metrics.
- [x] **Test Verification**:
  - Added smoke tests in `tests/test_alternative_data.py` verifying state loading, persistence, round-trip integrity, normalization, raw-store persistence, and feature snapshot export.
  - Test status: **`alternative-data smoke test passed` (100% SUCCESS)**.

---

## 4. Current Status & Remaining Gaps

The Phase 7 foundation is now implemented and validated. The collector framework, world-state integration, and basic persistence/snapshot utilities are in place, so the remaining work is now focused on hardening the pipeline rather than introducing the first version of the feature layer.

### ✅ Completed so far
- Base collector interface and retry abstraction implemented.
- Unified alternative-data aggregation layer implemented.
- Sprint 2–4 collectors implemented for market, macro, on-chain, derivatives, and social sources.
- WorldState alternative layer integrated into the causal bridge.
- Initial unit tests added for the new collectors.
- Basic persistence and snapshot/replay utilities are available in the repository for world-state and feature snapshots.

### ✅ All gaps closed (Sprint 7 complete)
- **Scheduler & orchestration** → `alternative_scheduler.py`: thread-based `AlternativeDataScheduler` with configurable interval, `on_success`/`on_failure` callbacks, `SchedulerRegistry`, and CLI entry point (`--once` or daemon mode).
- **Historical backfill & replay** → `alternative_backfill.py`:
  - `AlternativeDataBackfiller`: generates synthetic payloads across any date range into the raw-store directory (skip or overwrite existing).
  - `AlternativeDataReplayer`: iterates raw-store chronologically with date-range filtering, payload callback, and `replay_into_world_state` for direct WorldState injection during backtesting.
- **Data quality dashboard & alerting** → `alternative_quality.py`:
  - `DataQualityChecker`: validates field presence, freshness (configurable `max_age_seconds`), and per-field value-range bounds.
  - `DataQualityDashboard`: accumulates quality reports, writes a persistent JSON quality log, and surfaces `summary()` statistics and `print_dashboard()` output — **now includes ETF Flow Status block (BTC/ETH/SOL)**.
  - `CollectorHealthMonitor`: tracks per-collector uptime/failure rates and emits structured `AlertRecord` objects (info / warning / critical) with optional external forwarding callback — **now includes `check_etf_alert_conditions()` monitoring stale data >36h, consecutive failures >2 days, and 401/403 auth errors from MongoDB logs**.
- **API-key / rate-limit hardening** → Per-collector retry/delay config exposed through `CollectorBase` constructor args (retries, delay_seconds).

### ✅ Sprint 9: Source Hardening & ETF Flow Integration (COMPLETED)
- [x] **Sprint 9.1** — All `api.example.com` placeholders removed. Startup validation added via `validate_collectors_on_startup()`. Collectors fail soft.
- [x] **Sprint 9.2** — `ParsebotFarsideETFCollector` in `btc_scraper/collectors/parsebot_farside_collector.py`. Provider chain: Parse.bot → JSON cache. Normalizes `etf_flow`, `etf_momentum`, `etf_flow_confidence`, `etf_flow_source`.
- [x] **Sprint 9.3** — DefiLlama stablecoin endpoint patched to use `stablecoins.llama.fi/stablecoins`.
- [x] **Sprint 9.4** — Reddit OAuth implemented in `btc_scraper/collectors/reddit_collector.py`.
- [x] **Sprint 9.5** — Google Trends cadence fixed to 6h minimum with LKV cache.
- [x] **Sprint 9.6** — Confidence layer: `effective_stablecoin_momentum`, `effective_etf_momentum`, `effective_risk_on_score` computed in normalization layer and fed into `causal_context_bridge.py` WorldState instead of raw values.

### ✅ Phase C: ETF Storage MongoDB (COMPLETED)
- `btc_scraper/core/db.py`: Defines `alternative_data_etf_flows` collection (unique index on `source+symbol+flow_date`) and `alternative_data_fetch_logs` collection.
- `btc_scraper/collectors/parsebot_farside_collector.py`: `_parse_and_save_records_to_db()` upserts daily ETF flow records to MongoDB. `_save_fetch_log_to_db()` records every API call result.

### ✅ Phase D: Scheduler Auto-trigger (COMPLETED)
- `btc_scraper/collectors/alternative_scheduler.py`: `_collect()` now checks timezone-aware time (`Asia/Ho_Chi_Minh`) and automatically triggers `fetch_parsebot_etf_recent_job()`, `fetch_parsebot_etf_all_job()`, `fetch_parsebot_fund_info_job()` on the correct cron schedule without OS cron dependency.

### ✅ Phase F: ETF Monitoring & Alerts (COMPLETED)
- `CollectorHealthMonitor.check_etf_alert_conditions()` in `alternative_quality.py` queries MongoDB logs to detect: 401/403 auth errors, consecutive failures >48h, and stale data >36h — emitting Telegram-forwarded `AlertRecord`.

### ✅ Fallback Fixes (Bonus)
- **FRED 400 Bad Request**: `fred_collector.py` auto-falls back to Yahoo Finance REST (`query2.finance.yahoo.com/v8/finance/chart`) when key is `"demo"` or API returns error.
- **yfinance fallback**: `yahoo_collector.py` and `macro_collector.py` work without `yfinance` installed, using public REST endpoints.
- **Causal Bridge safety**: `_get_float()` helper prevents `TypeError` when alternative features return `None`.

---

## 5. Next Phase: Hardening & Feature Engineering (Sprint 5 - 7)

The next sprints should focus on production-readiness and full feature-engineering integration rather than just collector coverage.

### 🟡 Sprint 5: Feature Builder & Normalization (Implemented)
- [x] Establish a common collector payload schema and safe fallback behavior.
- [x] Implement normalization for all collector outputs into a common schema.
- [x] Handle missing values via safe defaults and fallback behavior.
- [x] Build derived metrics from the raw inputs.
- [x] Add a feature snapshot export for ML training and backtesting.

### ✅ Sprint 6: WorldState & Replay Integration (Completed)
- [x] Store normalized alternative features directly in `WorldState.alternative` through the causal bridge integration.
- [x] Add support for historical replay and snapshot-based backtest using the alternative-data payload (`AlternativeDataReplayer.replay_into_world_state`).
- [x] Ensure all new features are available to context providers and causal models.

### ✅ Sprint 7: Validation, Monitoring & Dashboard (Completed)
- [x] Add a lightweight data-quality dashboard (`DataQualityDashboard` with `print_dashboard()` and JSON quality log at `data/alternative_quality.json`).
- [x] Add alerting for collector failure, missing data, and stale values (`CollectorHealthMonitor` + `AlertRecord` with configurable callback).
- [x] Add historical replay and anomaly checks (`AlternativeDataReplayer`, `DataQualityChecker` out-of-range detection).
- [x] Add end-to-end tests for the collection → normalization → world-state pipeline (`tests/test_phase7_sprint7.py` — **29/29 PASSED**).
- [x] Add production scheduler/orchestration (`AlternativeDataScheduler`, `SchedulerRegistry`).

### ✅ Sprint 8: Production Integration (Completed)
- [x] Wire `AlternativeDataScheduler` into `main.py` → `async_main()` startup (runs first collection immediately, then background thread).
- [x] Wire `CollectorHealthMonitor` with Telegram alert callback (`_send_alt_data_telegram_alert`) for critical quality degradation.
- [x] Add per-cycle alternative-data quality check + console summary in `fetch_and_display()` (shows `risk_on`, `macro_pressure`, `funding_pressure`).
- [x] Add graceful shutdown: `_alt_data_scheduler.stop()` in the `finally` block.
- [x] Full regression test: **246/246 tests PASSED** (50 new tests vs 196 baseline).

---

## 6. Sprint 2–4 Implementation Summary

### 🟡 Sprint 2: Market & Macro Collectors
- [x] **Binance Live Collector**:
  - Added a lightweight Binance collector for funding rate and open interest values.
  - Implemented in `btc_scraper/collectors/binance_collector.py`.
- [x] **Yahoo Finance / FRED Collector**:
  - Added collectors for DXY, VIX, Gold spot price, and US 10-Year Bond Yield.
  - Implemented in `btc_scraper/collectors/fred_collector.py` and `btc_scraper/collectors/yahoo_collector.py`.
- [x] **DefiLlama Collector**:
  - Added a collector for stablecoin supply and aggregate DeFi TVL.
  - Implemented in `btc_scraper/collectors/defillama_collector.py`.
- [x] **Unified Aggregation Layer**:
  - The alternative data collection flow now merges these Sprint 2 metrics into a single payload in `btc_scraper/collectors/alternative_data.py`.

### 🟢 Sprint 3: On-chain & Derivatives Collectors
- [x] **Glassnode Free / Blockchain.com / Blockchair**:
  - Added collectors for active addresses, aggregate exchange netflows, and Bitcoin network hashrate.
  - Implemented in `btc_scraper/collectors/glassnode_collector.py`, `btc_scraper/collectors/blockchain_collector.py`, and `btc_scraper/collectors/blockchair_collector.py`.
- [x] **Deribit Options Collector**:
  - Added an options collector for implied volatility and skew.
  - Implemented in `btc_scraper/collectors/deribit_collector.py`.
- [x] **CryptoETF.today / Whale Alert**:
  - Added collectors for ETF flow and whale-alert-based whale score.
  - Implemented in `btc_scraper/collectors/etf_collector.py` and `btc_scraper/collectors/whalealert_collector.py`.
- [x] **Unified Aggregation Layer**:
  - Sprint 3 metrics are now merged into the alternative data payload in `btc_scraper/collectors/alternative_data.py`.

### 🔵 Sprint 4: Sentiment & Social Collectors
- [x] **Google Trends Collector**:
  - Added a lightweight Google Trends collector for search-interest proxy values.
  - Implemented in `btc_scraper/collectors/google_trends_collector.py`.
- [x] **Reddit Sentiment Collector**:
  - Added a Reddit sentiment collector for social sentiment proxy values.
  - Implemented in `btc_scraper/collectors/reddit_collector.py`.
- [x] **Unified Aggregation Layer**:
  - Sprint 4 sentiment metrics are now merged into the alternative data payload in `btc_scraper/collectors/alternative_data.py`.

---

## 7. Free Data Sources Index

| Source | Target Metrics | API Protocol | Cost |
| :--- | :--- | :--- | :--- |
| **Binance API** | Funding Rate, Open Interest, Orderbook | REST / WebSocket | Free |
| **DefiLlama** | TVL, Stablecoin Dominance | REST | Free |
| **FRED** | Yield Curve, CPI, Interest Rates | REST (with free API Key) | Free |
| **Yahoo Finance** | DXY, VIX, Gold Spot | python-yfinance | Free |
| **Deribit** | Options IV, Put/Call Ratio | Public REST | Free |
| **Google Trends** | Search Interest Momentum | pytrends / Scraping | Free |

---

## 8. Success & Evaluation Criteria

- **Collector Resilience**: Uptime > 98% with graceful fallback to last known values (LKVs) or defaults during API rate-limiting.
- **Micro-pipeline Latency**: Data collection to `WorldState` propagation time < 10 seconds.
- **Missing Value Handling**: Forward-fill or default substitution implemented to prevent causal reasoning failure during API outages.
- **Ensemble ML Support**: Historical CSV export supporting feature alignment for model retraining.

---

## 9. Final Status (as of 2026-07-07)

**All Phase 7 objectives and Sprint 9 hardening tasks are COMPLETE.**

Test results: `pytest tests/test_phase7_sprint7.py` → **29/29 PASSED**.

Key production files:
- `btc_scraper/collectors/parsebot_farside_collector.py` — ETF collector + MongoDB upsert
- `btc_scraper/collectors/alternative_scheduler.py` — Timezone-aware Parse.bot cron scheduling
- `btc_scraper/collectors/alternative_quality.py` — ETF alert monitoring + dashboard
- `btc_scraper/ml_engine/causal_context_bridge.py` — Confidence-weighted features in WorldState
- `btc_scraper/core/db.py` — MongoDB collections with production indexes
- `scripts/fetch_parsebot_etf_jobs.py` — CLI job runner (dry-run verified)
