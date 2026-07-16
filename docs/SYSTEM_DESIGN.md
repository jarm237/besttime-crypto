# AI Quant Trading System Design Document (TDD)

> **Cập nhật lần cuối**: 14/07/2026 — Architecture v2.1 + current signal detection/scoring assessment

Tài liệu này đóng vai trò là **Technical Design Document (TDD)** tổng thể, mô tả kiến trúc, luồng dữ liệu, feature engineering, Causal AI stack và định hướng phát triển của nền tảng **AI Quant Trading Platform**.

---

## 1. Architecture Diagram

Sơ đồ kiến trúc tổng thể phản ánh kiến trúc v2.1 (Event-Driven + Causal World Model):

```text
Market Data (Binance WebSocket / REST fallback)
             │
             ▼
     CandleStore (thread-safe)
             │
             ▼
   MarketAnalystAgent (MTF: 15m/1h/4h/1d)
             │
             ▼
   Indicator Engine (vectorized Pandas/NumPy)
   (ATR, RSI, EMA9/21, SMA50/200, MACD, BB, Chandelier)
             │
             ▼
   Signal Detection Engine
   RSI reversal, EMA crossover, SFP, Pullback, Break-SMA50,
   Chandelier, ADX/Choppiness, Volume, Fear&Greed
             │
             ▼
   SignalGeneratorAgent
   ├─ signal_score.py: internal 0-100 score + display_score
   ├─ Feature Extractor → Meta Model (RF+LGBM+CatBoost+XGB)
   ├─ Meta confidence + Kelly / volatility / regime sizing
   └─ CausalContextBridge ──────────────────────────────────────┐
             │                                                   │
             ▼                                                   ▼
   CausalGate (CRITICAL→NEUTRAL)           WorldStateManager (5 layers)
             │                              ├─ Macro (DXY, VIX, RealYield)
             ▼                              ├─ Liquidity (Funding, OI)
   RiskManagerAgent                         ├─ Crypto (BTC, ETH prices)
   (Drawdown gate, risk multiplier)         ├─ Sentiment (FearGreed)
             │                              └─ Risk (Drawdown, Vol)
             ▼                                        │
   PortfolioManagerAgent (MVO)                        ▼
             │                             HybridContextProvider
             ▼                             ├─ RuleContextProvider (alpha=0)
   RLExitAgent (PPO model)                 └─ BayesianContextProvider (alpha>0)
             │                                        │
             ▼                                        ▼
   ExecutionAgent (CCXT async)          MetaDecisionEngine.decide_with_provider()
   ├─ Shadow Log                                      │
   └─ CounterfactualEngine ─────────────────────────────
             │
             ▼
   logs/counterfactual_log.json
             │
             ▼
   Dashboard + Telegram + API (port 8000)
```

---

## 2. Data Pipeline

### 2.1. Data Flow — Continuous Learning

```text
Binance WebSocket (realtime)
      │
      ▼
CandleStore (in-memory, thread-safe RLock)
      │
      ▼
Feature Extraction (vectorized Pandas/NumPy)
      │
      ▼
Signal Detection (rule labels + TP/SL)
      │
      ▼
Signal Scoring (0=strong SELL, 50=neutral, 100=strong BUY)
      │
      ▼
ML Ensemble Scoring (meta_confidence, kelly_fraction)
      │
      ▼
Causal Context Enhancement (HybridContextProvider)
      │
      ▼
Trade Execution (CCXT async / Dry Run)
      │
      ▼
Closed Positions → MongoDB Atlas
      │
      ▼
ML Dataset (logs/adaptive_signals_v2.json)
      │
      ▼
Continuous Learning (scripts/continuous_learning.py — weekly)
```

### 2.2. Causal Context Data Flow (v2.0)

```text
Analysis Dict (coin)
      │
      ▼
build_world_state_from_ana()
      │  ├─ sentiment.FearGreed
      │  ├─ liquidity.BTC_Funding, OI_Delta
      │  ├─ crypto.BTC_Price
      │  ├─ macro.DXY/VIX/RealYield (from macro_collector + REST fallback)
      │  └─ alternative.* (from AlternativeDataCollector → load_alternative_data())
      │       ├─ etf_flow, etf_momentum       ← ParsebotFarsideETFCollector (MongoDB)
      │       ├─ exchange_netflow, whale_score ← on-chain collectors
      │       ├─ stablecoin_supply, funding_pressure, macro_pressure
      │       ├─ effective_etf_momentum       ← confidence-weighted (etf_flow_confidence)
      │       └─ effective_risk_on_score      ← confidence-weighted composite
      ↓
WorldState
      │
      ▼
HybridContextProvider.generate_context_report(score, state)
      │  ├─ RuleContextProvider (rule-based adjustments)
      │  └─ BayesianContextProvider (Gaussian inference, alpha-blended)
      ▼
ContextReport (adjusted_score, risk_level, adjustments)
      │
      ▼
MetaDecisionEngine.decide_with_provider()
      │
      ▼
Enhanced Decision {action, posterior, context_risk_level, context_adjustment}
```

### 2.3. Dataset Schema

```python
timestamp               # Thời gian đóng nến
coin                    # Ký hiệu (VD: BTCUSDT)
direction               # Chiều vị thế (LONG / SHORT)
signal_score            # Điểm tín hiệu rule-based
rsi                     # Relative Strength Index
macd_hist               # MACD Histogram
atr_pct                 # Normalized ATR
volume_ratio            # Volume spike ratio
fear_greed              # Fear & Greed Index (-1.0 → +1.0)
ema_distance_pct        # Khoảng cách EMA
bb_width_pct            # Bollinger Bands width
adx                     # Trend strength
mtf_alignment           # MTF confluence (-1/0/+1 per timeframe)
regime                  # Market regime (8 states)
meta_confidence         # ML win probability [0,1]
causal_risk_level       # Causal context risk (LOW/MEDIUM/HIGH/CRITICAL)
causal_alpha            # Blending factor used
entry_price / sl_price / tp_price
hold_hours
is_win                  # Target label (1=Win, 0=Loss)
```

---

## 2.4. Signal Detection & Scoring Flow

Tài liệu đánh giá chi tiết: [`signal_detection_and_scoring_assessment.md`](../evaluations/signal_detection_and_scoring_assessment.md).

Luồng production hiện tại:

```text
main.py::fetch_and_display()
  -> AgentOrchestrator.run_cycle()
  -> MarketAnalystAgent
  -> analyze_market() for 15m + 1h/4h/1d
  -> SignalGeneratorAgent
  -> evaluate_signal_score() / score_signal()
  -> CausalContextBridge + CausalGate
  -> RiskManagerAgent
  -> PortfolioManagerAgent
  -> ExecutionAgent / AutoTrader
```

Các ngưỡng và ngữ nghĩa chính:

| Layer | Current behavior |
| --- | --- |
| Raw signal | Text label từ RSI, EMA, SFP, pullback, break-SMA50, regime và sentiment. |
| Internal score | `0 = strong SELL`, `50 = NEUTRAL`, `100 = strong BUY`. |
| Strength / display score | Direction-normalized: BUY dùng `score`, SELL dùng `100 - score`; AutoTrader dùng `strength` cho threshold. |
| Meta confidence | Thiếu `meta_confidence` thì AutoTrader bỏ qua, không auto-trade. |
| MTF confluence | 1h/4h/1d alignment cộng/trừ score; 1h ngược chiều bị phạt mạnh nhất. |
| Causal gate | `CRITICAL` đổi `signal_score.action` về `NEUTRAL`; AutoTrader hard-block nếu action không còn BUY/SELL trước execution. |
| AutoTrader gate | Bỏ qua WEAK signal, dưới ngưỡng meta/score, trùng vị thế, tương quan > 0.75, circuit breaker hoặc exposure breach. |

Current assessment:

```text
Signal detection: PASS
Signal scoring: PASS - side-agnostic strength added
Paper auto-trade gating: PASS
Live execution readiness: CONDITIONAL
Maintainability: analysis/core.py should be split into smaller strategy modules
```

---

## 3. Multi-Agent Architecture

6 Agent chạy tuần tự trong `AgentOrchestrator`:

| Agent | Vai trò | File |
|-------|---------|------|
| `MarketAnalystAgent` | Phân tích 15m + MTF (1h/4h/1d), HTF Trend Summary | `ml_engine/multi_agent.py` |
| `SignalGeneratorAgent` | ML scoring + Causal Context Bridge + CausalGate | `ml_engine/multi_agent.py` |
| `RiskManagerAgent` | Drawdown gate (<10%), risk multiplier (consecutive losses) | `ml_engine/multi_agent.py` |
| `PortfolioManagerAgent` | MVO allocation khi ≥2 tín hiệu đồng thời | `ml_engine/multi_agent.py` |
| `RLExitAgent` | Load PPO model, shadow mode logging | `ml_engine/multi_agent.py` |
| `ExecutionAgent` | CCXT async, shadow log, CounterfactualEngine hook | `ml_engine/multi_agent.py` |

---

## 4. Causal World Model Stack (v2.1)

### 4.1. 5 Thành phần Nền tảng (Phase 2.0)

| Component | File | Vai trò |
|-----------|------|---------|
| `WorldStateManager` | `core/world_state.py` | Single source of truth, thread-safe (RLock) |
| `EventBus` | `core/event_bus.py` | Pub/Sub, 10 event types, ready for Kafka/Redis |
| `ContextProvider` | `ml_engine/context_provider.py` | Abstract interface — strategy pattern |
| `SnapshotManager` | `core/feature_snapshot.py` | Replay/Debug/Counterfactual |
| `CausalMonitor` | `ml_engine/causal_monitoring.py` | Metrics & JSON dashboard |

### 4.2. Các Phase Đã Triển Khai

| Phase | Mô tả | Test | Trạng thái |
|-------|-------|------|-----------|
| **2.1** | RuleContextProvider, CausalEventHandlers, `decide_with_provider()` | 18/18 | ✅ Production |
| **3.0** | BayesianContextProvider, CausalDiscoveryEngine, HybridContextProvider | 33/33 | ✅ Production |
| **4.0** | CausalSimulator, CounterfactualEngine, CLI | 3/3 | ✅ Production |
| **5.0** | WorldModelPredictor, CausalAnomalyDetector | 2/2 | ✅ Production |
| **6.0** | MacroAgent, LiquidityAgent, SentimentAgent, ConsensusEngine | 2/2 | ✅ Production |
| **A** | CausalContextBridge, build_world_state_from_ana(), singleton | 10/10 | ✅ Production |
| **B** | CausalGate trong SignalGeneratorAgent | — | ✅ Production |
| **C** | decide_with_provider() entry point | — | ✅ Production |
| **D** | CounterfactualEngine hook trong ExecutionAgent | — | ✅ Production |

### 4.3. Triển Khai An Toàn (Safe Rollout)

```bash
# Bước 1: Alpha=0.0 (rule-only) — default, an toàn tuyệt đối
CAUSAL_ALPHA=0.0

# Bước 2: Sau 2-4 tuần shadow mode → xem xét
CAUSAL_ALPHA=0.1    # 90% rules + 10% Bayesian

# Bước 3: Weekly discovery (recommended)
python -c "from btc_scraper.ml_engine.causal_discovery import CausalDiscoveryEngine; CausalDiscoveryEngine().discover()"

# Bước 4: Enable learned rules trong context_rules.json
# "enable_learned_rules": true
```

---

## 5. Feature Engineering

Bộ đặc trưng **40+ features** qua Feature Extractor:

### Momentum
```python
return_15m, return_1h, return_4h, return_1d, roc_14, roc_50
```

### Trend
```python
ema9_slope, ema21_slope, sma50_slope, sma200_slope, trend_strength
tf_1h_bull, tf_4h_bull, tf_1d_bull   # MTF per-TF direction features
```

### Volatility
```python
realized_vol_20, realized_vol_50, atr_percentile, hv20, hv60
```

### Liquidity
```python
obv, cmf, mfi, volume_percentile, volume_acceleration
```

### Market Structure
```python
distance_support, distance_resistance, higher_high, lower_low, bos, choch
```

### Causal/Macro (Phase 3.0+)
```python
DXY, VIX, RealYield, BondYield, BTC_Funding, OI_Delta, FearGreed
causal_risk_level, causal_alpha
```

**Anti-overfitting**: Feature Correlation Filter loại bỏ features > 0.85 correlation.

---

## 6. Explainable AI (XAI)

### Feature Importance
```python
RandomForest.feature_importances_   # Direct tree importance
```

### SHAP
```python
shap.TreeExplainer   # Per-prediction feature contribution
```

### Causal Reasoning (`CausalReasoningEngine`)
```python
engine = CausalReasoningEngine("data/causal_graph.json")
reasoning = engine.generate_reasoning_tree(target="BTC", signal_direction="BUY")
print(reasoning.explanation)
# "BUY signal driven by: DXY, RealYield. Primary path: FedRate → BondYield → DXY → BTC. Confidence: 82%."
```

---

## 7. Dynamic Position Sizing

### Kelly Fraction
$$f^* = \frac{bp - q}{b}$$

- **b** = Reward/Risk Ratio
- **p** = `meta_confidence` (xác suất thắng từ ML)
- **q** = 1 − p

```python
position_size = 0.25 * kelly_fraction   # Fractional Kelly (25%)
```

### Portfolio Optimization (MVO — khi ≥2 tín hiệu đồng thời)
```python
# Mean-Variance Optimization
weights = PortfolioManager(method="MVO", risk_aversion=2.0, max_weight=0.30)
         .allocate_weights(signals_info, raw_candles)
```

---

## 8. Reinforcement Learning Exit Manager

### Môi trường (Gymnasium)
- **State Space**: 18D — RSI, MACD Hist, ATR%, ADX, BB Width, meta_confidence, fear_greed, volume_ratio, PnL%, hold_time, Market Regime (8-dim one-hot)
- **Action Space**: 6 discrete — `HOLD`, `PARTIAL_CLOSE_50`, `MOVE_SL_BREAKEVEN`, `TAKE_PROFIT`, `EXIT`, `TRAILING_SL_ATR`
- **Reward**: Net PnL ± drawdown penalty ± holding penalty/bonus − transaction cost 0.3%

### Kết quả thực nghiệm (PPO 500k steps):
| Metric | Rule-Based | RL Agent (PPO) |
|--------|-----------|---------------|
| Mean Reward | -4.157 | **-2.509** (+1.648) |
| Mean PnL | -0.134% | -0.304% |
| SL Hit Rate | 72.1% | 40.4% |

**Known Issue**: Nghịch lý Reward-PnL — PPO chốt lời non, phí 0.3% ăn 30-60% lợi nhuận.
**Roadmap**: Simplify reward → net PnL; chuyển sang `MlpLstmPolicy`; tăng step size 15m→1h.

---

## 9. Walk Forward Validation

```text
Train: Jan-Jun  -->  Test: Jul
Train: Feb-Jul  -->  Test: Aug
Train: Mar-Aug  -->  Test: Sep
...
```

**Metrics**: ROC-AUC, Accuracy, Precision/Recall/F1, Profit Factor, Sharpe Ratio, Max Drawdown.

---

## 10. Portfolio Metrics

$$\text{Sharpe} = \frac{R_p - R_f}{\sigma_p}, \quad \text{Sortino} = \frac{R_p - R_f}{\sigma_{\text{downside}}}$$

$$\text{MDD} = \frac{\text{Peak} - \text{Trough}}{\text{Peak}}, \quad \text{Calmar} = \frac{\text{CAGR}}{\text{MDD}}$$

---

## 11. Online Learning Workflow

```text
Closed Trade → Append Dataset → Feature Validation
      → Retrain Candidate → Walk Forward Eval
      → Concept Drift Check (ROC-AUC ≥ 0.55)
      → Deploy Model → Shadow Prediction → Production
```

---

## 12. Market Regime Engine

8 trạng thái thị trường (one-hot encoded trong RL state space):

| Regime | Tác động |
|--------|---------|
| `STRONG_TREND` | Nới rộng TP, dùng Trailing SL |
| `WEAK_TREND` | Bình thường |
| `COMPRESSION` | Giảm position size, chờ breakout |
| `BREAKOUT` | Tăng tốc entry |
| `MEAN_REVERSION` | TP nhanh, SL chặt |
| `PANIC_SELL` | Block BUY, giảm size |
| `LOW_LIQUIDITY` | Giảm size, tránh market order |
| `PUMP_RISK` | Block SELL, cảnh báo |

---

## 13. Signal Tracker (Persistent)

`SignalTracker` theo dõi trạng thái tín hiệu bền vững qua file `data/tracked_signals.json`:

- **TTL**: 90 phút — tự động prune signals cũ.
- **States**: `Running`, `Hit TP1`, `Hit TP2`, `Hit SL`.
- **Evaluation**: Mỗi scan so sánh current_close với TP1/TP2/SL của mỗi signal còn active.
- **Integration**: `signal_tracker.register_signal()` được gọi trong `analysis/core.py`; tracked signals hiển thị trong Telegram alerts dưới "THEO DÕI TÍN HIỆU ĐÃ CÓ".

---

## 14. Lộ trình Phát triển (Roadmap)

```text
Phase 1-4 ✅   Feature Engineering + Regime + Ensemble ML + RL Exit
Phase 5 ✅     Portfolio Optimization (MVO + Risk Parity)
Phase 6 ✅     Multi-Agent AI (6 agents + AgentOrchestrator)
Phase 2.1 ✅   Causal Integration: RuleContextProvider + Event Bus
Phase 3.0 ✅   Learning: BayesianContextProvider + CausalDiscovery
Phase 4.0 ✅   Simulation: CausalSimulator + CounterfactualEngine
Phase 5.0 ✅   Digital Twin: WorldModelPredictor + AnomalyDetector
Phase 6.0 ✅   Multi-Agent Causal: ConsensusEngine + Sub-Agents
Phase A-D ✅   Production Integration: Bridge → Gate → Counterfactual
               ↓
[HIỆN TẠI] Hardening Sprint
- Fix circular import (multi_agent.py → main.py)
- Graceful shutdown + atomic file writes
- Pin dependencies (requirements-lock.txt)
               ↓
Causal Activation Sprint
- CAUSAL_ALPHA=0.1 (sau shadow mode validation)
- Weekly CausalDiscovery on 6-month data
- Grafana/Prometheus observability
               ↓
RL Improvement Sprint
- Simplify reward (net PnL focus)
- MlpLstmPolicy (sequential memory)
- Step size 15m → 1h
               ↓
RLContextProvider (v4.0)
- Learn context adjustments from shadow mode data
               ↓
LLMContextProvider (v5.0)
- Gemini AI real-time macro reasoning
```

---

**Document Version**: 3.0.0
**Last Updated**: 2026-07-02
**Architecture**: v2.1 (Event-Driven Causal AI)
**Test Coverage**: 196/196 PASSED ✅
