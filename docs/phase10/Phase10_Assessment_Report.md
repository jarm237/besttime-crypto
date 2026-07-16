# Phase 10 Assessment Report

> Date: 2026-07-14
> Scope: `docs/phase10/`, `btc_scraper/execution/`, API/UI execution integration, Phase 10 tests
> Verdict: **Partially production-ready for paper execution; not yet fully proven for controlled live execution.**

---

## 1. Executive Verdict

Phase 10 has a real implementation backbone:

- Execution logging and fill tracking exist.
- Liquidity scoring exists.
- Rule-based slippage prediction exists.
- Order type selection exists.
- Pre-trade guards exist.
- Post-trade quality reporting exists.
- API and dashboard integration exist.
- Phase 9 + Phase 10 test suite passes.

However, the current implementation is stronger as a **paper execution and simulation layer** than as a complete live execution intelligence layer. The main gaps are:

- Live execution still routes selected orders through market buy/sell calls only.
- TWAP is implemented as a planner/executor object but is not actually dispatched by `ExecutionEngine.submit_live()`.
- Live liquidity analysis uses candle-derived synthetic liquidity instead of real orderbook depth.
- ML slippage v2 training and inference feature schemas do not match.
- Training script only scans top-level fill JSONL files, while paper fills are written under `data/execution/fills/paper/`.
- Existing tests validate the module behavior, but do not fully prove live routing, TWAP dispatch, limit order lifecycle, or real orderbook integration.

Recommended status:

```text
Phase 10 paper/simulation readiness: PASS
Phase 10 live execution readiness: CONDITIONAL / NEEDS HARDENING
```

---

## 1.1. Signal Flow Context

Phase 10 sits after the signal detection/scoring gate. The current upstream flow is documented in [`../../evaluations/signal_detection_and_scoring_assessment.md`](../../evaluations/signal_detection_and_scoring_assessment.md):

```text
analyze_market() -> score_signal() -> CausalGate -> Risk/Portfolio gates
-> AutoTrader.should_trade() -> ExecutionEngine
```

This matters for Phase 10 readiness because execution quality can only be interpreted after confirming that:

- the signal has `meta_confidence`,
- the signal is not `WEAK`,
- causal/risk/portfolio gates did not block it,
- and the score threshold semantics are understood, especially for SELL where internal score and display score differ.

---

## 2. Evidence Reviewed

Documentation:

- `docs/phase10/Phase10_Execution_Intelligence_Implementation_Plan.md`
- `docs/phase10/walkthrough.md`

Core implementation:

- `btc_scraper/execution/execution_engine.py`
- `btc_scraper/execution/fill_tracker.py`
- `btc_scraper/execution/liquidity_analyzer.py`
- `btc_scraper/execution/slippage_predictor.py`
- `btc_scraper/execution/order_type_selector.py`
- `btc_scraper/execution/execution_planner.py`
- `btc_scraper/execution/twap.py`
- `btc_scraper/execution/execution_risk_monitor.py`
- `btc_scraper/execution/post_trade_analyzer.py`
- `btc_scraper/execution/exchange_adapter.py`

Integration:

- `api/server.py`
- `web/src/App.jsx`
- `scripts/train_slippage_model.py`
- `scripts/analyze_execution_quality.py`
- `scripts/replay_execution.py`

Validation command:

```bash
.venv/bin/python -m pytest tests/test_phase9_backtesting.py tests/test_phase10_execution_pipeline.py -q
```

Result:

```text
33 passed
```

---

## 3. Completion Checklist

| Requirement from Phase 10 plan | Current status | Assessment |
| --- | --- | --- |
| Execution logs are complete | Implemented | `ExecutionRecord` has the planned fields and JSONL persistence. |
| Liquidity score is available | Implemented | `LiquidityAnalyzer` computes score, spread, depth, imbalance, safe size. |
| Slippage model v1 is active | Implemented | Rule-based predictor is active by default. |
| Backtest supports execution simulation | Mostly implemented | Paper execution uses candle-derived synthetic liquidity and simulated fills. |
| Order type selector is active | Partially integrated | Selector runs, but live dispatch ignores non-market order semantics. |
| Execution risk guard blocks bad fills | Implemented | Spread, slippage, liquidity, latency, and size checks exist. |
| TWAP works for large orders | Partially implemented | TWAP planning exists, but engine does not dispatch TWAP child orders. |
| Post-trade analysis is generated | Implemented | Quality report is available through engine/API/UI when fills exist. |
| ML slippage model v2 trained from fills | Not proven | Training script exists, but dataset path and feature schema need fixes. |
| Dashboard shows execution quality | Implemented | Execution tab, simulator, metrics, and quality table exist. |

---

## 4. Key Findings

### High Severity

1. **Order type decisions are not faithfully executed in live mode.**

   `OrderTypeSelector` can return `LIMIT`, `AGGRESSIVE_LIMIT`, or `TWAP`, but `ExecutionEngine.submit_live()` always calls `create_market_buy()` or `create_market_sell()` after selection. This means the selected execution style is recorded, but not actually enforced at the exchange adapter level.

   Impact:

   - Passive limit behavior is not real.
   - TWAP is not live.
   - Limit fallback, timeout, and partial-fill behavior are not exercised in live routing.
   - Execution quality can look better/worse than intended because the recorded order type may not match the actual submitted order.

2. **Live liquidity analysis is synthetic, not orderbook-based.**

   `submit_live()` uses `analyze_from_candle()`, which estimates spread/depth from OHLCV. This is useful for simulation, but Phase 10's stated goal is real execution quality using orderbook depth, spread, and liquidity conditions.

   Impact:

   - Liquidity guard can pass/reject on stale or approximate data.
   - Market impact estimates are weak for thin books.
   - Real spread widening may not be caught before live orders.

3. **ML slippage v2 training is not wired cleanly to inference.**

   The predictor expects a 12-feature model, while the training script trains on 5 features. A model produced by the current script may fail or degrade inference, then silently fall back to v1.

   Impact:

   - ML v2 completion claim is not reliable.
   - Calibration reports may not reflect active model behavior.

4. **Paper fill training data path is likely missed by the trainer.**

   `FillTracker` writes paper fills under `data/execution/fills/paper/`, but `train_slippage_model.py` scans only `*.jsonl` at the top-level fills directory.

   Impact:

   - Training can report insufficient samples even when paper fills exist.
   - ML slippage v2 may never train from the intended paper dataset.

### Medium Severity

5. **Walkthrough overstates live readiness.**

   `walkthrough.md` says the stack is complete and "All systems perform as required." The implementation supports that claim for test-covered paper execution, but not yet for full live execution intelligence.

6. **TWAP lifecycle is module-level, not engine-level.**

   `TWAPExecutor` can create child slices and cancel on reversal, but there is no engine loop that submits due slices, records child order IDs, tracks partial fills, or cancels remaining live orders.

7. **API submit endpoint is paper-only.**

   `/api/execution/submit` calls `submit_paper()`. This is safe and useful for dashboard simulation, but it should be labeled clearly as simulator-only, not live order routing.

8. **Tests do not cover full live execution semantics.**

   Existing Phase 10 tests pass, but they mainly validate local formulas and paper path behavior. Missing tests include:

   - `TWAP` decision actually dispatches slices.
   - `LIMIT` decision creates limit orders, waits, cancels, or falls back.
   - Real orderbook data feeds liquidity analyzer.
   - Slippage model trained by script can be loaded by predictor.

---

## 5. Recommended Remediation Plan

### Priority 1 — Make Live Routing Honest

- Extend `WriteExchangeAdapter` with limit, aggressive-limit, cancel, and status methods.
- In `ExecutionEngine.submit_live()`, dispatch based on `order_decision.order_type`.
- Ensure record fields match the actual submitted order type.
- Add live-path tests with a mock adapter for `MARKET`, `LIMIT`, `AGGRESSIVE_LIMIT`, and `TWAP`.

### Priority 2 — Use Real Orderbook Data

- Add adapter method to fetch top-N orderbook.
- Route live liquidity analysis through `LiquidityAnalyzer.analyze()` instead of `analyze_from_candle()`.
- Keep `analyze_from_candle()` only for paper/backtest fallback.
- Log raw orderbook snapshot references for replay/calibration.

### Priority 3 — Fix ML Slippage v2 Dataset Contract

- Align `scripts/train_slippage_model.py` `FEATURE_COLS` with `SlippagePredictorV2.FEATURE_COLS`.
- Make trainer recursively scan `data/execution/fills/**/*.jsonl`.
- Save model metadata beside the model and validate schema before loading.
- Add a test: train/load a tiny model fixture and verify predictor inference does not fall back.

### Priority 4 — Integrate TWAP End-to-End

- Add TWAP plan persistence.
- Add child order submission state.
- Track partial fills per child order.
- Cancel remaining slices on signal reversal or timeout.
- Include TWAP quality in post-trade reports.

### Priority 5 — Update Documentation

- Change `walkthrough.md` from "complete live execution stack" to a more accurate status:

```text
Paper execution intelligence is implemented and tested.
Live execution guardrails exist, but live order-style routing, orderbook-based liquidity,
and ML slippage v2 calibration still require hardening before controlled live rollout.
```

---

## 6. Final Recommendation

Phase 10 should be treated as:

```text
Approved for paper execution simulation and dashboard monitoring.
Not yet approved as fully complete live execution intelligence.
```

Before moving from paper trading to controlled live trading, complete at least:

1. Real orderbook-based liquidity in live mode.
2. Adapter-level order type dispatch.
3. TWAP child order lifecycle.
4. ML slippage v2 schema/path fixes.
5. Live-path test coverage with mocked exchange adapter.
