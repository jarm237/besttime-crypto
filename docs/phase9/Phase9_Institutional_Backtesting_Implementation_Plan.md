# Phase 9 — Institutional Backtesting & Validation Implementation Plan

> Project: `besttime-crypto` — AI Quant Trading Platform  
> Phase: **9 — Institutional Backtesting & Validation**  
> Goal: chứng minh chiến lược có alpha thật sau khi tính phí, spread, slippage, latency, regime split và stress test.  
> Created: 2026-07-07

---

## 1. Executive Summary

Sau Phase 7 và Phase 8, hệ thống đã có:

- Alternative Data Layer.
- Feature Store v2.
- Meta-labeling.
- Triple Barrier Labeling.
- ML Dataset v3.
- Causal World Model.
- ML Ensemble.
- Risk Manager.
- Portfolio Manager.
- RL Exit Manager.

Điểm yếu còn lại là backtest chưa đủ nghiêm ngặt để trả lời:

```text
Chiến lược có sống được sau phí + spread + slippage không?
Có bị overfit không?
Có ổn định qua nhiều regime không?
Có phụ thuộc vào vài trade may mắn không?
Model có bị leak dữ liệu tương lai không?
Nếu latency tăng, kết quả còn tốt không?
Nếu thị trường crash như FTX/LUNA thì sao?
```

Phase 9 có nhiệm vụ:

```text
Prove the strategy is real before paper/live trading
```

---

## 2. Objective

Xây dựng backtesting framework đủ nghiêm ngặt để đánh giá chiến lược theo tiêu chuẩn gần institutional:

- Không look-ahead bias.
- Không data leakage.
- Có walk-forward validation.
- Có purged cross-validation.
- Có embargo.
- Có transaction cost model.
- Có slippage model cơ bản.
- Có latency model.
- Có regime split.
- Có stress test.
- Có Monte Carlo robustness test.
- Có performance attribution.
- Có report tự động.

---

## 3. Target Architecture

```text
Feature Store v2
ML Dataset v3
WorldState Snapshots
Trade Logs
Alternative Data
        ↓
Backtest Engine v2
        ├── Event-driven Replay
        ├── Vectorized Backtest
        ├── Walk-forward Validator
        ├── Purged KFold Validator
        ├── Embargo Manager
        ├── Cost Model
        ├── Slippage Model v1
        ├── Latency Model
        ├── Regime Split Analyzer
        ├── Stress Test Engine
        ├── Monte Carlo Engine
        └── Performance Attribution
        ↓
Reports
        ├── HTML
        ├── JSON
        ├── CSV
        └── Dashboard
```

---

## 4. Proposed Folder Structure

```text
btc_scraper/
  backtesting/
    __init__.py
    engine.py
    event_replay.py
    vectorized_engine.py
    walk_forward.py
    purged_kfold.py
    embargo.py
    cost_model.py
    slippage_model_v1.py
    latency_model.py
    regime_split.py
    stress_test.py
    monte_carlo.py
    metrics.py
    attribution.py
    report_builder.py
    config.py

  scripts/
    run_backtest_v2.py
    run_walk_forward.py
    run_stress_tests.py
    run_monte_carlo.py
    generate_backtest_report.py

data/
  backtests/
    runs/
    reports/
    monte_carlo/
    stress_tests/

logs/
  backtesting/
```

---

## 5. Backtest Types

### 5.1. Event-driven Backtest

Use case:

- Mô phỏng sát production.
- Dùng WorldState, Snapshot, Decision Engine, Risk Manager.
- Phù hợp để replay decision.

Flow:

```text
Historical Candle
    ↓
WorldState Builder
    ↓
FeatureSnapshot
    ↓
Signal Engine
    ↓
ML Meta Model
    ↓
Causal Context
    ↓
Risk Manager
    ↓
Portfolio Manager
    ↓
Execution Simulator
    ↓
Position Tracker
    ↓
Metrics
```

Pros:

- Sát production.
- Dễ debug.
- Dễ giải thích.

Cons:

- Chậm hơn vectorized.

---

### 5.2. Vectorized Backtest

Use case:

- Scan nhanh nhiều tham số.
- Tối ưu threshold.
- So sánh chiến lược.

Flow:

```text
DataFrame features
    ↓
Signal columns
    ↓
Entry/Exit columns
    ↓
Cost model
    ↓
Performance metrics
```

Pros:

- Nhanh.
- Tốt cho research.

Cons:

- Dễ sai nếu không kiểm soát leakage.

---

### 5.3. Hybrid Backtest

Khuyến nghị:

```text
Research stage → Vectorized
Validation stage → Event-driven
Production approval → Event-driven + Monte Carlo + Stress Test
```

---

## 6. Data Requirements

Input dataset:

```python
timestamp
coin
timeframe
open
high
low
close
volume
features...
meta_confidence
causal_risk_level
regime
signal
direction
entry_price
sl_price
tp1_price
tp2_price
```

Required execution fields:

```python
spread_bps
fee_bps
estimated_slippage_bps
latency_ms
order_type
liquidity_score
```

Required label fields from Phase 8:

```python
triple_barrier_label
meta_label
trade_quality_score
mfe_pct
mae_pct
hold_bars
```

---

## 7. Cost Model

### 7.1. Fee Model

Default:

```python
fee_config = {
    "spot_maker_bps": 10,
    "spot_taker_bps": 10,
    "futures_maker_bps": 2,
    "futures_taker_bps": 5,
    "use_bnb_discount": False,
}
```

Formula:

```python
fee_cost = notional * fee_bps / 10000
round_trip_fee = entry_fee + exit_fee
```

---

### 7.2. Spread Model

```python
spread_cost_bps = (ask - bid) / mid * 10000
```

For market order:

```python
entry_price_long = ask
exit_price_long = bid
entry_price_short = bid
exit_price_short = ask
```

---

### 7.3. Slippage Model v1

Initial simple model:

```python
slippage_bps = (
    base_slippage_bps
    + volatility_component
    + size_component
    + liquidity_component
)
```

Example:

```python
slippage_bps = (
    1.0
    + 0.2 * atr_pct
    + 0.5 * order_size_pct_adv
    + 0.3 * spread_bps
)
```

Fields:

```python
estimated_slippage_bps
realized_slippage_bps
slippage_reason
```

---

### 7.4. Latency Model v1

```python
effective_entry_time = signal_time + latency_ms
effective_entry_price = next_available_price_after_latency
```

Latency scenarios:

```python
latency_ms = [0, 100, 250, 500, 1000, 3000]
```

---

## 8. Walk-forward Validation

### 8.1. Purpose

Kiểm tra chiến lược có ổn định theo thời gian không.

Example:

```text
Train: 2024-01 → 2024-06
Test:  2024-07

Train: 2024-02 → 2024-07
Test:  2024-08

Train: 2024-03 → 2024-08
Test:  2024-09
```

### 8.2. Config

```python
walk_forward_config = {
    "train_months": 6,
    "test_months": 1,
    "step_months": 1,
    "min_train_samples": 1000,
    "retrain_model": True,
    "reoptimize_threshold": True,
}
```

### 8.3. Output

```python
window_id
train_start
train_end
test_start
test_end
n_train
n_test
roc_auc
win_rate
profit_factor
sharpe
max_drawdown
calibration_error
```

---

## 9. Purged K-Fold + Embargo

### 9.1. Why Needed

Trong trading, sample gần nhau có overlap thông tin.

Nếu dùng KFold thường:

```text
Train sample có thể biết tương lai gần của test sample
```

Dẫn tới overfit.

---

### 9.2. Purging

Remove training samples whose label horizon overlaps test period.

```python
if train_label_end_time >= test_start_time and train_start_time <= test_end_time:
    remove_from_train
```

---

### 9.3. Embargo

Sau test fold, bỏ thêm một khoảng thời gian.

```python
embargo_bars = max_holding_bars
```

Example:

```text
Test ends at 10:00
Embargo 48 bars 15m = 12h
No train sample from 10:00 to 22:00
```

---

## 10. Regime Split Evaluation

Evaluate by market regime:

```python
regime_bull_trend
regime_bear_trend
regime_sideway
regime_high_vol
regime_low_vol
regime_risk_on
regime_risk_off
regime_transitioning
```

Metrics per regime:

```python
n_trades
win_rate
avg_return
profit_factor
sharpe
sortino
max_drawdown
avg_hold_time
expectancy
```

Output:

```text
Which regime creates alpha?
Which regime destroys alpha?
Should the bot trade less in some regimes?
```

---

## 11. Stress Test Engine

### 11.1. Historical Stress Windows

Recommended stress windows:

```python
stress_windows = [
    {"name": "LUNA_Collapse", "start": "2022-05-01", "end": "2022-05-20"},
    {"name": "FTX_Collapse", "start": "2022-11-01", "end": "2022-11-20"},
    {"name": "COVID_Crash", "start": "2020-03-01", "end": "2020-03-20"},
    {"name": "ETF_Approval", "start": "2024-01-01", "end": "2024-01-20"},
    {"name": "High_Rate_Regime", "start": "2022-06-01", "end": "2023-12-31"},
]
```

Adjust dates based on available data.

---

### 11.2. Synthetic Stress Tests

```python
synthetic_shocks = [
    {"name": "spread_x2", "spread_mult": 2.0},
    {"name": "spread_x5", "spread_mult": 5.0},
    {"name": "slippage_x2", "slippage_mult": 2.0},
    {"name": "latency_1s", "latency_ms": 1000},
    {"name": "latency_3s", "latency_ms": 3000},
    {"name": "volume_down_50pct", "volume_mult": 0.5},
    {"name": "gap_down_5pct", "gap_pct": -5.0},
    {"name": "flash_crash_10pct", "shock_pct": -10.0},
]
```

---

## 12. Monte Carlo Robustness Test

### 12.1. Purpose

Kiểm tra kết quả có phụ thuộc vào vài trade may mắn không.

### 12.2. Simulations

```python
monte_carlo_config = {
    "n_simulations": 10000,
    "shuffle_trades": True,
    "bootstrap_trades": True,
    "randomize_slippage": True,
    "randomize_latency": True,
    "randomize_spread": True,
}
```

### 12.3. Output

```python
p05_return
p50_return
p95_return
probability_of_loss
probability_max_dd_gt_10pct
expected_max_drawdown
risk_of_ruin
```

Approval rule:

```text
Reject strategy if probability_of_loss > 25%
Reject strategy if probability_max_dd_gt_10pct > 20%
```

---

## 13. Performance Metrics

### 13.1. Core Metrics

```python
total_return
annualized_return
volatility
sharpe
sortino
calmar
max_drawdown
profit_factor
expectancy
win_rate
avg_win
avg_loss
payoff_ratio
exposure_time
turnover
```

### 13.2. Trading Metrics

```python
n_trades
trades_per_day
avg_hold_time
median_hold_time
tp1_hit_rate
tp2_hit_rate
sl_hit_rate
timeout_rate
mfe
mae
```

### 13.3. ML Metrics

```python
roc_auc
precision
recall
f1
brier_score
calibration_error
expected_calibration_error
threshold_stability
```

### 13.4. Execution Metrics

```python
avg_fee_bps
avg_spread_bps
avg_slippage_bps
avg_latency_ms
gross_pnl
net_pnl
cost_drag
```

---

## 14. Performance Attribution

Breakdown by:

```python
coin
direction
timeframe
strategy_type
signal_type
regime
causal_risk_level
meta_confidence_bucket
hour_of_day
day_of_week
feature_group
```

Questions:

```text
BTC or altcoins create most PnL?
LONG or SHORT performs better?
Which regime should be blocked?
Which confidence bucket is reliable?
Are causal HIGH risk trades actually worse?
```

---

## 15. Sprint Plan

### Sprint 9.1 — Backtest Engine Foundation

Tasks:

- Create `backtesting/` package.
- Define `BacktestConfig`.
- Define `BacktestResult`.
- Implement basic event-driven loop.
- Implement position tracker.
- Implement order fill abstraction.

Deliverables:

```text
backtesting/engine.py
backtesting/config.py
backtesting/metrics.py
scripts/run_backtest_v2.py
```

Acceptance Criteria:

- Can backtest one coin, one timeframe.
- Can simulate BUY/SELL/NEUTRAL.
- Can track open/closed positions.
- Can export JSON report.

---

### Sprint 9.2 — Cost, Spread, Slippage v1

Tasks:

- Add fee model.
- Add spread model.
- Add simple slippage model.
- Add latency model.
- Add gross vs net PnL.

Deliverables:

```text
cost_model.py
slippage_model_v1.py
latency_model.py
```

Acceptance Criteria:

- Every trade has gross PnL and net PnL.
- Cost drag is visible.
- Backtest can run with multiple cost scenarios.

---

### Sprint 9.3 — Walk-forward Validation

Tasks:

- Implement rolling train/test split.
- Integrate with ML training.
- Store per-window result.
- Add threshold re-optimization option.

Deliverables:

```text
walk_forward.py
scripts/run_walk_forward.py
```

Acceptance Criteria:

- Can run 6m train / 1m test windows.
- Per-window metrics exported.
- Report shows degradation across time.

---

### Sprint 9.4 — Purged KFold + Embargo

Tasks:

- Implement overlap detection.
- Implement purging.
- Implement embargo.
- Compare normal KFold vs Purged KFold.

Deliverables:

```text
purged_kfold.py
embargo.py
```

Acceptance Criteria:

- No overlapping label horizon between train/test.
- Embargo window applied correctly.
- Split report generated.

---

### Sprint 9.5 — Regime Split + Attribution

Tasks:

- Add regime metrics.
- Add coin/direction/signal breakdown.
- Add causal risk breakdown.
- Add confidence bucket analysis.

Deliverables:

```text
regime_split.py
attribution.py
```

Acceptance Criteria:

- Metrics by regime are generated.
- Weak regimes can be identified.
- Dashboard/report can show attribution.

---

### Sprint 9.6 — Stress Test Engine

Tasks:

- Implement historical stress windows.
- Implement synthetic shocks.
- Run strategy under stress assumptions.
- Export stress test report.

Deliverables:

```text
stress_test.py
scripts/run_stress_tests.py
```

Acceptance Criteria:

- Strategy can be tested on FTX/LUNA-like windows.
- Spread/slippage/latency shock can be applied.
- Stress failures are clearly reported.

---

### Sprint 9.7 — Monte Carlo Engine

Tasks:

- Implement trade bootstrap.
- Implement trade shuffle.
- Randomize costs.
- Compute risk of ruin.
- Generate distribution report.

Deliverables:

```text
monte_carlo.py
scripts/run_monte_carlo.py
```

Acceptance Criteria:

- 10,000 simulations supported.
- p05/p50/p95 metrics generated.
- Risk of ruin visible.

---

### Sprint 9.8 — Report Builder + Dashboard

Tasks:

- Generate Markdown/HTML/JSON reports.
- Add dashboard tab for Backtesting.
- Add run history.
- Add comparison between strategies.

Deliverables:

```text
report_builder.py
dashboard Backtesting tab
data/backtests/reports/
```

Acceptance Criteria:

- One-click backtest report.
- Strategy comparison available.
- Report can be reviewed before deployment.

---

## 16. Config File

### `backtest_config.json`

```json
{
  "backtest": {
    "initial_capital": 10000,
    "timeframe": "15m",
    "coins": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    "fee_model": {
      "spot_taker_bps": 10,
      "spot_maker_bps": 10,
      "futures_taker_bps": 5,
      "futures_maker_bps": 2
    },
    "slippage_model": {
      "enabled": true,
      "mode": "rule_v1",
      "base_slippage_bps": 1.0
    },
    "latency_model": {
      "enabled": true,
      "latency_ms": 250
    },
    "walk_forward": {
      "train_months": 6,
      "test_months": 1,
      "step_months": 1
    },
    "monte_carlo": {
      "n_simulations": 10000
    }
  }
}
```

---

## 17. Strategy Approval Gate

A strategy can move from backtest to paper trading only if:

```python
approval_rules = {
    "min_profit_factor": 1.3,
    "min_sharpe": 1.0,
    "max_drawdown": 0.10,
    "min_trades": 100,
    "max_cost_drag_pct_of_gross": 0.35,
    "max_probability_of_loss_mc": 0.25,
    "max_probability_dd_gt_10pct": 0.20,
    "positive_in_at_least_n_regimes": 3,
}
```

---

## 18. Dashboard Additions

Backtesting tab panels:

```text
Backtest run history
Gross vs net PnL
Walk-forward result
Regime performance
Stress test result
Monte Carlo distribution
Strategy approval status
Performance attribution
```

---

## 19. Testing Plan

Unit tests:

```text
tests/test_backtest_engine.py
tests/test_cost_model.py
tests/test_slippage_model.py
tests/test_walk_forward.py
tests/test_purged_kfold.py
tests/test_embargo.py
tests/test_stress_test.py
tests/test_monte_carlo.py
```

Integration tests:

```text
tests/test_phase9_backtest_pipeline.py
```

Critical test cases:

```text
No look-ahead in features
No overlap in purged folds
Embargo applied correctly
Fees reduce PnL correctly
Spread applied correctly for long/short
Slippage increases cost correctly
Latency changes fill price
Stress shock applies correctly
Monte Carlo distribution is reproducible with seed
```

---

## 20. Recommended Implementation Order

```text
1. Backtest Engine v2
2. Cost Model
3. Slippage Model v1
4. Walk-forward Validation
5. Purged KFold + Embargo
6. Regime Split
7. Stress Test
8. Monte Carlo
9. Performance Attribution
10. Report Builder + Dashboard
```

---

## 21. Final Deliverables

```text
btc_scraper/backtesting/
scripts/run_backtest_v2.py
scripts/run_walk_forward.py
scripts/run_stress_tests.py
scripts/run_monte_carlo.py
data/backtests/reports/
backtest_config.json
dashboard Backtesting tab
tests/test_phase9_*.py
```

---

## 22. Definition of Done

Phase 9 is complete when:

- Event-driven backtest works.
- Cost model is active.
- Slippage model v1 is active.
- Latency model is active.
- Walk-forward validation works.
- Purged KFold + embargo works.
- Regime split report works.
- Stress test works.
- Monte Carlo robustness test works.
- Performance attribution works.
- Dashboard/report shows gross vs net PnL.
- Strategy approval criteria are enforced.

---

## 23. Final Recommendation

Phase 9 phải hoàn thành trước Phase 10.

```text
If Phase 9 fails:
    do not optimize execution yet

If Phase 9 passes:
    move to Phase 10 paper execution and slippage modeling
```
