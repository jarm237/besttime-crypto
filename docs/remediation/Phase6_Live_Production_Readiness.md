# Phase 6 — Chuẩn bị Live Production

> Project: `besttime-crypto` — AI Quant Trading Platform  
> Roadmap: Khắc phục thiếu sót sau Phase 7–10  
> Nguyên tắc: Không chuyển phase nếu acceptance criteria chưa đạt.

## 1. Mục tiêu

Go-live với vốn nhỏ, hard risk limits, kill-switch, monitoring, alerting, reconciliation và runbook vận hành.

## 2. Thời gian dự kiến

```text
2 tuần chuẩn bị + rollout theo gate
```

## 3. Phạm vi
- Go/No-Go checklist
- Capital/risk limits
- Kill-switch
- Real-time monitoring
- Alerts
- Runbook
- Dry-run live
- Controlled rollout

## 4. Danh sách công việc

### Task 6.1 — Live checklist `[P0]`
- API key permissions
- Withdrawal disabled
- IP whitelist
- Time sync
- Model/config snapshot
- Rollback ready

### Task 6.2 — Hard risk limits `[P0]`
- Max position
- Max daily loss
- Max orders/day
- Max open positions
- Risk/trade

### Task 6.3 — Kill-switch `[P0]`
- Daily loss
- Consecutive losses
- Execution anomaly
- Position mismatch
- Model/DB failure
- Manual stop

### Task 6.4 — Real-time monitoring `[P1]`
- PnL
- Open positions
- Risk usage
- Slippage/latency
- Data/model/DB health

### Task 6.5 — Alerting `[P1]`
- Telegram/email
- INFO/WARNING/CRITICAL
- Multi-channel critical

### Task 6.6 — Runbook `[P1]`
- Startup/shutdown
- Rollback
- DB/exchange outage
- Position mismatch
- Kill-switch reset

### Task 6.7 — Dry-run live `[P1]`
- 24–72h live data
- No real orders
- Compare with paper

### Task 6.8 — Controlled go-live `[P1]`
- Stage 1: one symbol/one position
- Stage 2: more trades
- Stage 3: capital scaling by metrics

## 5. Deliverables
- Live readiness checklist
- Risk config
- Kill-switch
- Monitoring dashboard
- Alert rules
- Runbook
- Dry-run report
- Controlled go-live report

## 6. Acceptance Criteria
- [ ] All go/no-go gates pass
- [ ] Withdrawal disabled
- [ ] Kill-switch tested
- [ ] Position reconciliation works
- [ ] Critical alerts delivered
- [ ] Dry-run 24–72h clean
- [ ] Start with small capital
- [ ] Rollback immediate

## 7. Test Plan
- Manual kill-switch
- Daily loss breach
- Duplicate order
- Position mismatch
- Model/DB failure
- Restart with open position
- Emergency close

## 8. Rủi ro và giảm thiểu

| Rủi ro | Mức độ | Giảm thiểu |
|---|---:|---|
| Execution bug mất tiền | Rất cao | Tiny capital + hard limits |
| Position state mismatch | Rất cao | Reconciliation loop |
| Kill-switch fail | Rất cao | Periodic drills |
| Scale vốn sớm | Cao | Metric-based scaling |

## 9. Điều kiện chuyển phase

```text
Live với vốn nhỏ, mọi risk control hoạt động, có monitoring, runbook và rollback.
```
