# Phase 4 — Hạ tầng & Độ ổn định vận hành

> Project: `besttime-crypto` — AI Quant Trading Platform  
> Roadmap: Khắc phục thiếu sót sau Phase 7–10  
> Nguyên tắc: Không chuyển phase nếu acceptance criteria chưa đạt.

## 1. Mục tiêu

Đảm bảo không mất dữ liệu hoặc dừng toàn hệ thống khi MongoDB, network, process, disk hoặc external API gặp sự cố.

## 2. Thời gian dự kiến

```text
2 tuần
```

## 3. Phạm vi
- DB circuit breaker + SQLite spool
- Graceful shutdown
- Atomic write adoption
- Service health checks
- Resource monitoring
- Chaos tests

## 4. Danh sách công việc

### Task 4.1 — DB Circuit Breaker + SQLite spool `[P0]`
- CLOSED/OPEN/HALF_OPEN
- Local durable spool
- Background replay
- Idempotent event_id

### Task 4.2 — Graceful shutdown `[P0]`
- Stop scheduler/websocket
- Flush queue/logs
- Close CCXT/aiohttp
- Wait subprocess
- Persist state

### Task 4.3 — Atomic writes `[P0]`
- latest_signals
- adaptive_signals
- counterfactual logs
- model metadata
- execution reports

### Task 4.4 — Health endpoints `[P1]`
- /live
- /ready
- /dependencies
- DB/exchange/model/disk checks

### Task 4.5 — Resource monitoring `[P1]`
- CPU/RAM/Disk
- event loop lag
- queue size
- API latency
- collector duration

### Task 4.6 — Chaos tests `[P1]`
- DB down
- DNS failure
- Disk full
- SIGTERM
- Corrupt model
- WebSocket disconnect

## 5. Deliverables
- DB circuit breaker
- SQLite spool/replay
- Graceful shutdown
- Atomic write coverage
- Health endpoints
- Chaos test suite

## 6. Acceptance Criteria
- [ ] DB down không mất event
- [ ] Replay không duplicate
- [ ] SIGTERM không corrupt files
- [ ] Sessions đóng sạch
- [ ] Readiness phản ánh dependency
- [ ] Chaos tests pass

## 7. Test Plan
- MongoDB outage
- Network outage
- SIGTERM during write
- Restart during replay
- Disk nearly full
- 429 storm

## 8. Rủi ro và giảm thiểu

| Rủi ro | Mức độ | Giảm thiểu |
|---|---:|---|
| Replay duplicate | Rất cao | Idempotent upsert |
| Spool tăng vô hạn | Cao | Quota/retention/alert |
| Shutdown treo | Trung bình | Timeout + forced close |

## 9. Điều kiện chuyển phase

```text
DB/network/process failures không làm mất dữ liệu và health/readiness đáng tin cậy.
```
