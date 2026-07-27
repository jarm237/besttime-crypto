# 10 UI And Telegram

Status: requires remediation.

## UI/API

Positive:

- `api/server.py` exposes FastAPI endpoints for liveness/readiness, positions, auto-trade status, model health, market signals, backtests and execution.
- `web/` provides a React/Vite dashboard.
- `btc_scraper/ui/dashboard.py` provides a smaller FastAPI dashboard for regime/model views.

Gaps:

- UI must clearly distinguish analysis signal, eligible trade, submitted order, exchange accepted, partial fill, filled, position open, position closed and outcome linked.
- Stale data needs explicit markers.
- Model lineage fields should be visible: production model, shadow model, artifact hash, fallback, calibration drift, prediction failures.
- UI action authorization needs a dedicated review.

## Telegram

Positive:

- Telegram listener supports allowed chat IDs.
- Alerts and commands are split into modules.
- Markdown fallback exists for send failures.

Gaps:

- Dangerous commands need explicit approval/audit review.
- Telegram acknowledgement must not be treated as a transaction commit.
- Outage/rate-limit behavior needs replay tests.

## Classification

`REQUIRES_REMEDIATION`

