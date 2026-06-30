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
* **Vai trò**: Single source of truth.
* **Cấu trúc**: Quản lý trạng thái theo 5 layer: `macro`, `liquidity`, `crypto`, `sentiment`, `risk`.
* **Đặc điểm**: Thread-safe (dùng RLock), immutable per cycle (dễ dàng cho replay), và theo pattern Singleton.

### 2.2. Event Bus (`event_bus.py`)
* **Vai trò**: Giao tiếp Pub/Sub giữa các thành phần.
* **Event Types**: Hỗ trợ 10 danh mục event (Macro, Market, Sentiment, Internal, System).
* **Khả năng mở rộng**: Interface sẵn sàng để migrate sang Kafka hoặc Redis Streams khi scale.

### 2.3. ContextProvider Interface (`context_provider.py`)
* **Vai trò**: Lớp trừu tượng cho việc xử lý bối cảnh.
* **Quy chuẩn**: Phải implement các hàm `generate_context_report()`, `should_apply_context()`, và `validate()`.
* **Phiên bản hiện tại**: `RuleContextProvider` (Rule-based). Mở đường cho `Bayesian`, `RL`, và `LLM`. Có hỗ trợ `CompositeContextProvider` để mix nhiều chiến lược.

### 2.4. Feature Snapshot & Replay (`feature_snapshot.py`)
* **Vai trò**: Lưu trữ trạng thái toàn cảnh tại thời điểm ra quyết định.
* **Cấu trúc Snapshot**: `world_state` (serialized), `context_report`, `events`, `decision`, `reasoning_data`.
* **Use Cases**:
  - **Replay/Debug**: Trả lời câu hỏi "Tại sao lệnh này lại được mở?".
  - **Counterfactual/What-if**: "Nếu DXY lúc đó không tăng thì sao?".
  - **Backtest**: Áp dụng luật mới lên dữ liệu cũ.

### 2.5. Causal Monitoring (`causal_monitoring.py`)
* **Vai trò**: Đo lường và giám sát sức khỏe của hệ thống Causal.
* **Metrics Tracked**: Graph (tỷ lệ edge active), Context (latency, rule fired), Reasoning (path length), Decision (action distribution), Event Bus (event volume).
* **Output**: Xuất ra JSON Dashboard để UI dễ dàng đọc.

---

## 3. Cấu Hình Dữ Liệu Nâng Cao (Data Configurations)

### `causal_graph.json` (v2.0)
Hỗ trợ đồ thị động (Dynamic Graph) và truyền dẫn độ tin cậy.
* **Trường mới**:
  - `layer`: Phân bổ node vào từng layer (ví dụ: `macro`).
  - `is_active`: Cho phép bật/tắt edge linh hoạt theo Regime.
  - `source`: Theo dõi nguồn gốc của quan hệ (`manual`, `learned`, `hybrid`).
  - `propagate_confidence`: Cờ cho phép nhân độ tin cậy dọc theo chuỗi nhân quả.

### `context_rules.json` (v2.0)
* **Trường mới**: Bổ sung `source` để tách biệt các rule do con người tạo (`manual`) và rule do AI tự học (`learned`). Có cờ `enable_learned_rules`.

---

## 4. Kế Hoạch Tích Hợp Giai Đoạn Tiếp Theo

Với nền móng v2.0 đã hoàn tất, lộ trình sẽ tập trung vào Integration và Learning:

### Phase 2.1 (Integration & Go-Live)
- [ ] Chuyển đổi toàn bộ `ContextEngine` cũ sang dùng `RuleContextProvider` (implement interface mới).
- [ ] Update `decision_engine.py` để chấp nhận object `ContextProvider`.
- [ ] Đăng ký (Subscribe) module tính toán bối cảnh vào Event Bus để nhận `MACRO_EVENT`, `REGIME_CHANGE`.
- [ ] Định tuyến Telegram Alerts để đọc thông báo trực tiếp từ Event Bus thay vì gọi hàm trực tiếp.
- [ ] Chạy Integration Test tổng thể toàn hệ thống.

### Phase 3.0 (Learning & Causal Discovery)
- [ ] Triển khai `BayesianContextProvider` để xử lý bối cảnh theo nguyên lý xác suất.
- [ ] Áp dụng thuật toán Causal Discovery (FCI / PC) để tự động phát hiện quan hệ từ dữ liệu, cập nhật source thành `learned`.
- [ ] Bật cờ `enable_learned_rules` và chạy phương pháp Hybrid (Manual + Learned).

### Phase 4 & Phase 5 (Future)
- **Phase 4**: Scenario Simulation & Counterfactual Analysis (dựa trên module Replay và Snapshot).
- **Phase 5**: Digital Twin / World Model Prediction.
- **Phase 6**: Multi-Agent Collaboration.
