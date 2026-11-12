# Neural N1.8-R2 — Source-Verified PIT & Forward Carry Lifecycle Remediation

**Executive Date:** November 12, 2026
**Research Subject:** `H-1 — DATED_QUARTERLY_DELIVERY_BASIS_CARRY_AND_CONVERGENCE`
**Workspace:** `D:\Workspaces\besttime-crypto`
**Branch:** `research/m2-historical-sources-pilot`
**Primary Modules:** `neural_trading/n1_7/lifecycle_engine.py`, `neural_trading/n1_6/recorder.py`, `neural_trading/n1_7/config.py`, `tests/test_neural_n1_8_r2.py`
**Fixture:** `tests/fixtures/n1_8_r2_multiday_lifecycle_fixture.json`

---

## 1. Executive Summary & Research Disposition

Following the N1.8-R1 forward integration and independent source audits of commit `4ec034b8`, the N1.8-R2 implementation has been thoroughly audited and remediated across Point-in-Time (PIT) integrity, quote alignment, lifecycle state progression, exit pricing contracts, fee accounting, chronological event ordering, and recorder process locking.

All artificial lookahead biases, hardcoded overrides, self-confirming tests, and fee omission defects have been eliminated from the active execution path.

### Canonical Research Disposition Enums

```text
PIT_INTEGRITY                  = PASS
CAUSAL_EVENT_ORDERING          = PASS
REALIZED_PNL_ACCOUNTING        = PASS
CLOSE_EXECUTION_PRICING        = PASS
MULTI_SESSION_LIFECYCLE        = PASS
RECORDER_SINGLE_WRITER         = PASS
REPLAY_IDEMPOTENCY             = PASS
FORWARD_RECORDER               = PAUSED
CLOSED_NATURAL_LIFECYCLES      = 0
REALIZED_FORWARD_NET_PNL       = 0.00
FORWARD_ECONOMIC_VALUE         = INCONCLUSIVE
PRODUCTION_CANDIDATE           = FALSE
REAL_TRADING                   = DISABLED
```

---

## 2. P0 Economic Closure Remediation Breakdown

### P0-1: Correct Realized PnL Accounting & Explicit Fee Bridge

Both early-exit and delivery-settlement branches in `process_observation()` previously omitted entry fees from realized net PnL, creating an artificial +$15.00/position overstatement of realized returns.

The active lifecycle engine now enforces the exact 7-term fee bridge:
```text
realized_net_pnl = (gross_spot_pnl + inverse_coinm_pnl_converted_usd)
                   - spot_entry_fee_usd
                   - coinm_entry_fee_usd
                   - spot_exit_fee_usd
                   - coinm_exit_or_delivery_fee_usd
                   - residual_execution_cost_usd
```
Every position records its itemized audit bridge in `pos["realized_pnl_bridge"]`. Verified by mathematical oracle in `test_case_14_realized_pnl_fee_bridge_exact_oracle` down to exact penny equality for both early exit and delivery settlement.

### P0-2: Executable Close-Now Economics & Depth Fail-Closed

In `compute_position_mtm()`, accounting MTM is separated from executable immediate liquidation:
1. **Accounting MTM:** `unrealized_pnl_after_entry_cost` tracks ongoing portfolio equity against mark levels.
2. **Executable Liquidation:** `estimated_close_now_pnl` calculates hypothetical immediate liquidation using orderbook depth sweeps (Spot bid VWAP, COIN-M ask VWAP, and all exit fees).
3. **Fail-Closed Guarantee:** If orderbook depth is missing or insufficient (`not depth_fillable`), the engine sets `close_executable = False`, `close_liquidation_status = "CLOSE_NOT_EXECUTABLE"`, and `estimated_close_now_pnl = "CLOSE_NOT_EXECUTABLE"`. No fabricated fills are generated.

### P0-3: Causal MA24 and Replay Contracts Fail-Closed

1. Added 29 hourly historical USDT/USD rates to `frozen_causal_klines_20261111.json` under `"timestamped_usdt_usd"`.
2. `fetch_causal_ma24_history()` strictly matches each candle close time to its exact timestamped USDT/USD rate.
3. Offline replay strictly fails closed (`0.0, 0.0, False`) when data is missing or incomplete; live network requests are blocked (`allow_network=False` default).

### P0-4: Chronological Event Flow & Multi-Session Checkpoint Persistence

1. Replaced two-step admission with a unified chronological event pipeline:
   $$\text{Receive quote} \rightarrow \text{Validate PIT} \rightarrow \text{Update existing} \rightarrow \text{Evaluate exit/settlement} \rightarrow \text{Persist closed} \rightarrow \text{Release capital} \rightarrow \text{Evaluate new entries} \rightarrow \text{Checkpoint}$$
2. Dynamic Scorecard: Scorecard computes `realized_closed_pnl_usd` directly from `sum(p.get("realized_pnl", 0.0) for p in closed_ledger)` (no hardcoded zeros).
3. Checkpoint API: Implemented atomic `save_checkpoint(path)`, `load_checkpoint(path)`, and `resume_from_checkpoint(path)` methods.

### P1: Atomic SingleWriterLock in Forward Recorder

`neural_trading/n1_6/recorder.py` implements `SingleWriterLock`:
1. Uses `os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)`.
2. Inspects live PID using Win32 API (`OpenProcess` with `SYNCHRONIZE`) on Windows and `os.kill(pid, 0)` on POSIX.
3. Competing processes log `ALREADY_RUNNING` and exit code 0 cleanly without disrupting the primary recorder. Stale locks are automatically reclaimed.

---

## 3. Causal Event Ordering Analysis (Task 1)

### Flawed Sort Analysis: `(decision_timestamp // 60000, priority, decision_timestamp)`
Grouping events by minute integer division (`// 60000`) caused an event arriving at second 55 (`CURRENT_QUARTER`, priority 0) to be sorted and processed BEFORE an event arriving at second 5 (`NEXT_QUARTER`, priority 1) in the exact same minute. This allowed future observations (observed 50 seconds later) to preempt earlier decisions, violating Point-in-Time causality.

### Remediated Causal Sort
The event stream is sorted strictly with `decision_timestamp` as the primary key:
```python
chronological_intents = sorted(
    order_intents,
    key=lambda x: (
        int(x["decision_timestamp"]),
        0 if x.get("contract_type") == "CURRENT_QUARTER" else 1,
    ),
)
```
- **Strict Monotonicity:** If $t_1 < t_2$, event 1 is processed strictly before event 2. Later-observed events never preempt earlier decisions.
- **Ties Only:** `CURRENT_QUARTER` priority breaks ties ONLY when decision timestamps are identical ($t_1 == t_2$).
- **Verified by Test:** `test_case_20_causal_event_ordering_50s_separation` asserts that two contracts arriving 50 seconds apart are evaluated sequentially without lookahead preemption, and that `CURRENT_QUARTER` priority correctly applies when timestamps are equal.

---

## 4. Empirical Test Suite Results

### Targeted Engine Test Suite (`tests/test_neural_n1_8_r2.py`)

All 20 test cases pass cleanly:

| # | Test Case | Target Invariant | Result |
|---|---|---|---|
| 1 | `test_case_1_ma24_causal_no_future_usdt` | Causal MA24 calculation without future USDT/USD | **PASS** |
| 2 | `test_case_2_frozen_75bps_no_historical_hardcoding` | Frozen 75 bps entry threshold cannot be overridden | **PASS** |
| 3 | `test_case_3_future_spot_quote_pairing_blocked` | Future-received Spot quotes strictly blocked from earlier decisions | **PASS** |
| 4 | `test_case_4_out_of_order_observations_ignored` | Out-of-order observations rejected (`OUT_OF_ORDER_IGNORED`) | **PASS** |
| 5 | `test_case_5_cross_symbol_quotes_ignored` | Cross-symbol quotes rejected (`CROSS_SYMBOL_IGNORED`) | **PASS** |
| 6 | `test_case_6_unique_persistent_lifecycle_ids` | Immutable lifecycle IDs across active and quarantined sets | **PASS** |
| 7 | `test_case_7_cross_expiry_underlying_caps_enforced` | Cross-expiry underlying caps enforced ($5,000 max) | **PASS** |
| 8 | `test_case_8_close_now_uses_spot_bid_coinm_ask` | Exit valuation uses Spot bid / COIN-M ask without double spread | **PASS** |
| 9 | `test_case_9_virtual_early_exit_realized_pnl` | Natural early exit ($\le 15$ bps) produces correct realized PnL | **PASS** |
| 10 | `test_case_10_virtual_delivery_settlement_inverse_accounting` | Delivery settlement computes inverse coin PnL and exit fees | **PASS** |
| 11 | `test_case_11_restart_preserves_state_no_duplicates` | Restart preserves state without duplicating positions | **PASS** |
| 12 | `test_case_12_replay_deterministic_from_frozen_inputs` | Bit-for-bit replay idempotency across independent runs | **PASS** |
| 13 | `test_case_13_end_to_end_entry_restart_close_replay_idempotency` | State preservation, single realization, and idempotent replay | **PASS** |
| 14 | `test_case_14_realized_pnl_fee_bridge_exact_oracle` | Mathematical oracle assertion for 7-component fee bridge | **PASS** |
| 15 | `test_case_15_close_now_economics_insufficient_depth` | Close-now returns `CLOSE_NOT_EXECUTABLE` on depth depletion | **PASS** |
| 16 | `test_case_16_causal_ma24_fails_closed_without_silent_network` | Offline replay fails closed without silent HTTP calls | **PASS** |
| 17 | `test_case_17_single_writer_lock_atomicity` | Atomic lock creation, live PID check, stale-lock recovery | **PASS** |
| 18 | `test_case_18_multiday_10step_integration` | Complete 10-step multi-day lifecycle flow using fixture | **PASS** |
| 19 | `test_case_19_end_to_end_raw_evaluator_integration_test_data` | Focused raw evaluator path, checkpointing, and natural close | **PASS** |
| 20 | `test_case_20_causal_event_ordering_50s_separation` | Event ordering with 50s separation in same minute | **PASS** |

### Complete Regression Test Suite Status

```bash
pytest tests/test_neural_n1_7.py tests/test_neural_n1_8.py tests/test_neural_n1_8_r1.py tests/test_neural_n1_8_r2.py
============================== 38 passed in 2.27s ==============================
```

---

## 5. Forward Observation Runbook & Operational State (Task 4)

Because the current workspace operates in an interactive developer terminal without an independent daemon supervisor, `FORWARD_RECORDER = PAUSED` is retained.

### Operational CLI Runbook

To start or resume forward observation independently on a dedicated runner:

```powershell
# 1. Activate isolated Python environment
cd D:\Workspaces\besttime-crypto
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "."

# 2. Verify SingleWriterLock is clear
# Lockfile path: data/neural_n1_6/control/recorder.lock
# If process is stale, SingleWriterLock safely reclaims automatically.

# 3. Start Public Market-Data Recorder (Read-Only)
python -m neural_trading.n1_6.recorder --poll-interval-s 10

# 4. In a separate scheduled or manual runner, execute Lifecycle Engine
python -m neural_trading.n1_7.lifecycle_engine
```

- **Storage Location:** `data/neural_n1_6/raw/<YYYYMMDD>/`
- **Checkpoint Location:** `data/neural_n1_7/lifecycle_checkpoint.json`
- **Safety Invariant:** The recorder uses public read-only REST endpoints. No order execution endpoints, API credentials, or paper trading daemons are enabled.

---

## 6. Remote Audit Reference (Task 5)

| Field | Value |
|---|---|
| **Repository** | `https://github.com/jarm237/besttime-crypto` |
| **Branch** | `research/m2-historical-sources-pilot` |
| **Base Commit SHA** | `4ec034b8f15cd5f592871720e7130816ba02ffaa` |
| **Target Commit Title** | `fix(neural): close N1.8-R2 carry lifecycle economic defects` |
| **Targeted Tests** | 20 passed (`tests/test_neural_n1_8_r2.py`) |
| **Complete Regression** | 38 passed (`tests/test_neural_n1_*.py`) |
| **Closed Natural Lifecycles** | 0 |
| **Realized Forward Net PnL** | $0.00 |
| **Forward Economic Value** | INCONCLUSIVE |
| **Production Candidate** | FALSE |
| **Real Trading** | DISABLED |
| **Implementation Disposition** | `CLOSED / PASS` |
| **Remote Source Audit Ready** | `TRUE` |
