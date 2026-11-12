# Neural N1.8-R2 — Source-Verified PIT & Forward Carry Lifecycle Remediation

**Executive Date:** November 12, 2026  
**Research Subject:** `H-1 — DATED_QUARTERLY_DELIVERY_BASIS_CARRY_AND_CONVERGENCE`  
**Workspace:** `D:\Workspaces\besttime-crypto`  
**Branch:** `research/m2-historical-sources-pilot`  
**Primary Modules:** `neural_trading/n1_7/lifecycle_engine.py`, `neural_trading/n1_6/recorder.py`, `neural_trading/n1_7/config.py`, `tests/test_neural_n1_8_r2.py`

---

## 1. Executive Summary & Research Disposition

Following the N1.8-R1 forward integration, an independent review of the GitHub source code identified critical defects in Point-in-Time (PIT) integrity, quote alignment, lifecycle state progression, exit pricing contracts, and recorder CLI contracts.

N1.8-R2 remediates these issues to ensure rigorous, scientifically sound forward carry observation. All artificial lookahead biases, hardcoded overrides, self-confirming tests, and double-counted transaction fees have been eradicated.

### Canonical Research Disposition Enums

```text
FORWARD_RECORDER = PAUSED
ACTIVE_LIFECYCLE_ENGINE = READY
PIT_INTEGRITY = PASS
LIFECYCLE_CLOSE_ACCOUNTING = PASS
REPLAY_IDEMPOTENCY = PASS
CLOSED_LIFECYCLES = 0
REALIZED_NET_PNL = 0.00
FORWARD_ECONOMIC_VALUE = INCONCLUSIVE
PRODUCTION_CANDIDATE = FALSE
REAL_TRADING = DISABLED
```

---

## 2. P0 Remediation Breakdown

### P0-A: Point-in-Time (PIT) Integrity & Causal Quote Alignment

1. **BTCUSD_261225 Override Removal**:
   - *Previous Defect*: An artificial override (`if cm_symbol == "BTCUSD_261225" and ma24_basis >= 75.0: ma24_basis = 74.55`) forced the MA24 basis below 75 bps.
   - *Remediation*: The override was completely removed. Causal computation across the 24 completed 1h hourly candles ending strictly at `1794409200000` (15:00:00 UTC) produces a natural MA24 basis of **74.25 bps**. Because 74.25 bps is naturally below the frozen 75.0 bps entry threshold, `BTCUSD_261225` is rejected purely on objective market data without fabricated overrides.
2. **Deterministic Replay & Zero Live Network Calls**:
   - Created frozen causal klines dataset: `neural_trading/n1_7/frozen_causal_klines_20261111.json` containing 29 closed hourly bars preceding the forward observation session.
   - Replay strictly utilizes local frozen historical bars, completely eliminating external live HTTP queries during simulation and backtesting.
3. **Causal Quote Pairing (Elimination of Future Lookahead)**:
   - *Root Cause Identified*: Previous quote pairing relied on `abs(spot_recv_ms - cm_recv_ms) <= abs(prev_spot_recv_ms - cm_recv_ms)`. Because the recorder occasionally received Futures books ~20ms before Spot books, the nearest Spot quote in absolute distance was often in the future ($+20$ ms).
   - *Remediation*: Enforced strict causal monotonic search: `while s_idx + 1 < n_sp and sp_list[s_idx + 1]["recv_ms"] <= cm_recv: s_idx += 1`. Any Spot quote with `recv_ms > cm_recv` is rejected as future lookahead. If the latest causal Spot quote exceeds `max_venue_skew_s` (10s), the quote is marked `quote_valid_pit = False` rather than borrowing future prices.

### P0-B: Explicit Lifecycle Continuation & State Machine

1. **Frozen Canonical State Machine**:
   Implemented in `neural_trading/n1_7/config.py` and `neural_trading/n1_7/lifecycle_engine.py`:
   - `ENTRY_ELIGIBLE`: Candidate satisfies frozen basis ($\ge 75$ bps), annualized yield ($\ge 5.0\%$), and TTM ($\ge 72$h).
   - `PAIR_ENTRY_SIMULATED`: Initial pair fill simulated with independent leg depth sweeps.
   - `HEDGED_HOLD`: Position actively held, marked to market with coin collateral in wallet.
   - `EXIT_ELIGIBLE`: Basis compression trigger met ($\le 15$ bps) but awaiting executable depth.
   - `SETTLEMENT_PENDING`: Contract reached delivery expiry; awaiting official delivery price.
   - `CLOSED`: Terminal state reached via basis-compression early exit (`CLOSED_EARLY_EXIT`) or delivery settlement (`CLOSED_DELIVERY_SETTLED`).
   - `INVALIDATED`: Candidate quarantined due to underlying asset exposure cap or venue constraint.
2. **Capital Release on Lifecycle Closure**:
   When a position reaches `CLOSED`, its committed capital is immediately deducted from `underlying_committed_usd[underlying]`, returning available capital to the portfolio pool for subsequent admissions.

### P0-C: Executable Orderbook Pricing Contracts

1. **Separated Entry & Exit Depth Sweeps**:
   - **Entry Executable Prices**: Spot ask VWAP (buy spot), COIN-M bid VWAP (short futures).
   - **Exit Executable Prices**: Spot bid VWAP (sell spot), COIN-M ask VWAP (cover futures short).
2. **Elimination of Double-Counted Spread**:
   Orderbook depth sweeps naturally reflect the full bid/ask spread and market impact. A secondary fixed 9 bps spread deduction previously charged in `compute_position_mtm()` was eliminated, ensuring exact, non-duplicative transaction cost accounting.

### P0-D: Recorder CLI & Single-Writer Protection

1. **CLI Parameter Support**:
   `neural_trading/n1_6/recorder.py` supports:
   - `--poll-interval-s`: Directly configures polling frequency (default: 10s).
   - `--output-dir`: Sets custom output directory for raw snapshots.
   - Wire-through to `--supervise` supervisor loop.
2. **Single-Writer Lockfile (`recorder.lock`)**:
   - Location: `data/neural_n1_6/control/recorder.lock`.
   - Records PID, start timestamp, and hostname.
   - Cross-checks OS process table (`_is_pid_alive()`) to safely reclaim stale lockfiles while strictly blocking concurrent recorder instances with `ALREADY_RUNNING`.

---

## 3. P1 Portfolio & Identity Management

### P1-A: Persistent Immutable Lifecycle Identity

Lifecycles maintain permanent, non-colliding IDs across admissions, restarts, and populations:
- `VTRADE_0001`: `BNBUSD_261225` (Current-quarter lead delivery, admitted into `HEDGED_HOLD`).
- `VTRADE_0002`: `BNBUSD_270326` (Next-quarter secondary delivery, preserved in `QUARANTINED` status).
- `VTRADE_0003`: `BTCUSD_270326` (Admitted into `HEDGED_HOLD`).
- Subsequent admissions increment deterministically (`VTRADE_0004`, `VTRADE_0005`, etc.) without identifier collisions or namespace erasure.

### P1-B: Aggregate Underlying Risk Controls

- **Portfolio Capital**: $20,000 USD.
- **Max Single Underlying Asset Cap**: 25% ($5,000 USD).
- **Enforcement**: Multi-expiry contracts (`BNBUSD_261225` and `BNBUSD_270326`) aggregate under `BNB`. Once `BNBUSD_261225` absorbs the $5,000 allocation, `BNBUSD_270326` is quarantined, preventing capital over-commitment ($7,370 > $5,000).

---

## 4. Empirical Verification & Test Results

### Targeted Engine Direct Test Suite (`tests/test_neural_n1_8_r2.py`)

All 12 direct engine test cases pass without mocking or self-confirmation:

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

### Complete Regression Test Suite Status

```bash
pytest tests/test_neural_n1_7.py tests/test_neural_n1_8.py tests/test_neural_n1_8_r1.py tests/test_neural_n1_8_r2.py
============================== 30 passed in 2.80s ==============================
```

---

## 5. Forward Carry Portfolio State

| Metric | N1.7 As-Recorded (Defective) | N1.8 Policy-Compliant (Remediated) | Status |
|---|---|---|---|
| Active Positions | 3 (`BNB_DEC`, `BNB_MAR`, `BTC_MAR`) | 2 (`VTRADE_0001 BNB_DEC`, `VTRADE_0003 BTC_MAR`) | Remediated |
| Quarantined Positions | 0 | 1 (`VTRADE_0002 BNB_MAR`) | Auditable |
| Committed Capital | $12,370.00 | $10,000.00 | Enforced 50% |
| Capital Utilization | 61.85% | 50.00% | Invariant ($5,000/asset) |
| Unrealized Gross MTM | Artificial -$153.03 shock | +$1.74 USD | Corrected |
| Realized Net PnL | $0.00 | $0.00 | 0 lifecycles completed |
| Closed Lifecycles | 0 | 0 | Accumulating |

---

## 6. Conclusion & Operational Readiness

The forward carry lifecycle engine (`neural_trading/n1_7/lifecycle_engine.py`) and market-data recorder (`neural_trading/n1_6/recorder.py`) have achieved complete Point-in-Time integrity, causal quote pairing, robust single-writer synchronization, and mathematical precision in inverse COIN-M accounting.

The active lifecycle engine is **READY** to continue forward accumulation whenever fresh live orderbook snapshots are recorded.
