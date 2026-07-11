# Phase 1 — Hoàn thiện Execution Pipeline

> Project: `besttime-crypto` — AI Quant Trading Platform  
> Roadmap: Khắc phục thiếu sót sau Phase 7–10  
> Nguyên tắc: Không chuyển phase nếu acceptance criteria chưa đạt.

## 1. Mục tiêu

Đưa ExecutionEngine vào main loop và đảm bảo mọi lệnh đi qua liquidity, slippage, latency, risk guard, order selection và fill tracking.

## 2. Thời gian dự kiến

```text
2–3 tuần
```

## 3. Phạm vi
- Hook ExecutionEngine vào ExecutionAgent
- Cấm bypass CCXT
- Kết nối LiquidityAnalyzer/SlippagePredictor/RiskMonitor
- FillTracker + PostTradeAnalyzer
- Integration test end-to-end

## 4. Danh sách công việc

### Task 1.1 — Hook ExecutionEngine `[P0]`
- Signal → Risk → Portfolio → ExecutionEngine → Exchange
- Chuẩn hóa ExecutionResult schema

### Task 1.2 — Cấm direct write `[P0]`
- Tách ExchangeAdapter
- Chỉ ExecutionEngine được inject write adapter
- Module khác chỉ read-only

### Task 1.3 — Kết nối module execution `[P0]`
- LiquidityAnalyzer
- SlippagePredictor
- ExecutionRiskMonitor
- OrderTypeSelector
- ExecutionPlanner/TWAP

### Task 1.4 — Chuẩn hóa pre-trade guard `[P0]`
- Spread/slippage/latency/liquidity limits
- Dynamic size reduction
- Emergency policy riêng

### Task 1.5 — Fill và post-trade analytics `[P0]`
- Log decision/submission/fill prices
- Fee/spread/slippage/latency
- Implementation shortfall

### Task 1.6 — Integration tests `[P0]`
- High spread reject
- High slippage reject
- Low liquidity reduce/reject
- Partial fill
- TWAP
- Emergency exit

## 5. Deliverables
- ExecutionEngine integrated in main loop
- Isolated ExchangeAdapter
- Pre-trade guard active
- FillTracker/PostTradeAnalyzer connected
- Execution integration test suite

## 6. Acceptance Criteria
- [ ] 100% write orders qua ExecutionEngine
- [ ] Không còn direct CCXT write
- [ ] Guard hoạt động đúng
- [ ] Partial fill đúng state
- [ ] Persist fill/post-trade logs
- [ ] Paper execution ổn định 72 giờ

## 7. Test Plan
- Signal-to-fill integration
- Timeout/retry/idempotency
- Partial fill
- Duplicate signal
- Emergency stop

## 8. Rủi ro và giảm thiểu

| Rủi ro | Mức độ | Giảm thiểu |
|---|---:|---|
| Double order do retry | Rất cao | Idempotency key theo signal_id |
| Partial fill sai position | Cao | State machine + reconciliation |
| Guard quá chặt | Trung bình | Shadow metrics trước enforce |

## 9. Điều kiện chuyển phase

```text
Execution flow tests pass, paper execution không bypass guard và logs đầy đủ.
```
