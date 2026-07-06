# Phase 10 — Execution Intelligence & Slippage Modeling Implementation Plan

> Project: `besttime-crypto` — AI Quant Trading Platform  
> Phase: **10 — Execution Intelligence & Slippage Modeling**  
> Goal: biến paper alpha thành executable alpha bằng cách tối ưu phí, spread, slippage, latency và chất lượng khớp lệnh.  
> Created: 2026-07-07

---

## 1. Executive Summary

Phase 10 bắt đầu sau khi Phase 9 chứng minh chiến lược có edge thật qua:

- Cost model.
- Slippage model v1.
- Walk-forward validation.
- Purged KFold + Embargo.
- Regime split.
- Stress test.
- Monte Carlo test.

Nếu Phase 9 trả lời:

```text
Strategy has real alpha
```

thì Phase 10 trả lời:

```text
Can this alpha be executed in real markets?
```

Goal:

```text
Convert paper alpha into executable alpha
```

---

## 2. Objective

Phase 10 tập trung vào:

- Execution simulator.
- Slippage prediction.
- Liquidity-aware sizing.
- Order type decision.
- Smart execution.
- Execution risk guard.
- Order routing.
- Fill tracking.
- Post-trade analysis.
- ML slippage model từ real/paper fills.

---

## 3. Current Problem

Bot hiện tại có thể ra quyết định:

```text
BUY / SELL / NEUTRAL
```

Nhưng execution thực tế cần trả lời:

```text
Đặt market hay limit?
Vào toàn bộ hay chia nhỏ?
Slippage dự kiến bao nhiêu?
Coin này có đủ thanh khoản không?
Khi spread rộng có nên skip không?
Latency làm giá lệch bao nhiêu?
Nếu không fill limit order thì sao?
Có nên dùng TWAP không?
Có nên giảm size theo orderbook không?
```

---

## 4. Target Architecture

```text
Decision Engine
    ↓
Execution Intelligence Layer
    ├── Liquidity Analyzer
    ├── Slippage Predictor
    ├── Order Type Selector
    ├── Smart Execution Planner
    ├── Order Router
    ├── Fill Tracker
    ├── Post-trade Analyzer
    └── Execution Risk Monitor
    ↓
Exchange Adapter
    ├── Binance
    ├── Bybit optional
    └── OKX optional
    ↓
Execution Logs
    ↓
Execution Model Training Dataset
```

---

## 5. Proposed Folder Structure

```text
btc_scraper/
  execution/
    __init__.py
    execution_engine.py
    execution_config.py
    liquidity_analyzer.py
    slippage_predictor.py
    order_type_selector.py
    execution_planner.py
    order_router.py
    fill_tracker.py
    post_trade_analyzer.py
    execution_risk_monitor.py
    smart_orders.py
    twap.py
    vwap.py
    iceberg.py

  scripts/
    train_slippage_model.py
    analyze_execution_quality.py
    replay_execution.py

data/
  execution/
    fills/
    orderbook_snapshots/
    slippage_dataset/
    reports/

logs/
  execution/
```

---

## 6. Execution Data Schema

Every execution attempt should log:

```python
execution_id
signal_id
timestamp
coin
exchange
market_type
side
intended_qty
intended_notional
order_type
time_in_force
decision_price
submitted_price
filled_price
avg_fill_price
filled_qty
unfilled_qty
fee
fee_asset
spread_bps_at_submit
orderbook_imbalance_at_submit
top_bid
top_ask
mid_price
latency_ms
submit_time
first_fill_time
last_fill_time
status
reason
```

Derived:

```python
arrival_price
decision_to_submit_slippage_bps
submit_to_fill_slippage_bps
total_slippage_bps
implementation_shortfall_bps
market_impact_bps
opportunity_cost_bps
```

---

## 7. Liquidity Analyzer

### 7.1. Inputs

```python
orderbook_top_20
orderbook_top_100
spread_bps
volume_1m
volume_5m
volume_1h
atr_pct
open_interest
funding_rate
recent_trades
```

### 7.2. Features

```python
spread_bps
depth_1bps
depth_5bps
depth_10bps
bid_depth
ask_depth
orderbook_imbalance
liquidity_wall_distance
market_impact_estimate
volume_participation_rate
```

### 7.3. Liquidity Score

```python
liquidity_score = (
    0.25 * normalized_depth
    + 0.20 * inverse_spread_score
    + 0.20 * volume_score
    + 0.15 * orderbook_stability
    + 0.10 * inverse_volatility
    + 0.10 * fill_probability_score
)
```

Output:

```python
liquidity_score
max_safe_order_size
recommended_order_type
liquidity_warning
```

---

## 8. Slippage Predictor

### 8.1. v1 Rule-based Model

```python
expected_slippage_bps = (
    base_slippage_bps
    + 0.3 * spread_bps
    + 0.2 * atr_pct
    + 0.4 * order_size_pct_depth
    + 0.2 * volatility_score
    - 0.2 * liquidity_score
)
```

### 8.2. v2 ML Model

Training target:

```python
realized_slippage_bps
```

Features:

```python
coin
side
order_type
notional
spread_bps
atr_pct
volume_1m
volume_5m
orderbook_imbalance
depth_5bps
depth_10bps
latency_ms
time_of_day
session
regime
```

Models:

```text
Baseline: Linear / Ridge
Main: LightGBM Regressor
Fallback: Rule-based v1
```

Metrics:

```python
mae_bps
rmse_bps
p95_error_bps
calibration_by_coin
```

---

## 9. Order Type Selector

Decision rules:

```python
if urgency == "HIGH":
    prefer MARKET or aggressive LIMIT

elif spread_bps > max_spread_bps:
    skip or passive LIMIT

elif liquidity_score < min_liquidity_score:
    reduce size or skip

elif expected_slippage_bps > max_allowed_slippage_bps:
    use TWAP or reduce size

else:
    use LIMIT_MAKER or passive LIMIT
```

Output:

```python
order_type
limit_price
time_in_force
max_wait_seconds
fallback_action
```

---

## 10. Smart Execution Strategies

### 10.1. Market Order

Use only when:

```text
SL emergency
high urgency exit
low spread
high liquidity
```

Risk:

```text
higher slippage
```

---

### 10.2. Limit Order

Use when:

```text
normal entry
spread is moderate
liquidity is good
```

Policy:

```python
limit_price_long = best_bid + tick_size
limit_price_short = best_ask - tick_size
```

---

### 10.3. Aggressive Limit

Use when:

```text
need fill but want slippage cap
```

Policy:

```python
aggressive_limit_buy = best_ask
aggressive_limit_sell = best_bid
```

---

### 10.4. TWAP

Use when:

```text
order size is large relative to depth / volume
```

Config:

```python
twap_config = {
    "slices": 5,
    "interval_seconds": 30,
    "max_duration_seconds": 180,
    "cancel_on_signal_reversal": True,
}
```

---

### 10.5. VWAP

Use when:

```text
enough intraday volume profile exists
```

Phase 10 optional.

---

### 10.6. Iceberg

Use when:

```text
large size and exchange supports iceberg
```

Phase 10 optional.

---

## 11. Execution Risk Guard

Before sending order:

```python
if spread_bps > MAX_SPREAD_BPS:
    reject("spread_too_wide")

if expected_slippage_bps > MAX_SLIPPAGE_BPS:
    reject("slippage_too_high")

if liquidity_score < MIN_LIQUIDITY_SCORE:
    reject("insufficient_liquidity")

if order_size > max_safe_order_size:
    reduce_size_or_reject()

if exchange_latency_ms > MAX_LATENCY_MS:
    reject("latency_too_high")
```

Recommended defaults:

```python
execution_guard_config = {
    "max_spread_bps": 20,
    "max_slippage_bps": 30,
    "min_liquidity_score": 0.4,
    "max_latency_ms": 1500,
    "max_participation_rate": 0.02,
}
```

---

## 12. Post-trade Analysis

For every fill:

```python
implementation_shortfall_bps = (
    (avg_fill_price - decision_price) / decision_price * 10000
)
```

For SELL, reverse sign.

Breakdown:

```python
decision_to_submit_delay
submit_to_fill_delay
price_drift
spread_cost
slippage_cost
fee_cost
opportunity_cost
```

Example report:

```text
This trade lost 18 bps to execution:
- 5 bps spread
- 8 bps slippage
- 3 bps fee
- 2 bps latency drift
```

---

## 13. Execution Simulator

Phase 10 must integrate with Phase 9.

Backtest should support:

```python
execution_mode = [
    "ideal_fill",
    "spread_aware",
    "slippage_model_v1",
    "slippage_model_ml",
    "orderbook_replay",
]
```

Approval:

```text
Strategy must pass under slippage_model_v1 before paper/live.
```

---

## 14. Integration with Phase 9

Flow:

```text
Phase 9 Backtest
    ↓
Find candidate strategy
    ↓
Apply cost model
    ↓
Apply slippage model
    ↓
Apply latency model
    ↓
Run stress test
    ↓
Run Monte Carlo
    ↓
If passed:
    ↓
Phase 10 Paper Execution
    ↓
Collect execution logs
    ↓
Train slippage model
    ↓
Compare expected vs realized
    ↓
Approve live execution
```

---

## 15. Phase 10 Sprint Plan

### Sprint 10.1 — Execution Logging Foundation

Tasks:

- Define execution log schema.
- Log all submitted orders.
- Log all fills.
- Log spread/orderbook at submit.
- Store execution dataset.

Deliverables:

```text
execution_engine.py
fill_tracker.py
execution_log_schema.json
```

Acceptance Criteria:

- Every order has execution_id.
- Every fill has slippage metrics.
- Logs can train slippage model later.

---

### Sprint 10.2 — Liquidity Analyzer

Tasks:

- Capture orderbook snapshots.
- Compute spread/depth/imbalance.
- Compute liquidity score.
- Estimate max safe order size.

Deliverables:

```text
liquidity_analyzer.py
orderbook_snapshot_store.py
```

Acceptance Criteria:

- Liquidity score available per symbol.
- Max safe order size generated.
- Low-liquidity trades can be blocked.

---

### Sprint 10.3 — Slippage Predictor v1

Tasks:

- Implement rule-based slippage predictor.
- Add config thresholds.
- Integrate with backtest and live execution.
- Log expected vs realized slippage.

Deliverables:

```text
slippage_predictor.py
slippage_model_v1_config.json
```

Acceptance Criteria:

- Expected slippage available before order.
- High slippage trades can be skipped.
- Backtest supports slippage model v1.

---

### Sprint 10.4 — Order Type Selector

Tasks:

- Implement order type selection.
- Add market/limit/aggressive-limit logic.
- Add fallback if limit does not fill.
- Add max wait time.

Deliverables:

```text
order_type_selector.py
```

Acceptance Criteria:

- Order type is chosen automatically.
- Emergency exits use proper urgency.
- Limit order fallback works.

---

### Sprint 10.5 — Smart Execution Planner

Tasks:

- Implement TWAP.
- Add order slicing.
- Add cancel on reversal.
- Add max duration.
- Add partial fill handling.

Deliverables:

```text
execution_planner.py
twap.py
smart_orders.py
```

Acceptance Criteria:

- Large orders can be split.
- Partial fills tracked correctly.
- Execution stops on signal reversal.

---

### Sprint 10.6 — Execution Risk Guard

Tasks:

- Add pre-trade execution checks.
- Add max spread/slippage/liquidity thresholds.
- Add latency checks.
- Add dynamic size reduction.

Deliverables:

```text
execution_risk_monitor.py
```

Acceptance Criteria:

- Bad execution conditions block trades.
- Bot can reduce size instead of only reject.
- Reasons are logged.

---

### Sprint 10.7 — Post-trade Analyzer

Tasks:

- Compute implementation shortfall.
- Decompose execution cost.
- Compare expected vs realized slippage.
- Generate execution quality report.

Deliverables:

```text
post_trade_analyzer.py
scripts/analyze_execution_quality.py
```

Acceptance Criteria:

- Every executed trade has execution quality metrics.
- Slippage prediction error is tracked.
- Worst execution cases are visible.

---

### Sprint 10.8 — ML Slippage Model v2

Tasks:

- Build slippage dataset.
- Train baseline model.
- Train LightGBM regressor.
- Compare rule vs ML.
- Deploy ML only if stable.

Deliverables:

```text
scripts/train_slippage_model.py
slippage_model_v2.joblib
slippage_model_v2.json
```

Acceptance Criteria:

- ML model beats rule baseline.
- Error by coin is acceptable.
- Rule model remains fallback.

---

## 16. Config File

### `execution_config.json`

```json
{
  "execution": {
    "enabled": true,
    "dry_run": true,
    "max_spread_bps": 20,
    "max_slippage_bps": 30,
    "min_liquidity_score": 0.4,
    "max_latency_ms": 1500,
    "max_participation_rate": 0.02,
    "default_order_type": "LIMIT",
    "emergency_order_type": "MARKET",
    "limit_order_max_wait_seconds": 30,
    "twap": {
      "enabled": true,
      "slices": 5,
      "interval_seconds": 30,
      "max_duration_seconds": 180
    }
  }
}
```

---

## 17. Paper-to-Live Approval Gate

A strategy can move from paper to live only if:

```python
paper_approval_rules = {
    "min_paper_trades": 50,
    "realized_slippage_within_expected_p75": True,
    "execution_reject_rate_below": 0.20,
    "no_critical_execution_incidents": True,
    "paper_net_pnl_not_worse_than_backtest_by": 0.30,
}
```

---

## 18. Dashboard Additions

Execution tab panels:

```text
Spread by coin
Slippage expected vs realized
Liquidity score
Execution reject reasons
Order type distribution
Fill quality
Implementation shortfall
Latency
Post-trade cost breakdown
```

---

## 19. Testing Plan

Unit tests:

```text
tests/test_liquidity_analyzer.py
tests/test_slippage_predictor.py
tests/test_order_type_selector.py
tests/test_execution_risk_monitor.py
tests/test_twap.py
tests/test_post_trade_analyzer.py
```

Integration tests:

```text
tests/test_phase10_execution_pipeline.py
tests/test_phase9_phase10_integration.py
```

Critical test cases:

```text
Market order fills immediately
Limit order can timeout
Partial fill handled
TWAP slices correctly
Execution guard rejects high spread
Execution guard rejects high slippage
Execution guard reduces size when liquidity is low
Post-trade shortfall calculated correctly
Expected vs realized slippage logged
Fallback to rule model if ML model missing
```

---

## 20. Recommended Implementation Order

Do not start with TWAP or ML slippage.

Recommended order:

```text
1. Execution Logging
2. Liquidity Analyzer
3. Slippage Model v1
4. Order Type Selector
5. Execution Risk Guard
6. Integration with Phase 9 Backtest
7. TWAP
8. Post-trade Analyzer
9. ML Slippage Model v2
10. Dashboard Execution Tab
```

Reason:

```text
First measure execution
Then guard bad execution
Then optimize order placement
Then train ML execution models
```

---

## 21. Final Deliverables

```text
btc_scraper/execution/
scripts/train_slippage_model.py
scripts/analyze_execution_quality.py
scripts/replay_execution.py
data/execution/fills/
data/execution/orderbook_snapshots/
data/execution/slippage_dataset/
data/execution/reports/
execution_config.json
dashboard Execution tab
tests/test_phase10_*.py
```

---

## 22. Definition of Done

Phase 10 is complete when:

- Execution logs are complete.
- Liquidity score is available.
- Slippage model v1 is active.
- Backtest supports execution simulation.
- Order type selector is active.
- Execution risk guard blocks bad fills.
- TWAP works for large orders.
- Post-trade analysis is generated.
- ML slippage model v2 is trained from real/paper fills.
- Dashboard shows execution quality.

---

## 23. Final Recommendation

Phase 10 chỉ nên chạy sau khi Phase 9 pass.

```text
If Phase 9 passes but Phase 10 fails:
    strategy has paper alpha but not executable alpha

If Phase 10 passes:
    strategy can move from paper trading toward controlled live trading
```
