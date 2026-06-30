# Causal Implementation Plan - Thực Hiện Phase 1-4

## Overview

Thực hiện thành công 4 giai đoạn đầu tiên của Causal World Model:
- **Phase 1**: Knowledge Graph (Mối quan hệ nhân quả thủ công)
- **Phase 2**: Data Gathering & Time Alignment  
- **Phase 3**: Context Engine (Điều chỉnh tín hiệu Rule-based)
- **Phase 4**: Causal Reasoning Engine (Giải thích quyết định)

---

## Phase 1: Knowledge Graph ✓

### Files Created
1. **`data/causal_graph.json`** - Đồ thị nhân quả cơ bản
   - 13 edge-based relationships từ macro → crypto
   - Nodes: DXY, FedRate, BondYield, VIX, BTC, ETH, Funding, OI, v.v.
   - Metadata: weight, confidence, lag, condition

2. **`btc_scraper/ml_engine/graph_validator.py`** - Kiểm tra tính hợp lệ ⭐
   - Checks: Cycles, Missing Nodes, Duplicate Edges, Invalid Weights
   - Mandatory call trước khi bot khởi động
   - Sử dụng: `validate_graph_or_fail("data/causal_graph.json")`

3. **`btc_scraper/ml_engine/causal_graph.py`** - Phân tích đồ thị
   - `CausalGraph` class với methods:
     - `find_shortest_path(source, target)`
     - `find_all_paths(source, target, max_depth)`
     - `get_influencers(target)` - Tìm nodes tác động đến target
     - `get_descendants(source)` - Tìm nodes bị tác động bởi source

### Usage Example
```python
from btc_scraper.ml_engine.causal_graph import CausalGraph
from btc_scraper.ml_engine.graph_validator import validate_graph_or_fail

# Validate at startup
validate_graph_or_fail("data/causal_graph.json")

# Analyze relationships
graph = CausalGraph("data/causal_graph.json")

# Find all influencers on BTC
influencers = graph.get_influencers("BTC", max_depth=3)
# Output: [("DXY", 0.85), ("RealYield", 0.80), ("VIX", 0.70), ...]

# Find shortest path from DXY to BTC
path = graph.find_shortest_path("DXY", "BTC")
# Output: CausalPath(path=["DXY", "BTC"], confidence=0.85, effect="negative")
```

---

## Phase 2: Data Gathering & Time Alignment

### Integration Points
Data aggregation đã tồn tại trong system:
- **Binance Futures**: Funding Rate, OI, Long/Short Ratio  
- **Macro Providers**: DXY, VIX, Yields (yfinance, FRED)
- **Economic Calendar**: Các sự kiện macro

### Recommended Time Alignment Implementation
Thêm vào data pipeline (trong `btc_scraper/core/data_loader.py` hoặc tương tự):

```python
def time_align_features(macro_df, crypto_df, on_chain_df):
    """
    Forward Fill để chống look-ahead bias:
    - Macro: 1 ngày → resample 4h/1h
    - Funding: 8 giờ → resample 4h/1h
    - OI: 5 phút → giữ nguyên
    - BTC: 1 phút → giữ nguyên
    """
    # Forward Fill only (không backward fill)
    aligned_df = macro_df.reindex(
        crypto_df.index, method='ffill'
    )
    return aligned_df
```

---

## Phase 3: Context Engine ✓

### Files Created
1. **`data/context_rules.json`** - Config-driven rules
   - 20+ rules cross 4 layers: macro, market, sentiment, risk
   - Mỗi rule: priority, condition, impact, stop_processing
   - Expressions: `"FedRate.Change > 0 AND RealYield > 1.5"`

2. **`btc_scraper/ml_engine/context_engine.py`** - Multi-layered processor
   - `ContextEngine` class
   - `ContextReport` dataclass với breakdown & adjustments

### Usage Example
```python
from btc_scraper.ml_engine.context_engine import ContextEngine

# Initialize
engine = ContextEngine("data/context_rules.json")

# Context data (ví dụ)
context_data = {
    "MacroEvent": {
        "FOMC": {"HoursToEvent": 2, "Importance": "HIGH"}
    },
    "Funding_Z": 1.5,
    "OI_Delta": 10,
    "FearGreed": 30,
    "DXY": 104.5,
}

# Generate report
original_score = 0.75
report = engine.generate_context_report(original_score, context_data)

print(report.adjusted_score)  # 0.40 (sau khi điều chỉnh)
print(report.breakdown)  # {"macro": -0.25, "market": -0.10, ...}
print(report.risk_level)  # "HIGH"

for adj in report.adjustments:
    print(f"  {adj.layer}: {adj.impact:+.3f} - {adj.reason}")
```

### Integration với Decision Engine
```python
from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine

decision_engine = MetaDecisionEngine()

# Phương pháp cũ (Meta model only)
base_decision = decision_engine.decide(analysis_info)

# Phương pháp mới (Meta + Context)
context_report = engine.generate_context_report(
    original_score=base_decision["posterior_probability"],
    context_data=market_context
)
enhanced_decision = decision_engine.decide_with_context(
    analysis_info,
    context_report.to_dict()
)

print(enhanced_decision["action"])  # Có thể thay đổi từ "BUY" → "HOLD"
print(enhanced_decision["context_risk_level"])  # "HIGH"
```

---

## Phase 4: Causal Reasoning Engine ✓

### Files Created
1. **`btc_scraper/ml_engine/causal_reasoning.py`** - Explainable reasoning
   - `CausalReasoningEngine` class
   - `CausalReasoning` dataclass với paths & explanations

2. **`btc_scraper/ml_engine/scenario_interface.py`** - Foundation for Phase 5
   - Abstract classes: `Scenario`, `DigitalTwin`, `CounterfactualAnalyzer`
   - `ScenarioLibrary` với 6 predefined scenarios
   - `ScenarioSimulator` cho đơn giản hóa

### Usage Example
```python
from btc_scraper.ml_engine.causal_reasoning import CausalReasoningEngine

engine = CausalReasoningEngine("data/causal_graph.json")

# Find root causes tác động BTC
root_causes = engine.find_root_causes("BTC", max_depth=4)
# Output: [("DXY", 0.85), ("RealYield", 0.80), ("VIX", 0.70), ...]

# Generate full reasoning tree
reasoning = engine.generate_reasoning_tree(
    target="BTC",
    signal_direction="BUY"
)

print(reasoning.explanation)
# "BUY signal on BTC driven by: DXY, RealYield. Primary causal path: 
#  FedRate → BondYield → DXY → BTC. Current conditions pressure the 
#  case for BUY. Confidence: 82%."

# Explain a trading decision
decision_with_explanation = engine.explain_decision(
    decision_dict=enhanced_decision,
    target="BTC",
    context_report=context_report.to_dict()
)
```

### Scenario Simulation (Preview for Phase 5)
```python
from btc_scraper.ml_engine.scenario_interface import ScenarioSimulator

simulator = ScenarioSimulator(graph)

# Simulate "Fed Pivot" scenario
outcome = simulator.simulate_scenario(
    scenario_name="FedPivot",
    current_state={"RealYield": 1.5, "BTC": 50000},
    horizon_hours=24
)

print(outcome.target_impact)  # 0.30 (expected positive impact)
print(outcome.affected_nodes)  # ["FedRate", "RealYield", "BondYield", "DXY"]
```

---

## Updated Telegram Alerts ✓

### New Functions Added

1. **`send_causal_analysis_alert(decision_with_reasoning)`**
   - Hiển thị causal pathway từ root causes → BTC
   - Root causes ranking theo confidence
   - Primary pathway visualization

2. **`send_context_adjustment_alert(context_report, original_decision)`**
   - So sánh original score vs adjusted score
   - Layer-by-layer breakdown
   - Risk level warning

3. **`send_shadow_mode_report(...)`**
   - Tracking cho Shadow Mode verification
   - Compare Original vs Context-Adjusted decision
   - Monitor PnL difference

### Telegram Integration Example
```python
from btc_scraper.telegram_bot.alerts import (
    send_signals_alert,
    send_causal_analysis_alert,
    send_context_adjustment_alert
)

# Original signal alert
signal_msg_id = send_signals_alert(analysis_results)

# Add causal explanation
if decision_with_reasoning:
    causal_msg_id = send_causal_analysis_alert(decision_with_reasoning)

# Add context adjustment warning if needed
if context_report.get("risk_level") in ["HIGH", "CRITICAL"]:
    context_msg_id = send_context_adjustment_alert(
        context_report, 
        original_decision
    )
```

---

## Critical Next Steps - IMPLEMENTATION ✓

### 1. Bot Startup Integration ✓

**File**: `btc_scraper/ml_engine/causal_startup.py`

Validates and initializes all causal components at bot startup. Fails loudly if validation fails.

**Integration**:
```python
from btc_scraper.ml_engine.causal_startup import initialize_causal_system_at_startup

try:
    causal_system = initialize_causal_system_at_startup()
    # Bot proceeds normally
except Exception as e:
    logger.critical(f"Cannot start: {str(e)}")
    sys.exit(1)
```

**Test**:
```bash
python3 btc_scraper/ml_engine/causal_startup.py
# ✓ CAUSAL SYSTEM INITIALIZATION SUCCESSFUL
```

---

### 2. Time Alignment Module ✓

**File**: `btc_scraper/ml_engine/time_alignment.py`

Forward fills multi-frequency data to prevent look-ahead bias (forward fill only, never backward).

**Usage**:
```python
from btc_scraper.ml_engine.time_alignment import TimeAlignmentManager

manager = TimeAlignmentManager()
aligned_df = manager.align_dataframes(
    crypto_df=btc_data,
    macro_df=dxy_daily_data,
    funding_df=funding_8h_data,
)
manager.validate_no_lookahead_bias(aligned_df)
```

---

### 3. Shadow Mode Tracking ✓

**File**: `btc_scraper/ml_engine/shadow_mode_tracker.py`

Logs Original and Context-Adjusted decisions in parallel for 2-4 weeks without affecting trades.

**Usage**:
```python
from btc_scraper.ml_engine.shadow_mode_tracker import ShadowModeTracker

tracker = ShadowModeTracker(enable_shadow_mode=True)

# Log each decision
tracker.log_decision(
    symbol="BTC/USDT",
    original_decision=base_decision,
    adjusted_decision=enhanced_decision,
)

# When trade closes
tracker.update_trade_exit(symbol="BTC/USDT", exit_price=52000)

# Generate report
report = tracker.generate_report()
tracker.save_report()
```

**Success Criteria**:
- Win rate improvement > 5%
- Profit Factor improvement > 0.1
- Max Drawdown reduction > 5%

---

### 4. A/B Backtest Comparison ✓

**File**: `btc_scraper/ml_engine/ab_backtest.py`

Compares Baseline (Meta only) vs Treatment (Context-adjusted) on historical data.

**Usage**:
```python
from btc_scraper.ml_engine.ab_backtest import ABBacktestComparator

comparator = ABBacktestComparator(context_engine, decision_engine)
comparison = comparator.run_ab_backtest(signals_df, context_df)

# Output: recommendation in ["ENABLE_CONTEXT_ADJUSTMENTS_LIVE", "ENABLE_CAUTIOUSLY", "CONTINUE_TESTING", "DO_NOT_ENABLE"]
```

**Automated Recommendation**:
- **Score >= 5**: `ENABLE_CONTEXT_ADJUSTMENTS_LIVE` ✓
- **Score 3-4**: `ENABLE_CAUTIOUSLY` ◐
- **Score < 1**: `DO_NOT_ENABLE` ✗

---

## Implementation Verification

### 1. Shadow Mode ⭐

```python
# Enable Shadow Mode in config
ENABLE_SHADOW_MODE = True

# During execution:
# - Log Original decision (Meta only)
# - Log Context-Adjusted decision
# - Do NOT execute context-adjusted trades yet
# - Track PnL for 2-4 weeks

# Compare metrics:
# - Number of signals
# - Profit Factor
# - Max Drawdown
# - Win rate
```

### 2. A/B Historical Backtest
```python
from btc_scraper.ml_engine.context_engine import ContextEngine
from btc_scraper.ml_engine.causal_reasoning import CausalReasoningEngine

# Backtest with context on historical data
engine = ContextEngine("data/context_rules.json")

for signal in historical_signals:
    # Original score
    original_score = signal.posterior
    
    # Adjusted score
    context_report = engine.generate_context_report(
        original_score, 
        signal.context_data
    )
    adjusted_score = context_report.adjusted_score
    
    # Track both PnL
    track_pnl(original_score, adjusted_score, signal)

# Compare results
compare_metrics(baseline_pnl, context_adjusted_pnl)
```

### 3. Automated Tests
```bash
# Run validation
python btc_scraper/ml_engine/graph_validator.py data/causal_graph.json

# Test causal_graph
python btc_scraper/ml_engine/causal_graph.py data/causal_graph.json

# Test context_engine
python btc_scraper/ml_engine/context_engine.py
```

---

## Files Summary

| File | Purpose | Status |
|------|---------|--------|
| `data/causal_graph.json` | Knowledge graph edges | ✓ Created |
| `data/context_rules.json` | Context rules config | ✓ Created |
| `btc_scraper/ml_engine/graph_validator.py` | Graph validation | ✓ Implemented |
| `btc_scraper/ml_engine/causal_graph.py` | Graph analysis | ✓ Implemented |
| `btc_scraper/ml_engine/context_engine.py` | Context adjustment | ✓ Implemented |
| `btc_scraper/ml_engine/decision_engine.py` | Enhanced with context | ✓ Updated |
| `btc_scraper/ml_engine/causal_reasoning.py` | Reasoning engine | ✓ Implemented |
| `btc_scraper/ml_engine/scenario_interface.py` | Scenario foundation | ✓ Implemented |
| `btc_scraper/telegram_bot/alerts.py` | Alert functions | ✓ Updated |
| **`btc_scraper/ml_engine/causal_startup.py`** | **Bot startup integration** | **✓ NEW** |
| **`btc_scraper/ml_engine/time_alignment.py`** | **Time alignment (forward fill)** | **✓ NEW** |
| **`btc_scraper/ml_engine/shadow_mode_tracker.py`** | **Shadow mode tracking** | **✓ NEW** |
| **`btc_scraper/ml_engine/ab_backtest.py`** | **A/B backtest comparison** | **✓ NEW** |

---

## Next Steps (Phase 5)

Các giai đoạn tiếp theo sẽ xây dựng trên nền tảng này:

1. **Phase 5**: Causal Discovery Algorithm (Tự động phát hiện quan hệ)
2. **Phase 6**: Scenario Simulator & Counterfactual Analysis
3. **Phase 7**: Digital Twin / World Model
4. **Phase 8**: Transfer Learning & Model Adaptation
5. **Phase 9**: Multi-Agent Collaboration
6. **Phase 10**: Production Deployment & Monitoring

---

## Quick Start Checklist

### Before Bot Deployment ✓
- [ ] **Step 1: Bot Startup** - Import `initialize_causal_system_at_startup()` from `causal_startup.py`
- [ ] **Step 2: Time Alignment** - Use `TimeAlignmentManager.align_dataframes()` from `time_alignment.py`
- [ ] **Step 3: Shadow Mode** - Create `ShadowModeTracker(enable_shadow_mode=True)` instance
- [ ] **Step 4: A/B Backtest** - Run `ABBacktestComparator.run_ab_backtest()` on historical data

### Validation Tests
```bash
# Test startup system
python3 btc_scraper/ml_engine/causal_startup.py
# ✓ CAUSAL SYSTEM INITIALIZATION SUCCESSFUL

# Test time alignment
python3 btc_scraper/ml_engine/time_alignment.py

# Test shadow mode
python3 btc_scraper/ml_engine/shadow_mode_tracker.py

# Test A/B backtest
python3 btc_scraper/ml_engine/ab_backtest.py

# Legacy validation tests
python3 btc_scraper/ml_engine/graph_validator.py data/causal_graph.json
python3 btc_scraper/ml_engine/context_engine.py
python3 btc_scraper/ml_engine/causal_reasoning.py
```

---

## Critical Implementation Notes ⭐

1. **Startup Validation REQUIRED** - Graph validator must pass or bot refuses to start
2. **Time Alignment is Critical** - Use forward fill only (never backward fill) to prevent look-ahead bias
3. **Shadow Mode Duration** - Run for 2-4 weeks before enabling context adjustments in production
4. **A/B Backtest Required** - Test on historical data before making decision to enable
5. **Recommendation Scoring** - Score >= 5 enables, 3-4 requires caution, < 1 means don't enable

---

**Implementation Date**: 2026-06-30  
**Version**: 1.0.0  
**Status**: Phase 1-4 Complete ✓ | Critical Next Steps Complete ✓
