# 00 System Architecture

Status: initial inventory complete.

## Main Runtime

`main.py` is the normal operational entry point. It loads `.env`, starts Binance WebSocket with REST fallback, updates macro and alternative data, initializes causal components, runs scheduled analysis, sends Telegram/dashboard outputs, and optionally starts the Telegram command listener.

`main_live.py` is the live wrapper. It fails closed unless:

- `LIVE_TRADING_ENABLED=true`
- `AUTO_TRADE_DRY_RUN=false`
- `LIVE_AUTHORIZATION_TOKEN` is present
- Phase 5 report exists and passes
- manual checklist passes
- kill switch is armed

`api/server.py` is the FastAPI backend for dashboard and operational endpoints.

## Data Flow

```text
market/external providers
  -> collectors and exchange clients
  -> normalized state files / feature snapshots
  -> analysis and regime logic
  -> ML feature extractor / meta model
  -> prediction logger and RuntimeEvidenceStore
  -> decision engine / AutoTrader
  -> ExecutionEngine / ReservationStore / FillTracker
  -> PositionTracker / outcome linker
  -> calibration evidence / dashboards / Telegram
```

## Runtime Stores

- Latest state: `data/latest_signals.json`, `data/latest_ai_analysis.json`, `data/macro_state.json`.
- Alternative data: `data/alternative_data.json`, `data/alternative_feature_snapshot.json`, `data/raw_alternative/**`.
- Execution: `data/execution/**`, `logs/execution/**`.
- Prediction/evidence: `logs/prediction_audit/**`, `logs/runtime_evidence.sqlite`.
- Backtests: `data/backtests/**`.
- Models: `logs/*.joblib`, `logs/rl_models/**`, `models/*.pt`.

## Initial Architecture Rating

Classification: `PAPER_READY` architecture with production-shaped gates, but live readiness remains `BLOCKED` pending evidence.

