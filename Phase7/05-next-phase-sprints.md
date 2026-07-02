# Phase 7 — Next Phase: Hardening & Feature Engineering (Sprint 5 - 7)

## Sprint 5: Feature Builder & Normalization
- Implement normalization for all collector outputs into a common schema.
- Handle missing values via forward-fill, interpolation, or safe defaults.
- Build derived metrics from the raw inputs.
- Add a feature snapshot export for ML training and backtesting.

## Sprint 6: WorldState & Replay Integration
- Store normalized alternative features directly in `WorldState.alternative`.
- Add support for historical replay and snapshot-based backtest.
- Ensure all new features are available to context providers and causal models.

## Sprint 7: Validation, Monitoring & Dashboard
- Add a lightweight data-quality dashboard.
- Add alerting for collector failure, missing data, and stale values.
- Add historical replay and simple anomaly checks.
- Add end-to-end tests for the collection → normalization → world-state pipeline.
