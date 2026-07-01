# Kế Hoạch Triển Khai & Kiến Trúc Causal World Model (v2.0)

Tài liệu này mô tả chi tiết kiến trúc nền tảng **Architecture v2.0** của Causal World Model trong hệ thống `besttime-crypto`. Phiên bản này đã chuyển đổi từ kiến trúc module tĩnh sang **Event-Driven Architecture** (hướng sự kiện) với khả năng quản lý trạng thái tập trung (Centralized State Management), sẵn sàng cho các giai đoạn nâng cao (Causal Discovery, World Model, RL, LLM).

---

## 1. Kiến Trúc Tổng Thể (5-Layer Foundation)

Kiến trúc v2.0 bao gồm 5 thành phần cốt lõi đã được triển khai hoàn tất:

```text
Collectors
    ↓
[Event Bus] ──────────────────────┐
    ↓                             │
[World State Manager]             │
    ↓                             │
[Feature Snapshot & Replay] ← Stored
    ↓                             │
ContextProvider (Interface)       │
 ├─ RuleContextProvider (v2.0)    │
 ├─ BayesianContextProvider (v3.0)│
 ├─ RLContextProvider (v4.0)      │
 └─ LLMContextProvider (v5.0)     │
    ↓                             │
Decision Engine                   │
    ↓                             │
[Event Bus] (DECISION_MADE)       │
    ↓                             │
CausalMonitor → Dashboard JSON    │
```

---

## 2. Chi Tiết Các Thành Phần Nền Tảng (Core Components)

### 2.1. World State Manager (`world_state.py`)

- **Vai trò**: Single source of truth.
- **Cấu trúc**: Quản lý trạng thái theo 5 layer: `macro`, `liquidity`, `crypto`, `sentiment`, `risk`.
- **Đặc điểm**: Thread-safe (dùng RLock), immutable per cycle (dễ dàng cho replay), và theo pattern Singleton.

### 2.2. Event Bus (`event_bus.py`)

- **Vai trò**: Giao tiếp Pub/Sub giữa các thành phần.
- **Event Types**: Hỗ trợ 10 danh mục event (Macro, Market, Sentiment, Internal, System).
- **Khả năng mở rộng**: Interface sẵn sàng để migrate sang Kafka hoặc Redis Streams khi scale.

### 2.3. ContextProvider Interface (`context_provider.py`)

- **Vai trò**: Lớp trừu tượng cho việc xử lý bối cảnh.
- **Quy chuẩn**: Phải implement các hàm `generate_context_report()`, `should_apply_context()`, và `validate()`.
- **Phiên bản hiện tại**: `RuleContextProvider` (Rule-based). Mở đường cho `Bayesian`, `RL`, và `LLM`. Có hỗ trợ `CompositeContextProvider` để mix nhiều chiến lược.

### 2.4. Feature Snapshot & Replay (`feature_snapshot.py`)

- **Vai trò**: Lưu trữ trạng thái toàn cảnh tại thời điểm ra quyết định.
- **Cấu trúc Snapshot**: `world_state` (serialized), `context_report`, `events`, `decision`, `reasoning_data`.
- **Use Cases**:
  - **Replay/Debug**: Trả lời câu hỏi "Tại sao lệnh này lại được mở?".
  - **Counterfactual/What-if**: "Nếu DXY lúc đó không tăng thì sao?".
  - **Backtest**: Áp dụng luật mới lên dữ liệu cũ.

### 2.5. Causal Monitoring (`causal_monitoring.py`)

- **Vai trò**: Đo lường và giám sát sức khỏe của hệ thống Causal.
- **Metrics Tracked**: Graph (tỷ lệ edge active), Context (latency, rule fired), Reasoning (path length), Decision (action distribution), Event Bus (event volume).
- **Output**: Xuất ra JSON Dashboard để UI dễ dàng đọc.

---

## 3. Cấu Hình Dữ Liệu Nâng Cao (Data Configurations)

### `causal_graph.json` (v2.0)

Hỗ trợ đồ thị động (Dynamic Graph) và truyền dẫn độ tin cậy.

- **Trường mới**:
  - `layer`: Phân bổ node vào từng layer (ví dụ: `macro`).
  - `is_active`: Cho phép bật/tắt edge linh hoạt theo Regime.
  - `source`: Theo dõi nguồn gốc của quan hệ (`manual`, `learned`, `hybrid`).
  - `propagate_confidence`: Cờ cho phép nhân độ tin cậy dọc theo chuỗi nhân quả.

### `context_rules.json` (v2.0)

- **Trường mới**: Bổ sung `source` để tách biệt các rule do con người tạo (`manual`) và rule do AI tự học (`learned`). Có cờ `enable_learned_rules`.

---

## 4. Kế Hoạch Tích Hợp Giai Đoạn Tiếp Theo

Với nền móng v2.0 đã hoàn tất, lộ trình sẽ tập trung vào Integration và Learning:

### Phase 2.1 (Integration & Go-Live) ✅ COMPLETE

- [x] Tạo `RuleContextProvider` — Wrap `ContextEngine` vào interface `ContextProvider` (`btc_scraper/ml_engine/rule_context_provider.py`).
- [x] Update `decision_engine.py` — Thêm method `decide_with_provider(analysis_info, context_provider, world_state)` để DecisionEngine hoàn toàn không phụ thuộc vào implementation cụ thể.
- [x] Tạo `causal_event_handlers.py` — Đăng ký (Subscribe) 4 loại event trên Bus: `MACRO_EVENT`, `REGIME_CHANGE`, `FUNDING_SPIKE`, `RULES_RELOADED`.
- [x] Viết và chạy Integration Test — `tests/test_phase21_integration.py` — **18/18 PASSED**.

**Files Created/Modified:**
| File | Purpose | Status |
|------|---------|--------|
| `btc_scraper/ml_engine/rule_context_provider.py` | Bridges ContextEngine ↔ ContextProvider interface | ✅ NEW |
| `btc_scraper/ml_engine/causal_event_handlers.py` | Event Bus subscriptions (MACRO, REGIME, FUNDING) | ✅ NEW |
| `btc_scraper/ml_engine/decision_engine.py` | Added `decide_with_provider()` method | ✅ MODIFIED |
| `tests/test_phase21_integration.py` | 18 integration tests — all passed | ✅ NEW |

### Phase 3.0 (Learning & Causal Discovery) ✅ COMPLETE

- [x] Triển khai `BayesianContextProvider` — Gaussian log-likelihood inference trên 6 features (DXY, VIX, Funding_Z, FearGreed, RealYield, OI_Delta). Weights loaded từ `causal_graph.json` edge confidences.
- [x] Triển khai `CausalDiscoveryEngine` — Lagged correlation + simplified Granger causality. Discovered edges ghi vào `causal_graph.json` với `source="learned"`. Không bao giờ ghi đè manual edges.
- [x] Triển khai `HybridContextProvider` — Blends Rule-based + Bayesian với configurable alpha (0.0=rules only → 1.0=Bayesian only). Đọc flag `enable_learned_rules` từ `context_rules.json` cho phép rollout an toàn.
- [x] Integration Test — `tests/test_phase30_learning.py` — **33/33 PASSED**.
- [x] Combined test suite (Phase 2.1 + 3.0) — **51/51 PASSED**.

**Files Created:**
| File | Purpose | Status |
|------|---------|--------|
| `btc_scraper/ml_engine/bayesian_context_provider.py` | Gaussian Bayesian inference on WorldState features | ✅ NEW |
| `btc_scraper/ml_engine/causal_discovery.py` | Granger causality discovery + graph writer | ✅ NEW |
| `btc_scraper/ml_engine/hybrid_context_provider.py` | Alpha-blended Rule+Bayesian provider | ✅ NEW |
| `tests/test_phase30_learning.py` | 33 integration tests — all passed | ✅ NEW |

**Deployment Guide — Safe Rollout:**

1. **alpha=0.0** (default): Identical behavior to Phase 2.1 — safe to deploy immediately
2. **enable_learned_rules=false**: Bayesian ignored even if alpha>0 — extra safety gate
3. Run `CausalDiscoveryEngine.discover()` on 6-12 months historical data weekly
4. Review learned edges before enabling `enable_learned_rules=true` in `context_rules.json`
5. Gradually increase alpha (0.1 → 0.2 → 0.3) while monitoring shadow mode PnL

### Phase 4.0: Scenario Simulation & Counterfactual Analysis (Simulated Interventions)

Cho phép chạy thử nghiệm giả định (Intervention - Do-calculus) và phân tích phản thực tế (Counterfactual) trên lịch sử giao dịch bằng cách tận dụng hệ thống Replay và Snapshot hiện tại.

> **Foundation đã có**: `btc_scraper/ml_engine/scenario_interface.py` — Abstract classes (`Scenario`, `DigitalTwin`, `CounterfactualAnalyzer`), `ScenarioLibrary` với 6 predefined scenarios, và `ScenarioSimulator` cơ bản. Triển khai Phase 4 đã được hoàn tất bằng lớp simulator thực tế và engine counterfactual dùng WorldState hiện có.

- [x] **Triển khai `CausalSimulator`** (`btc_scraper/ml_engine/causal_simulator.py`):
  - Nhận một `WorldState` snapshot hiện tại hoặc quá khứ.
  - Cho phép người dùng áp dụng một can thiệp (ví dụ: Can thiệp $do(DXY = 110)$ hoặc $do(VIX = 35)$).
  - Lan truyền tác động (propagate impact) qua các edge hoạt động trong `causal_graph.json` dựa trên `weight` và `lag` để cập nhật các biến phụ thuộc (như `BTC`, `ETH`, `Sentiment`).
  - Trả về một `SimulatedWorldState`.
- [x] **Triển khai `CounterfactualEngine`** (`btc_scraper/ml_engine/counterfactual_engine.py`):
  - Phân tích các trade thua lỗ trong lịch sử (từ trade log hoặc database).
  - Chạy giả lập: "Nếu tại thời điểm t, một tin tức vĩ mô cực xấu (ví dụ: FOMC rate hike) xảy ra sớm hơn 2 giờ, hệ thống có đóng vị thế kịp thời không?".
  - So sánh PnL thực tế với PnL giả định để đánh giá độ nhạy của luật.
- [x] **Tích hợp CLI & API endpoints**:
  - Cung cấp lệnh CLI `python -m btc_scraper.ml_engine.simulator --state-id <id> --intervention "DXY=+5%"` để debug nhanh.
- [x] **Viết Integration Test** — `tests/test_phase40_simulation.py`

**Files đã tạo/cập nhật:**
| File | Purpose | Status |
|------|---------|--------|
| `btc_scraper/ml_engine/causal_simulator.py` | CausalSimulator — propagate interventions | ✅ DONE |
| `btc_scraper/ml_engine/counterfactual_engine.py` | CounterfactualEngine — what-if trade analysis | ✅ DONE |
| `btc_scraper/ml_engine/simulator.py` | CLI parsing helpers for interventions | ✅ DONE |
| `tests/test_phase40_simulation.py` | Integration tests | ✅ DONE |

**Verification:**
- Chạy: `./.venv/bin/python -m pytest -q tests/test_phase40_simulation.py`
- Kết quả: `3 passed in 2.43s`

### Phase 5.0: Digital Twin & World Model Prediction (Dự báo trạng thái thế giới)

Xây dựng một "Digital Twin" (bản sao số) của thị trường dựa trên đồ thị nhân quả để dự báo các bước chuyển dịch trạng thái tiếp theo (State Transition Model).

- [x] **Triển khai `WorldModelPredictor`** (`btc_scraper/ml_engine/world_model_predictor.py`):
  - Dự báo phân phối xác suất của `WorldState` tại thời điểm $t+1$ dựa trên trạng thái hiện tại $S_t$ và đồ thị nhân quả: $P(S_{t+1} | S_t)$.
  - Ràng buộc các dự đoán phi tuyến bằng các mối quan hệ nhân quả vật lý đã biết (ví dụ: DXY tăng mạnh chắc chắn tạo áp lực giảm lên giá BTC sau $N$ chu kỳ).
- [x] **Triển khai Causal Anomaly Detection** (`btc_scraper/ml_engine/causal_anomaly_detector.py`):
  - So sánh liên tục giữa `WorldState` thực tế thu thập được và trạng thái dự đoán từ `WorldModel`.
  - Nếu phát hiện độ lệch lớn (Significant Deviation) vượt quá ngưỡng tin cậy, kích hoạt cảnh báo phá vỡ cấu trúc nhân quả (Structural Break / Regime Drift) và phát sự kiện `REGIME_CHANGE` trên Event Bus.
- [x] **Viết Integration Test** — `tests/test_phase50_world_model.py`

**Files đã tạo/cập nhật:**
| File | Purpose | Status |
|------|---------|--------|
| `btc_scraper/ml_engine/world_model_predictor.py` | Digital Twin — state transition prediction | ✅ DONE |
| `btc_scraper/ml_engine/causal_anomaly_detector.py` | Structural break & regime drift detection | ✅ DONE |
| `tests/test_phase50_world_model.py` | Integration tests | ✅ DONE |

**Verification:**
- Chạy: `./.venv/bin/python -m pytest -q tests/test_phase50_world_model.py`
- Kết quả: `2 passed in 4.55s`

### Phase 6.0: Multi-Agent Causal Collaboration (Đồng thuận nhân quả đa Agent)

Chia nhỏ hệ thống context thành các Sub-Agent chuyên biệt giao tiếp phi tập trung qua Event Bus và thống nhất quyết định thông qua phân tích nhân quả.

- [x] **Thiết lập các Sub-Agent chuyên trách**:
  - `MacroAgent` (`btc_scraper/ml_engine/agents/macro_agent.py`): Giám sát DXY, Yields, FedRate và phát đi đánh giá rủi ro vĩ mô.
  - `LiquidityAgent` (`btc_scraper/ml_engine/agents/liquidity_agent.py`): Giám sát Funding, Orderbook, OI Delta và phát đi cảnh báo thanh lý.
  - `SentimentAgent` (`btc_scraper/ml_engine/agents/sentiment_agent.py`): Giám sát Fear & Greed, tin tức mạng xã hội.
- [x] **Triển khai Consensus Engine** (`btc_scraper/ml_engine/agents/consensus_engine.py`) **(Causal Voting / Bayesian Fusion)**:
  - Khi các Agent đưa ra các nhận định mâu thuẫn (ví dụ: Macro báo BEARISH nhưng Sentiment báo BULLISH).
  - Consensus Engine sẽ duyệt đồ thị nhân quả hiện tại để xác định Agent nào có biến tác động trực tiếp và mạnh hơn lên `BTC` tại Regime hiện tại để ưu tiên trọng số (Dynamic Weighting).
  - Xuất ra quyết định điều chỉnh cuối cùng thống nhất và ghi nhận vào log.
- [x] **Viết Integration Test** — `tests/test_phase60_multiagent.py`

**Files đã tạo/cập nhật:**
| File | Purpose | Status |
|------|---------|--------|
| `btc_scraper/ml_engine/agents/macro_agent.py` | MacroAgent — DXY, Yields, FedRate watcher | ✅ DONE |
| `btc_scraper/ml_engine/agents/liquidity_agent.py` | LiquidityAgent — Funding, OI, Orderbook watcher | ✅ DONE |
| `btc_scraper/ml_engine/agents/sentiment_agent.py` | SentimentAgent — Fear&Greed, social watcher | ✅ DONE |
| `btc_scraper/ml_engine/agents/consensus_engine.py` | Causal Voting / Bayesian Fusion | ✅ DONE |
| `tests/test_phase60_multiagent.py` | Integration tests | ✅ DONE |

**Verification:**
- Chạy: `./.venv/bin/python -m pytest -q tests/test_phase60_multiagent.py`
- Kết quả: `2 passed in 9.04s`
