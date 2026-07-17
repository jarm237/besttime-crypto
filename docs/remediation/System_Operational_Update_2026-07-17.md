# System Operational Update

**Date:** 2026-07-17
**Scope:** trade provenance, WLD manual correction, runtime linkage rollout documentation
**Status:** applied and verified.

## Summary

The system can now distinguish orders created by the system in paper mode from orders created by a user through Telegram/UI/CLI.

The WLD position records were also corrected so the duplicate open WLD position is removed and the prior closed WLD trade is represented as a manual Telegram trade that followed a system signal.

## Trade Provenance Update

Implemented normalized order provenance fields:

```text
order_creator = system | user | test
order_channel = paper_runner | live_runner | telegram | ui | cli | manual | test | unknown
```

Derived flags now include:

```text
is_system_order
is_user_order
is_system_paper_order
is_user_telegram_order
is_user_ui_order
```

Runtime behavior:
- paper mode orders created by `auto_trader` are marked `system + paper_runner`;
- Telegram `/buy` positions are marked `user + telegram`;
- CLI-created positions are marked `user + cli`;
- UI-created positions can be marked or inferred as `user + ui`;
- manual trades following a system signal remain user-created trades through `manual_decision_basis = system_signal`.

Telegram `/positions` and the CLI position list now display the human-readable source label, such as:

```text
System paper mode
User via Telegram
User via UI
User via CLI
```

## WLD Correction

Applied operator-requested correction:

```text
Open WLD removed: b6c4d0aa-4ecb-40b5-bfb9-05ae2e95cca6
Corrected closed WLD: deadd193-2f1b-4bd1-afef-c75a95d33181
```

Corrected WLD trade:

```text
direction: SHORT
trade_origin: manual
execution_mode: manual
created_by: telegram_command
order_creator: user
order_channel: telegram
manual_decision_basis: system_signal
entry_price: 0.3978
sell_price / exit_price: 0.3943
invested_usdt: 500.0
pnl_pct: 0.8798
net_pnl_pct: 0.8798
pnl_usd_actual: 4.40
pnl_usd_per_1000: 8.80
fee_usd: 1.00
received_usdt: 503.39
r_multiplier: 0.51
result: WIN
```

Collections updated:
- `positions`
- `closed_positions`
- `closed_trades`

Verification:

```text
open_wld_count = 0
```

Backup:

```text
data/cleanup/wld_manual_signal_correction_backup_2026-07-17.json
```

## Verification

Focused provenance and paper lifecycle checks:

```bash
.venv/bin/pytest tests/test_trade_provenance.py tests/ml/test_paper_lifecycle_e2e.py -q
```

Result:

```text
19 passed
```

Compile check:

```bash
.venv/bin/python -m compileall -q \
  btc_scraper/trading/position_tracker.py \
  btc_scraper/telegram_bot/commands.py \
  btc_scraper/telegram_bot/formatters.py \
  btc_scraper/trading/auto_trader.py \
  scripts/manage_positions.py \
  scripts/backfill_trade_provenance.py
```

Result: passed.

## Operational Status

```text
Trade provenance taxonomy: IMPLEMENTED
Telegram/CLI source display: IMPLEMENTED
Legacy provenance backfill support: IMPLEMENTED
WLD duplicate open correction: APPLIED
WLD manual signal correction: APPLIED
Paper lifecycle tests: PASSED
Shadow evidence window: NOT STARTED
Runtime calibration readiness: BLOCKED
Meta promotion readiness: BLOCKED
```

## Remaining Work

This update does not start Gate A or the shadow evidence window.

Next operational sequence remains:

```text
run paper runner with fresh runtime records
-> generate producer coverage report
-> verify Gate A
-> create fresh GateSnapshot
-> start 7-day shadow evidence window
```

Do not retrain or promote the Meta Model from this correction alone.
