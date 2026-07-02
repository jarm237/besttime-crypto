# Phase 7 — Current Status & Remaining Gaps

Remaining work:

- Persistent raw-store infrastructure under a dedicated raw-data directory.
- Scheduler and cron-style orchestration for periodic collection.
- Normalization layer for time-alignment and missing values.
- Derived feature builder for metrics (liquidity_pressure, macro_pressure, funding_pressure, orderbook_imbalance, stablecoin_momentum, etf_momentum, risk_on_score).
- Feature-store or snapshot export for model training / replay.
- Historical backfill and replay support.
- Data quality dashboard and alerting.
- API-key configuration and rate-limit handling for higher-volume providers.
