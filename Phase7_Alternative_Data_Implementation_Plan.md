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
  - Added smoke tests in `tests/test_alternative_data.py` verifying state loading, persistence, and round-trip integrity.
  - Test status: **`alternative-data smoke test passed` (100% SUCCESS)**.

---

## 4. Current Status & Remaining Gaps

The Phase 7 foundation is now in place, and the first multi-source collector layer has been implemented. The remaining work is focused on hardening the pipeline, adding normalization and derived features, and connecting the system to persistence, replay, and monitoring.

### ✅ Completed so far
- Base collector interface and retry abstraction implemented.
- Unified alternative-data aggregation layer implemented.
- Sprint 2–4 collectors implemented for market, macro, on-chain, derivatives, and social sources.
- WorldState alternative layer integrated into the causal bridge.
- Initial unit tests added for the new collectors.

### ⚠️ Remaining gaps / missing functionality
- Persistent raw-store infrastructure under a dedicated raw-data directory.
- Scheduler and cron-style orchestration for periodic collection.
- Normalization layer for time-alignment and missing values.
- Derived feature builder for metrics such as:
  - `liquidity_pressure`
  - `macro_pressure`
  - `funding_pressure`
  - `orderbook_imbalance`
  - `stablecoin_momentum`
  - `etf_momentum`
  - `risk_on_score`
- Feature-store or snapshot export for model training / replay.
- Historical backfill and replay support.
- Data quality dashboard and alerting.
- API-key configuration and rate-limit handling for higher-volume providers.

---

## 5. Next Phase: Hardening & Feature Engineering (Sprint 5 - 7)

The next sprints should focus on production-readiness rather than just collector coverage.

### 🟡 Sprint 5: Feature Builder & Normalization
- [ ] Implement normalization for all collector outputs into a common schema.
- [ ] Handle missing values via forward-fill, interpolation, or safe defaults.
- [ ] Build derived metrics from the raw inputs.
- [ ] Add a feature snapshot export for ML training and backtesting.

### 🟢 Sprint 6: WorldState & Replay Integration
- [ ] Store normalized alternative features directly in `WorldState.alternative`.
- [ ] Add support for historical replay and snapshot-based backtest.
- [ ] Ensure all new features are available to context providers and causal models.

### 🔵 Sprint 7: Validation, Monitoring & Dashboard
- [ ] Add a lightweight data-quality dashboard.
- [ ] Add alerting for collector failure, missing data, and stale values.
- [ ] Add historical replay and simple anomaly checks.
- [ ] Add end-to-end tests for the collection → normalization → world-state pipeline.

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
