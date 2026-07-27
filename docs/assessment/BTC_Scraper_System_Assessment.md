# BTC Scraper System Assessment

Date: 2026-07-27

Scope: initial system assessment based on repository inventory, static code reading, import/config scan, and compile/test evidence from the current local environment. This is not a completed production certification; it is the baseline artifact for the full review plan.

## Executive Conclusion

`btc_scraper` is best classified as `PAPER_READY` for signal research and paper-trading workflows, with live trading still `BLOCKED` by design until stronger operational evidence is available.

The repository already contains several production-shaped controls: fail-closed live entry validation in `main_live.py`, a central `ExecutionEngine`, live guard checks, a SQLite runtime evidence store, stable decision types, reservation/idempotency support, prediction audit JSONL/SQLite persistence, and targeted tests for ML/runtime/execution flows.

The main blockers are not absence of safety concepts. The first remediation wave has removed the immediate test/compile/contract/dispatch blockers; remaining risk is concentrated in operational proof depth and state lifecycle:

- Full local test assertions now pass: `743 passed, 118 warnings, 5 subtests passed`.
- Full compile now passes with `.venv/bin/python -m compileall -q btc_scraper main.py main_live.py api scripts`.
- `prediction_created` now requires production lineage fields including `artifact_sha256`, `feature_snapshot_id`, `symbol`, `timeframe`, `side`, `predicted_at`, and `valid_until`.
- Live LIMIT dispatch now calls limit adapter methods; live TWAP is disabled fail-closed until live adapter integration is rehearsed against child-order recovery.
- Test runtime artifacts are now isolated under `/tmp/btc-scraper-tests/<run-id>/` with environment metadata and a pytest guard that blocks repo runtime-root mutation.
- Restart/replay recovery tests now cover the baseline crash-boundary matrix from persisted prediction through outcome revision conflict and repeated multi-restart replay.
- Live exchange outage baseline tests now cover submit timeout, rate-limit backoff, outage taxonomy, child-order persistence, cancel/replace ambiguity, WS/REST disagreement, and operator quarantine workflow through deterministic fake adapters.
- Runtime ownership now provides deployment-scoped roots, identity metadata, per-deployment process locks, stale-lock audit, and hash-based guard reporting. A pre-existing `main.py` process should be restarted on these owned roots before claiming clean full-suite guard evidence.
- Persistent historical data lifecycle is still broad across legacy `data/`, `logs/`, `btc_scraper/data`, `btc_scraper/logs`, `models/`, and `checkpoints_gpu`, and needs a full taxonomy for raw/processed/runtime/paper/backtest/model/quarantine state.
- There are many broad `except Exception` fallback paths; some are intentional resilience, but they need classification into fail-closed, degrade, quarantine, or continue.

## Architecture Summary

Primary runtime path:

```text
main.py
  -> exchange candles via Binance WebSocket / REST fallback
  -> collectors for macro and alternative data
  -> analysis.analyze_market
  -> ml_engine.signal_score / meta_model prediction
  -> causal context bridge / causal startup components
  -> trading.AutoTrader decision and sizing
  -> execution.ExecutionEngine
  -> reservation store, fill tracker, position tracker
  -> runtime evidence / prediction audit / Telegram / dashboard files
```

Live entry path:

```text
main_live.py
  -> assert_live_authorized()
  -> Phase 5 report gate
  -> manual checklist
  -> kill switch
  -> main.main()
```

Dashboard/API path:

```text
api/server.py
  -> FastAPI endpoints
  -> data/latest_signals.json
  -> data/latest_ai_analysis.json
  -> logs/meta_model*.json/joblib
  -> data/backtests/*
  -> execution config, fills, reports
```

## Package Inventory

Static AST inventory of `btc_scraper`:

| Package | Modules | Classes | Functions | Async |
|---|---:|---:|---:|---:|
| `btc_scraper.ai_analyst` | 5 | 1 | 17 | 0 |
| `btc_scraper.analysis` | 6 | 2 | 43 | 0 |
| `btc_scraper.backtesting` | 16 | 15 | 30 | 0 |
| `btc_scraper.collectors` | 24 | 37 | 191 | 0 |
| `btc_scraper.core` | 16 | 32 | 151 | 13 |
| `btc_scraper.exchanges` | 5 | 1 | 25 | 8 |
| `btc_scraper.execution` | 31 | 90 | 352 | 29 |
| `btc_scraper.feature_engineering` | 13 | 24 | 102 | 0 |
| `btc_scraper.ml_engine` | 74 | 137 | 689 | 2 |
| `btc_scraper.regime` | 7 | 0 | 26 | 0 |
| `btc_scraper.telegram_bot` | 6 | 0 | 24 | 0 |
| `btc_scraper.trading` | 8 | 14 | 91 | 3 |
| `btc_scraper.ui` | 3 | 0 | 17 | 2 |

Total: 215 Python modules, 353 classes, 1758 functions.

## Runtime Entry Points

Primary:

- `main.py`: normal bot loop, `--once` mode, scheduler, AI worker, Telegram listener, WebSocket bootstrap, alternative data scheduler.
- `main_live.py`: fail-closed live production wrapper around `main.main()`.
- `api/server.py`: FastAPI backend for dashboard and operational data.
- `web/`: React/Vite dashboard.

Operational scripts:

- Training/build: `scripts/build_and_train.py`, `scripts/train_meta_model_v3.py`, `scripts/train_many_coins.py`, `scripts/train_rl_exit_manager.py`, `scripts/train_slippage_model.py`.
- Feature pipeline: `scripts/build_feature_store_v2.py`, `scripts/build_ml_dataset_v3.py`, `scripts/build_*features.py`, `scripts/generate_*labels.py`.
- Backtest/validation: `scripts/backtest.py`, `scripts/run_backtest_v2.py`, `scripts/run_walk_forward.py`, `scripts/run_monte_carlo.py`, `scripts/run_stress_tests.py`.
- Runtime evidence: `scripts/generate_gate_a_runtime_evidence.py`, `scripts/generate_ml_shadow_readiness.py`, `scripts/backfill_historical_paper_to_evidence.py`, `scripts/replay_prediction.py`, `scripts/replay_execution.py`.
- Scheduler docs/scripts: `scripts/SCHEDULE.md`, `scripts/setup_cron.sh`, `scripts/run_periodic_recalibration.sh`.

Internal `__main__` modules exist in `core`, `regime`, `execution`, and many `ml_engine` files. These should be classified as either supported CLI tools, research utilities, or deprecated scripts.

## Dependency Flow

High-level internal imports show this dependency shape:

```text
core
  <- collectors, exchanges, analysis, feature_engineering, ml_engine, trading
collectors / exchanges
  -> data and market snapshots
analysis / regime
  -> signal labels and rule scores
ml_engine.feature_extractor / meta_model / signal_score
  -> prediction and scoring
ml_engine.data_contracts / runtime_evidence_store
  -> event lineage and evidence
trading.auto_trader / decision_types
  -> eligibility, EV, sizing, decision metadata
execution.execution_engine / live_execution_guard / reservation_store / fill_tracker
  -> order lifecycle and reconciliation surfaces
telegram_bot / ui / api
  -> user interface and alert surfaces
```

## Persistent State Map

Observed persistent stores:

| Root | Files | Size | Main formats |
|---|---:|---:|---|
| `data/` | 2460 | ~905 MB | JSON, CSV, JSONL, Parquet, DB, PKL |
| `logs/` | 339 | ~762 MB | JSON, CSV, JSONL, log, joblib, zip |
| `btc_scraper/data/` | 1 | small | SQLite DB |
| `btc_scraper/logs/` | 4 | ~0.6 MB | log, JSON |
| `models/` | 3 | ~1.3 MB | PyTorch `.pt` |
| `checkpoints_gpu/` | 3 | ~0.4 MB | PyTorch `.pt` |
| `catboost_info/` | 5 | small | CatBoost training artifacts |

Key state families:

- Runtime latest state: `data/latest_signals.json`, `data/latest_ai_analysis.json`, `data/macro_state.json`, `data/alternative_data.json`, `data/alternative_feature_snapshot.json`.
- Owned runtime root: `runtime/<environment>/<deployment-id>/{data,logs,models,state}` by default for newly started processes.
- Runtime lock: `runtime/<environment>/<deployment-id>/state/runtime.lock`, with stale-lock audit in `runtime_lock_events.jsonl`.
- Feature store: `data/feature_store/**`.
- Execution state: `data/execution/**`, `logs/execution/**`.
- Runtime evidence: `logs/runtime_evidence.sqlite`, `logs/prediction_audit/*.jsonl`.
- Model registry/artifacts: `logs/model_registry.json`, `logs/*.joblib`, `models/*.pt`, `logs/rl_models/**`.
- Backtests: `data/backtests/**`, `logs/backtest_*`.
- Legacy/package-local state: `btc_scraper/data/fallback_buffer.db`, `btc_scraper/logs/*`.

## Config And Feature Flags

Environment variables found by static scan include:

```text
AUTO_TRADE_*, LIVE_TRADING_ENABLED, LIVE_AUTHORIZATION_TOKEN,
LIVE_ACKNOWLEDGED_MANUAL_ITEMS, ML_ENGINE_LIVE_AUTHORIZED,
TELEGRAM_*, GEMINI_API_KEY*, MONGODB_URI,
ENABLE_BINANCE, ENABLE_FRED, ENABLE_ETF, ENABLE_REDDIT,
ENABLE_GLASSNODE, ENABLE_GOOGLE_TRENDS, ENABLE_DEFILLAMA,
ENABLE_BLOCKCHAIN_COM, ENABLE_BLOCKCHAIR, ENABLE_WHALE_ALERT,
PARSEBOT_*, ETF_FLOW_*, FRED_API_KEY, GLASSNODE_API_KEY,
WHALE_ALERT_API_KEY, REDDIT_*,
RL_EXIT_*, META_PROB_LOG_*, PAPER_RUN_ID, PAPER_FILL_SOURCE,
ML_MODEL_PROMOTION_OVERRIDE, CAUSAL_ALPHA, DEPLOYMENT_ID
```

Risk note: `ML_MODEL_PROMOTION_OVERRIDE` and live flags must be explicitly audited as privileged operational controls.

## Production Readiness

Current classification after the first remediation wave:

```text
Signal research: PAPER_READY
Paper trading: PAPER_READY with executable local test evidence
Live entry: BLOCKED by gates and missing real exchange/testnet drill proof
ML/causal/RL advanced components: mixed PAPER_READY / RESEARCH_ONLY
Execution: STRONG PAPER_READY candidate, deterministic live-outage baseline exists, live TWAP still disabled until exchange-integrated drill evidence exists
Operations: PAPER_READY baseline for ownership/isolation, still requires clean guard run and operator rehearsal before production
```

See detailed scoring in `BTC_Scraper_Module_Scorecard.md`.
