# Phase 5 — Paper Trading Validation

> Project: `besttime-crypto` — AI Quant Trading Platform  
> Roadmap: Khắc phục thiếu sót sau Phase 7–10  
> Nguyên tắc: Không chuyển phase nếu acceptance criteria chưa đạt.

## 1. Mục tiêu

Xác thực end-to-end trên paper trading bằng execution data thực, so sánh expected/realized slippage và gross/net PnL.

## 2. Thời gian dự kiến

```text
4 tuần
```

## 3. Phạm vi
- 100+ paper fills
- Execution quality
- Gross vs net PnL
- Real-time model/data monitoring
- Causal shadow analysis
- Go/No-Go report

## 4. Danh sách công việc

### Task 5.1 — Chạy paper trading `[P1]`
- 2–4 tuần
- BTC/ETH/SOL
- Nhiều regime
- Log full decision-to-fill

### Task 5.2 — Expected vs realized slippage `[P1]`
- MAE/RMSE
- P50/P90/P95
- Bias by coin/order/regime

### Task 5.3 — Gross vs Net PnL `[P1]`
- Fees
- Spread
- Slippage
- Latency drift
- Cost drag %

### Task 5.4 — Execution metrics `[P1]`
- Reject rate
- Fill rate
- Partial fill
- Latency
- Implementation shortfall

### Task 5.5 — Model monitoring `[P1]`
- Prediction distribution
- Calibration proxy
- Feature drift
- Missing rate

### Task 5.6 — Causal impact shadow `[P1]`
- Without vs with adjustment
- Decision/PnL/DD difference

### Task 5.7 — Paper trading report `[P1]`
- Uptime
- PnL
- Execution
- Model/data quality
- Incidents
- Go/No-Go

## 5. Deliverables
- Paper fill dataset
- Execution quality report
- Gross/net PnL report
- Shadow model report
- Causal impact report
- Go/No-Go recommendation

## 6. Acceptance Criteria
- [ ] >=100 paper fills
- [ ] Critical incidents=0
- [ ] Reject rate<=20%
- [ ] Fill rate>=80%
- [ ] Slippage MAE<=10 bps
- [ ] Paper vs backtest degradation<=30%
- [ ] Data completeness>=90%

## 7. Test Plan
- Long-running stability
- Volatility spike
- Spread widening
- Network reconnect
- Model reload
- DB fallback during paper

## 8. Rủi ro và giảm thiểu

| Rủi ro | Mức độ | Giảm thiểu |
|---|---:|---|
| 100 trades chưa đại diện | Trung bình | Kéo dài theo regime |
| Paper fill quá lý tưởng | Cao | Orderbook-aware simulation |
| Schema backtest/paper lệch | Cao | Shared execution schema |

## 9. Điều kiện chuyển phase

```text
Paper approval rules pass, không unresolved P0/P1 và review kết luận GO.
```
