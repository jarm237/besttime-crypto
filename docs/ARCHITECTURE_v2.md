# Causal World Model - Architecture v2.0

## Lịch Sử Phiên Bản

| Phiên Bản | Ngày | Mô Tả | Trạng Thái |
|-----------|------|-------|-----------|
| 1.0 | 2026-06-30 | Phase 1-4: Knowledge Graph, Context Engine, Causal Reasoning, Shadow Mode | ✓ Hoàn thành |
| **2.0** | **2026-06-30** | **5 Thành Phần Nền Tảng: World State, Event Bus, ContextProvider, Snapshot, Monitoring** | **✓ Hoàn thành** |
| **2.1** | **2026-07-01** | **Phase 2.1-D: RuleContextProvider, BayesianContextProvider, HybridContextProvider, CausalContextBridge, CounterfactualEngine — tích hợp production** | **✓ Hoàn thành** |
| **3.0** | **2026-07-07** | **Phase 7: Alternative Data Layer — 12+ features, ParsebotFarsideETFCollector, MongoDB ETF storage, confidence-weighted WorldState, ETF monitoring & alerts** | **✓ Hoàn thành** |

> **Trạng thái hiện tại (07/07/2026)**: Test suite **246/246 PASSED** — Toàn bộ Phase 2.1 → Phase D và Phase 7 Alternative Data đã được tích hợp production.

---

## Executive Summary

Phiên bản 2.0 thiết kế lại toàn bộ hệ thống từ **modular monolith** thành **event-driven architecture**:

**Trước (v1.0)**:
```
Collectors → Feature Store
                ↓
        Each module reads
        independently
```

**Sau (v2.0)**:
```
Collectors → Event Bus → World State Manager ← Snapshot & Replay
                              ↓
                    ContextProvider (Interface)
                    ├─ RuleContextProvider (v2.0)
                    ├─ BayesianContextProvider (v3.0)
                    ├─ RLContextProvider (v4.0)
                    └─ LLMContextProvider (v5.0)
                              ↓
                        Decision Engine
                              ↓
                    Monitoring & Metrics
```

---

## Architecture Layers

### 1. Centralized State Layer

**File**: `btc_scraper/core/world_state.py`

Thay vì mỗi module độc lập đọc từ Feature Store, toàn bộ hệ thống sử dụng **unified state object**:

```python
class WorldState:
    timestamp: datetime
    regime: MarketRegime  # RISK_ON, RISK_OFF, TRANSITIONING
    macro: MacroLayer
      ├─ DXY, FedRate, BondYield, VIX, RealYield
    liquidity: LiquidityLayer
      ├─ Funding, OI, LongShortRatio
    crypto: CryptoLayer
      ├─ BTC_Price, ETH_Price, volumes
    sentiment: SentimentLayer
      ├─ FearGreed, SocialVolume, LongTermHolders
    risk: RiskLayer
      ├─ CurrentDrawdown, Volatility, VaR, Sharpe
```

**Lợi ích**:
- ✓ Single source of truth (không bao giờ không đồng bộ)
- ✓ Thread-safe access (RLock protection)
- ✓ Immutable per decision cycle (reproducibility)
- ✓ Easy snapshot (for replay/backtest)

**Usage**:
```python
from btc_scraper.core.world_state import get_world_state_manager

manager = get_world_state_manager()
state = manager.get_state()  # Read-only
print(state.macro.DXY)
print(state.crypto.BTC_Price)
```

---

### 2. Event Bus Layer

**File**: `btc_scraper/core/event_bus.py`

Khi macro event xảy ra (e.g., CPI announcement), nó phát tán tới toàn bộ subscribers:

```python
class Event:
    type: EventType  # MACRO_EVENT, FED_PIVOT, FUNDING_SPIKE, etc
    timestamp: datetime
    source: str  # "collector", "context_engine", etc
    data: Dict[str, Any]
    priority: int  # 0 (low) to 10 (critical)
    event_id: str
    causally_related_to: List[str]  # Chain events together
```

**Event Types**:
- Macro: `MACRO_EVENT`, `FED_PIVOT`, `ECONOMIC_SHOCK`
- Market: `FUNDING_SPIKE`, `OI_SPIKE`, `LIQUIDITY_CRISIS`, `REGIME_CHANGE`
- Sentiment: `SENTIMENT_SHIFT`, `SOCIAL_VOLUME_SPIKE`, `WHALE_ACTIVITY`
- Internal: `DECISION_MADE`, `TRADE_EXECUTED`, `ALERT_SENT`
- System: `GRAPH_UPDATED`, `RULES_RELOADED`, `SNAPSHOT_CREATED`

**Pub/Sub Model**:
```python
from btc_scraper.core.event_bus import get_event_bus, EventType, Event

bus = get_event_bus()

# Subscribe
def on_macro_event(event: Event):
    print(f"Received {event.type.value}: {event.data}")

bus.subscribe(
    "context_engine",
    on_macro_event,
    event_types=[EventType.MACRO_EVENT, EventType.FED_PIVOT],
    min_priority=7
)

# Publish
event = Event(
    type=EventType.MACRO_EVENT,
    timestamp=datetime.now(),
    source="collector",
    data={"indicator": "CPI", "value": 3.5},
    priority=8,
)
bus.publish(event)
```

**Lợi ích**:
- ✓ Loose coupling (modules don't need to know about each other)
- ✓ Ready for Kafka/Redis Streams migration
- ✓ Event history & replay capability
- ✓ Causal chain tracking (events linked together)

---

### 3. Context Provider Interface

**File**: `btc_scraper/ml_engine/context_provider.py`

Cho phép thay thế context adjustment strategy mà Decision Engine không cần sửa:

```python
class ContextProvider(ABC):
    """Abstract interface."""
    
    @abstractmethod
    def generate_context_report(self, original_score: float,
                               world_state: WorldState) -> ContextReport:
        """Generate adjusted score based on context."""
        pass
    
    @abstractmethod
    def should_apply_context(self, world_state: WorldState) -> bool:
        """Conditionally apply context (e.g., don't adjust during circuit breaker)."""
        pass
    
    @abstractmethod
    def validate(self) -> tuple[bool, str]:
        """Validate configuration."""
        pass
```

**Implementations**:

| Phiên Bản | Provider | Approach | Status |
|-----------|----------|----------|--------|
| v2.0 | `RuleContextProvider` | Rule-based | ✓ Ready (Production) |
| v3.0 | `BayesianContextProvider` | Probabilistic Gaussian | ✓ Implemented (alpha=0.0 → safe mode) |
| v3.1 | `HybridContextProvider` | Alpha-blended Rule+Bayesian | ✓ Production (CAUSAL_ALPHA env var) |
| v4.0 | `RLContextProvider` | Reinforcement Learning | 🔮 Planned |
| v5.0 | `LLMContextProvider` | Large Language Model | 🔮 Planned |

**Composite Pattern** (mix strategies):
```python
from btc_scraper.ml_engine.context_provider import CompositeContextProvider

provider = CompositeContextProvider(
    "hybrid",
    providers=[
        RuleContextProvider(),  # Fast, interpretable
        BayesianContextProvider(),  # Probabilistic
    ],
    stop_on_critical=True,  # Don't cascade if risk CRITICAL
)

report = provider.generate_context_report(0.75, world_state)
```

**Lợi ích**:
- ✓ Decision Engine doesn't know which provider is used
- ✓ Easy A/B test different strategies
- ✓ Gradual migration (v2→v3→v4 without code change)
- ✓ Composite for hybrid approaches

---

### 4. Snapshot & Replay Layer

**File**: `btc_scraper/core/feature_snapshot.py`

Lưu trữ toàn bộ state snapshot để replay/backtest/counterfactual:

```python
@dataclass
class FeatureSnapshot:
    snapshot_id: str
    timestamp: datetime
    world_state: Dict[str, Any]  # Serialized WorldState
    context_report: Optional[Dict[str, Any]]
    events: List[Dict[str, Any]]  # Events that triggered this
    reasoning_data: Optional[Dict[str, Any]]
    decision: Optional[Dict[str, Any]]
    metadata: Dict[str, Any]
    
    def hash(self) -> str:
        """SHA256 hash for integrity check."""
        pass
```

**Use Cases**:

1. **Replay**: "Why did we make that decision?"
   ```python
   snapshot = manager.load_snapshot("snap_1719768000_42")
   result = replayer.replay_decision(snapshot)
   # Compare original vs replayed decision
   ```

2. **Backtest**: "What if we ran context adjustments?"
   ```python
   comparison = run_ab_backtest(
       original_decisions=[...],
       using_snapshot_states=[...]
   )
   ```

3. **Counterfactual**: "What if DXY was 102 instead of 104.5?"
   ```python
   result = replayer.counterfactual_analysis(
       snapshot,
       modifications={"macro.DXY": 102.0}
   )
   ```

4. **Debugging**: Quick replay of issue
   ```python
   snapshot.to_json()  # Save for post-mortem
   snapshot = FeatureSnapshot.from_json(saved_json)  # Load later
   ```

**Storage**:
- **Memory**: Last 1000 snapshots (quick access)
- **Disk**: Persistent storage (backtest/replay)

---

### 5. Causal Monitoring Layer

**File**: `btc_scraper/ml_engine/causal_monitoring.py`

Theo dõi health & performance của toàn bộ system:

```python
monitor = get_causal_monitor()

# Record metrics
monitor.record_graph_loaded(num_nodes=11, num_edges=13)
monitor.record_context_report_generated(0.75, 0.40, 3, "HIGH", 45.2)
monitor.record_reasoning_generated(0.85, 3, 52.1)
monitor.record_decision_made("HOLD", 0.40, 12.3)
monitor.record_event_published("MACRO_EVENT", 8)

# Get dashboard
dashboard = monitor.get_dashboard_data()
```

**Metrics Tracked**:

| Category | Metrics | Purpose |
|----------|---------|---------|
| **Graph** | # nodes, # edges, active edges %, validation errors | Health of causal model |
| **Context** | avg adjustment, # rules fired, latency | Context engine performance |
| **Reasoning** | avg confidence, path length, latency | Reasoning quality |
| **Decision** | action distribution, posterior, latency | Decision quality |
| **Event Bus** | event volume by type, subscriber count | Bus health |
| **Snapshot** | snapshot size, creation frequency | Storage efficiency |
| **Shadow Mode** | decision counts by strategy | A/B test progress |

**Output Format** (JSON):
```json
{
  "timestamp": "2026-06-30T10:30:45.123Z",
  "uptime_seconds": 3600,
  "metrics": {
    "graph": {
      "validation_errors": {},
      "active_edges_pct": {"value": 100.0},
      "num_nodes": {"value": 11.0}
    },
    "context": {
      "avg_adjustment": {"count": 42, "min": 0.05, "max": 0.35, "avg": 0.15},
      "avg_latency_ms": {"count": 42, "min": 30.0, "max": 120.0, "avg": 52.3}
    }
  },
  "counters": {
    "context.reports_by_risk.HIGH": 12,
    "decision.action.BUY": 15,
    "decision.action.HOLD": 25,
    "event.MACRO_EVENT": 8
  }
}
```

---

## Data Flow: Complete Cycle

### Step 1: Data Collection
```
Market Data (1m/5m/1h/1d)
         ↓
Collectors (btc_scraper/core/data_loader.py)
         ↓
Event Bus: MACRO_EVENT, FUNDING_SPIKE published
```

### Step 2: State Update
```
Event Bus (subscribers)
         ↓
World State Manager
         ↓
Update all layers:
- Macro (DXY, FedRate, etc)
- Liquidity (Funding, OI)
- Crypto (BTC, ETH prices)
- Sentiment (FearGreed)
- Risk (Drawdown, Volatility)
```

### Step 3: Snapshot Creation
```
World State
         ↓
Snapshot Manager
         ↓
Create FeatureSnapshot
- Save to memory (quick access)
- Save to disk (long-term)
- Publish SNAPSHOT_CREATED event
```

### Step 4: Context Adjustment
```
FeatureSnapshot
         ↓
ContextProvider.generate_context_report()
         ↓
Original Score (from Meta Model)
   +
Context Report (adjustments + risk level)
         =
Adjusted Score
         ↓
Publish CONTEXT_REPORT_GENERATED event
```

### Step 5: Causal Reasoning
```
Adjusted Score + World State
         ↓
CausalReasoningEngine
         ↓
Root Causes → Primary Path → Confidence
         ↓
CausalReasoning object + Explanation
         ↓
Publish REASONING_GENERATED event
```

### Step 6: Decision Making
```
Original Score
Context Report
Causal Reasoning
         ↓
Decision Engine
         ↓
Action (BUY / HOLD / SELL)
Posterior Probability
Risk Level
         ↓
Publish DECISION_MADE event
```

### Step 7: Shadow Mode Tracking
```
Decision
         ↓
ShadowModeTracker
- Log Original (Meta only)
- Log Adjusted (with context)
         ↓
Track PnL for both
         ↓
After 2-4 weeks:
Generate Comparison Report
```

### Step 8: Monitoring
```
All Events
         ↓
CausalMonitor
         ↓
Record Metrics:
- Graph health
- Context adjustments
- Reasoning quality
- Decision latency
- Event volume
         ↓
Export to JSON/Dashboard
```

---

## Key Architectural Principles

### 1. Immutability Per Cycle
```python
# Each decision cycle creates new objects
original_score = 0.75
context_report = engine.generate_context_report(0.75, state)
# New object with original_score + adjusted_score
decision = decision_engine.decide_with_context(original_score, context_report)
# New object with all fields

# Easy to replay: all data is explicit
snapshot.world_state  # What was the state?
snapshot.decision  # What did we decide?
```

### 2. Confidence Propagation
```
DXY (0.85 confidence)
  ↓ × 0.85
RealYield (should inherit 0.85 × 0.90 = 0.765)
  ↓ × 0.765
BTC impact (0.765 × 0.85 = 0.65)

Not: 0.85 (final weight)
```

**Implementation**:
```python
edge.propagate_confidence = True
# During path finding:
path_confidence = product(edge.confidence for edge in path)
```

### 3. Layer-Based Graph
```
Macro Layer (5 nodes)
     ↓
Liquidity Layer (3 nodes)
     ↓
Crypto Layer (2 nodes)
     ↓
Sentiment Layer (1 node)

Edges only go: Macro → Liquidity → Crypto → Sentiment
(Never circular, always DAG)
```

### 4. Dynamic Edge Activation
```json
{
  "id": "edge_3",
  "from": "DXY",
  "to": "BTC",
  "is_active": true,
  "activation": {
    "regime": "bear"  // Only active in bear market
  }
}
```

In future, Dynamic Graph can toggle edges based on regime.

### 5. Source-Aware Rules
```json
{
  "id": "rule_1",
  "source": "manual",  // Phase 2.0
  // Later:
  // "source": "learned"  // Phase 3.0 (Causal Discovery)
  // "source": "hybrid"   // Phase 4.0 (Combine both)
}
```

Easy to track which rules are handcrafted vs learned vs hybrid.

---

## Integration Guide

### Step 1: Initialize Causal System
```python
# main.py
from btc_scraper.ml_engine.causal_startup import initialize_causal_system_at_startup
from btc_scraper.core.world_state import get_world_state_manager
from btc_scraper.core.event_bus import get_event_bus

causal_system = initialize_causal_system_at_startup()
world_state_manager = get_world_state_manager()
event_bus = get_event_bus()

# Subscribe to events
def on_macro_event(event):
    print(f"Macro event: {event.type.value}")

event_bus.subscribe("my_handler", on_macro_event)
```

### Step 2: Update World State
```python
# In data collection pipeline
from btc_scraper.core.world_state import WorldState, MarketRegime
import datetime

state = WorldState(timestamp=datetime.datetime.now())
state.macro.DXY = 104.5
state.macro.FedRate = 5.25
state.crypto.BTC_Price = 52000.0
state.sentiment.FearGreed = 65

world_state_manager.update_state(state)

# Publish event
event = Event(
    type=EventType.MACRO_EVENT,
    timestamp=datetime.datetime.now(),
    source="collector",
    data={"indicator": "CPI", "value": 3.5},
)
event_bus.publish(event)
```

### Step 3: Create Snapshot
```python
from btc_scraper.core.feature_snapshot import SnapshotManager

manager = SnapshotManager()

state = world_state_manager.get_state()
snapshot = manager.create_snapshot(
    world_state=state,
    decision={"action": "BUY", "posterior": 0.75},
)

manager.save_snapshot(snapshot)
```

### Step 4: Generate Context Report
```python
# Get current state
state = world_state_manager.get_state()

# Generate context adjustment
context_report = context_engine.generate_context_report(
    original_score=0.75,
    world_state=state
)

# Record in monitoring
monitor.record_context_report_generated(
    original_score=0.75,
    adjusted_score=context_report.adjusted_score,
    num_adjustments=len(context_report.adjustments),
    risk_level=context_report.risk_level.value,
    latency_ms=42.5,
)
```

### Step 5: Generate Decision
```python
# Make decision with context
decision = decision_engine.decide_with_context(
    analysis_info,
    context_report.to_dict()
)

# Publish event
event = Event(
    type=EventType.DECISION_MADE,
    timestamp=datetime.datetime.now(),
    source="decision_engine",
    data=decision,
    priority=7,
)
event_bus.publish(event)

# Record in monitoring
monitor.record_decision_made(
    action=decision["action"],
    posterior=decision["posterior"],
    latency_ms=15.3,
)
```

---

## Migration Path: v1.0 → v2.0 → v3.0

### Phase 2.0 (Current): Rule-Based Context
- ✓ World State Manager (centralized state)
- ✓ Event Bus (pub/sub)
- ✓ ContextProvider Interface (abstraction)
- ✓ Snapshot & Replay (debugging, backtest)
- ✓ Monitoring (system health)
- ✓ RuleContextProvider (Phase 1-4 adapted)

### Phase 3.0: Bayesian Context
```python
class BayesianContextProvider(ContextProvider):
    """
    Probabilistic approach using:
    - Prior: Historical correlation strength
    - Likelihood: Current evidence (rules)
    - Posterior: Updated adjustment probability
    """
    def generate_context_report(self, score, state):
        # Compute posteriors for each context factor
        # Update beliefs based on evidence
        # Return adjusted score
        pass
```

### Phase 4.0: Reinforcement Learning
```python
class RLContextProvider(ContextProvider):
    """
    Learn context adjustments from:
    - State-action-reward tuples
    - Shadow mode data
    - Historical decisions
    """
    def generate_context_report(self, score, state):
        # Query trained policy
        # Return best adjustment for state
        pass
```

### Phase 5.0: LLM-based Reasoning
```python
class LLMContextProvider(ContextProvider):
    """
    Use language model for:
    - Understanding complex relationships
    - Real-time macro analysis
    - Natural language explanations
    """
    def generate_context_report(self, score, state):
        # Send state to LLM
        # Parse reasoning
        # Return adjustment
        pass
```

**All phases use same ContextProvider interface** → Decision Engine never changes!

---

## Monitoring Dashboard (Sample)

```json
{
  "timestamp": "2026-06-30T10:45:30Z",
  "uptime_hours": 1.25,
  "system_status": "HEALTHY",
  "metrics": {
    "graph": {
      "nodes": 11,
      "edges": 13,
      "active_edges_pct": 100.0,
      "validation_errors": 0
    },
    "context": {
      "reports_generated": 42,
      "avg_adjustment_magnitude": 0.15,
      "avg_latency_ms": 52.3,
      "risk_level_distribution": {
        "LOW": 8,
        "MEDIUM": 20,
        "HIGH": 12,
        "CRITICAL": 2
      }
    },
    "reasoning": {
      "avg_confidence": 0.82,
      "avg_path_length": 2.8,
      "avg_latency_ms": 48.1
    },
    "decision": {
      "total_decisions": 42,
      "action_distribution": {
        "BUY": 14,
        "HOLD": 20,
        "SELL": 8
      },
      "avg_posterior": 0.68,
      "avg_latency_ms": 15.2
    },
    "event_bus": {
      "total_events": 156,
      "subscribers": 8,
      "event_types": {
        "MACRO_EVENT": 12,
        "MACRO_EVENT": 8,
        "CONTEXT_REPORT": 42,
        "DECISION_MADE": 42
      }
    },
    "snapshot": {
      "total_snapshots": 42,
      "memory_snapshots": 42,
      "disk_snapshots": 0,
      "avg_size_kb": 48.5
    },
    "shadow_mode": {
      "total_decisions_tracked": 42,
      "original_strategy_winrate": 0.625,
      "adjusted_strategy_winrate": 0.688,
      "improvement": "+6.3%"
    }
  }
}
```

---

## Files Summary

### New Core Modules (v2.0)
| File | Lines | Purpose |
|------|-------|---------|
| `btc_scraper/core/world_state.py` | 380 | Centralized market state |
| `btc_scraper/core/event_bus.py` | 340 | Event pub/sub system |
| `btc_scraper/ml_engine/context_provider.py` | 350 | Abstract context interface |
| `btc_scraper/core/feature_snapshot.py` | 420 | Snapshot & replay |
| `btc_scraper/ml_engine/causal_monitoring.py` | 400 | Metrics & monitoring |

### Updated Config Files (v2.0)
| File | Changes | Purpose |
|------|---------|---------|
| `data/causal_graph.json` | v1.0 → v2.0 | Added: layer, is_active, source, propagate_confidence |
| `data/context_rules.json` | v1.0 → v2.0 | Added: source field, metadata |

### New Modules (Phase A-D — Production Integration)
| File | Purpose | Status |
|------|---------|--------|
| `btc_scraper/ml_engine/causal_context_bridge.py` | Singleton bridge: WorldState builder + HybridContextProvider init | ✅ Production |
| `btc_scraper/ml_engine/bayesian_context_provider.py` | Gaussian log-likelihood Bayesian inference | ✅ Production |
| `btc_scraper/ml_engine/hybrid_context_provider.py` | Alpha-blended Rule + Bayesian (CAUSAL_ALPHA env var) | ✅ Production |
| `btc_scraper/ml_engine/causal_simulator.py` | Do-calculus intervention simulator | ✅ Production |
| `btc_scraper/ml_engine/counterfactual_engine.py` | What-if trade analysis, logs/counterfactual_log.json | ✅ Production |
| `btc_scraper/ml_engine/world_model_predictor.py` | Digital Twin: predict next WorldState | ✅ Production |
| `btc_scraper/ml_engine/causal_anomaly_detector.py` | Structural break & anomaly detection | ✅ Production |
| `btc_scraper/ml_engine/agents/macro_agent.py` | Phase 6.0: DXY/Yields/FedRate watcher | ✅ Production |
| `btc_scraper/ml_engine/agents/liquidity_agent.py` | Phase 6.0: Funding/OI/Orderbook watcher | ✅ Production |
| `btc_scraper/ml_engine/agents/sentiment_agent.py` | Phase 6.0: Fear&Greed/social watcher | ✅ Production |
| `btc_scraper/ml_engine/agents/consensus_engine.py` | Phase 6.0: Causal Voting + Bayesian Fusion | ✅ Production |
| `btc_scraper/analysis/signal_tracker.py` | Persistent signal tracking (TTL 90m, data/tracked_signals.json) | ✅ Production |
| `btc_scraper/collectors/macro_collector.py` | DXY, VIX, RealYield, BondYield fetcher | ✅ Production |

### New Test Files (Phase A-D)
| File | Tests | Coverage |
|------|-------|---------|
| `tests/test_causal_context_bridge.py` | 10 | CausalContextBridge, WorldState builder, singleton |
| `tests/test_causal_runtime_integration.py` | 3 | End-to-end runtime integration |
| `tests/test_phase40_simulation.py` | 3 | CausalSimulator, CounterfactualEngine |
| `tests/test_phase50_world_model.py` | 2 | WorldModelPredictor, AnomalyDetector |
| `tests/test_phase60_multiagent.py` | 2 | ConsensusEngine, Sub-Agents |

**Tổng cộng: 196/196 tests PASSED (02/07/2026)**

---

## Known Issues & Technical Debt

### ⚠️ High Priority

| Issue | Mô tả | File | Giải pháp đề xuất |
|-------|-------|------|------------------|
| **Circular Import** | `MarketAnalystAgent.run()` import `_summarize_htf_trend` từ `main.py` | `ml_engine/multi_agent.py` | Tách sang `analysis/htf_utils.py` |
| **Graceful Shutdown** | `ai_worker` và `start_telegram_listener` bị kill đột ngột | `main.py` | `shutdown_event = asyncio.Event()`, sentinel `None` vào `ai_queue` |
| **File I/O non-atomic** | `json.dump()` trực tiếp → file corrupt khi crash | nhiều nơi | `write_atomic(tmp_path, target_path)` pattern |

### ⚠️ Medium Priority

| Issue | Mô tả | Giải pháp |
|-------|-------|----------|
| **CAUSAL_ALPHA = 0.0** | Bayesian provider triển khai nhưng chưa active | Activate `0.1` sau 2-4 tuần shadow mode |
| **MacroCollector staleness** | `load_macro_state()` → DXY/VIX stale nếu không chạy collector thường xuyên | Thêm freshness check + auto-schedule |
| **RL Reward-PnL Paradox** | PPO optimize reward nhân tạo → PnL thực giảm | Simplify reward → net PnL; `MlpLstmPolicy` |
| **No dependency lock** | `requirements.txt` unpinned | `pip freeze > requirements-lock.txt` |
| **Subprocess PID tracking** | `continuous_learning.py` không có PID tracking | Ghi PID + `process.wait()` khi shutdown |

### ℹ️ Low Priority (Warnings)

| Warning | Mô tả |
|---------|-------|
| XGBoost GPU fallback | Không có GPU → tự động CPU, chỉ xuất hiện khi load model |
| LightGBM feature names | Inference không có DataFrame wrapper → UserWarning |
| `test_stage1_pipeline.py` return non-None | Nên dùng `assert` thay vì `return` |

---

## Next Steps

### Đã hoàn thành (Phase 2.1 → Phase D) ✅
- [x] Integrate `RuleContextProvider` with new ContextProvider interface
- [x] Update `decision_engine.py` — `decide_with_provider()` method
- [x] Implement `BayesianContextProvider` (Gaussian log-likelihood)
- [x] Create `CausalDiscoveryEngine` (Granger causality + graph writer)
- [x] Implement `HybridContextProvider` (alpha-blended Rule+Bayesian)
- [x] Scenario Simulator (`CausalSimulator`) + Counterfactual Analysis (`CounterfactualEngine`)
- [x] Digital Twin / World Model (`WorldModelPredictor`)
- [x] Causal Anomaly Detector (`CausalAnomalyDetector`)
- [x] Multi-Agent Collaboration (`MacroAgent`, `LiquidityAgent`, `SentimentAgent`, `ConsensusEngine`)
- [x] Production Integration: `CausalContextBridge` → `SignalGeneratorAgent` → `ExecutionAgent`
- [x] **196/196 integration tests PASSED** (02/07/2026)

### Tiếp theo (Hardening & Activation)
- [ ] Fix circular import: `multi_agent.py` → `main.py` (tách HTF utils sang `analysis/htf_utils.py`)
- [ ] Graceful shutdown: `shutdown_event`, sentinel `ai_queue`, PID tracking subprocesses
- [ ] Atomic file write utility (`write-tmp + os.replace`)
- [ ] Pin dependencies: `pip freeze > requirements-lock.txt`
- [ ] Activate `CAUSAL_ALPHA=0.1` sau 2-4 tuần shadow mode baseline
- [ ] Weekly `CausalDiscoveryEngine.discover()` trên 6 tháng data
- [ ] Implement `RLContextProvider` (v4.0) — learn context adjustments từ shadow mode data
- [ ] Grafana/Prometheus observability dashboard

---

**Architecture Document Version**: 2.1.0
**Last Updated**: 2026-07-02
**Status**: Foundation + Phase 2.1-D Complete ✓ | Production Integrated ✓ | 196/196 Tests PASSED ✓
