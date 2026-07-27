# 06 Trading Decision And Risk

Status: paper-ready candidate.

## Positive Findings

- `trading/decision_types.py` provides canonical decision and reason-code structures.
- `AutoTrader` computes eligibility, EV, Kelly-related sizing fields, rejection reasons, and routes orders through `ExecutionEngine`.
- Circuit breaker, daily limit, exposure/correlation checks, existing-position checks, and readiness gate hooks are present.
- AutoTrader passes prediction and decision IDs into execution/position tracking.

## Gaps

- Need executable test evidence for the full decision matrix.
- Need explicit assertion that positive EV after fees/slippage is mandatory for all entry orders.
- Need stronger proof that model lineage survives through close/outcome for every system-created trade.
- Broad fallback paths should be classified as fail-closed or degraded.

## Classification

`PAPER_READY`, not live-ready without E2E evidence.

