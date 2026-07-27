# BTC Scraper Module Scorecard

Date: 2026-07-27

Scale: 0-50 across correctness, contract clarity, lineage, failure safety, idempotency/recovery, test coverage, observability, runtime evidence, maintainability, and production readiness.

Classification:

```text
43-50: Production-ready candidate
35-42: Paper-ready
25-34: Requires remediation
15-24: Research-only / major gaps
0-14: Blocked / redesign
```

Hard blockers override numeric score.

| Module | Score | Classification | Recommended disposition | Main blockers / risks |
|---|---:|---|---|---|
| `core` | 34 | Requires remediation | REFACTOR | Core has useful path, atomic write, event, snapshot, world-state primitives, but domain contracts are split and timestamp/Decimal/error taxonomy are not centralized enough. |
| `ml_engine.data_contracts` / `contracts` | 37 | Paper-ready | KEEP/REFACTOR | Prediction contract now requires production lineage fields; next work is broader schema/version compatibility across all event producers. |
| `collectors` | 32 | Requires remediation | REFACTOR | Provider health/status exists for alternative data, but many external fallbacks need fixture/replay proof and provider-by-provider fail behavior classification. |
| `exchanges` | 31 | Requires remediation | REFACTOR | CCXT wrapper and adapters exist, but precision/min-notional/order-state reconciliation needs end-to-end proof. |
| `feature_engineering` | 33 | Requires remediation | REFACTOR | Feature store and validators exist; point-in-time and training/runtime parity need explicit fixtures. |
| `analysis` | 33 | Requires remediation | REFACTOR | Signal scoring improvements exist, but `analysis/core.py` remains a large rule surface and needs score semantics tests/matrix. |
| `regime` | 30 | Requires remediation | REFACTOR | Regime classifier/calibration scripts exist; stability, unknown-state handling, and runtime parity need proof. |
| `ml_engine.training` | 30 | Requires remediation | REFACTOR | Many training scripts and artifacts; reproducibility and immutable dataset manifest need stronger enforcement. |
| `ml_engine.governance` | 36 | Paper-ready | KEEP/REFACTOR | Registry, gates, governed loader and evidence health exist; promotion override and live evidence separation need audit. |
| `ml_engine.inference` | 35 | Paper-ready | KEEP/REFACTOR | Artifact loader, prediction logger, schema validator exist; missing feature behavior and prediction validity contract need hardening. |
| `ml_engine.runtime` | 36 | Paper-ready | KEEP/REFACTOR | RuntimeEvidenceStore is strong; environment test evidence unavailable and prediction contract is incomplete. |
| `ml_engine.agents` | 22 | Research-only | RESEARCH_ONLY | Agent output should remain advisory unless passed through deterministic guards. |
| `ml_engine.causal` | 24 | Research-only | RESEARCH_ONLY | Causal graph/simulator exists, but assumptions, sensitivity, and incremental runtime value are not proven. |
| `ml_engine.rl` | 23 | Research-only | RESEARCH_ONLY | RL exit has guard/shadow mode, but live action should remain disabled until out-of-sample and tail-risk evidence are complete. |
| `trading` | 36 | Paper-ready | KEEP/REFACTOR | AutoTrader uses canonical decision types and ExecutionEngine; live readiness depends on evidence and stronger linkage checks. |
| `execution` | 36 | Paper-ready | KEEP/REFACTOR | Reservation/idempotency/live guard exist; selected LIMIT now dispatches through limit adapter and TWAP rejects fail-closed until E2E live TWAP recovery exists. |
| `backtesting` | 30 | Requires remediation | REFACTOR | Institutional components exist and compile blocker is fixed; runtime/backtest logic parity must still be proven. |
| `ai_analyst` | 24 | Research-only | RESEARCH_ONLY | Useful explanation layer; should not be a direct trading authority. |
| `telegram_bot` | 33 | Requires remediation | REFACTOR | Allowed chat ID support exists; dangerous command authorization/audit and outage behavior need full review. |
| `ui` / `api` | 30 | Requires remediation | REFACTOR | Dashboard surfaces many states but stale/lineage/authorization display needs stronger guarantees. |
| `data/` | 25 | Requires remediation | REFACTOR | Large mixed persistent state with raw/processed/runtime/paper/backtest/model artifacts; needs lifecycle and environment tagging. |
| `logs/` / observability | 28 | Requires remediation | REFACTOR | JSONL and metrics surfaces exist; rotation, correlation IDs, secret scanning, and evidence dashboards need completion. |

## Hard Blockers

| Priority | Blocker | Evidence | Acceptance criteria |
|---|---|---|---|
| P1 | Data/log lifecycle remains mixed | Full pytest writes runtime artifacts into operational paths | Test/debug/paper/live state is path-isolated and environment-tagged. |
| P1 | Persistent state is mixed across roots | Runtime, model, data, logs, synthetic and paper artifacts coexist under broad directories | Data lifecycle layout and environment tag required for operational records. |
| P1 | Restart/replay proof needs scenario expansion | Core lifecycle tests pass, but full restart matrix is not yet exhaustively documented | Restart after prediction, decision, reservation, submit timeout, partial fill and close-before-outcome passes without duplicate/conflict. |
| P2 | Many broad fallback paths need taxonomy | Static scan found extensive `except Exception` and fallback handling | Each path is tagged continue/degrade/fallback/block/quarantine/shutdown. |
