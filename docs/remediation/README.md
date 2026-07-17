# Besttime-Crypto — Remediation Roadmap

## Thứ tự triển khai

```text
Phase 0 — Ổn định hệ thống
  ↓
Phase 1 — Hoàn thiện Execution Pipeline
  ↓
Phase 2 — Data & Alternative Data Quality
  ↓
Phase 3 — Model Governance & Continuous Learning
  ↓
Phase 4 — Infrastructure & Operational Resilience
  ↓
Phase 5 — Paper Trading Validation
  ↓
Phase 6 — Live Production Readiness
```

## Nguyên tắc

- P0 phải hoàn tất trước P1.
- Không chuyển phase nếu acceptance criteria chưa đạt.
- Không bật live trước khi Phase 5 kết luận GO.
- Mọi thay đổi model và execution phải có rollback.

## Cập Nhật Vận Hành Mới Nhất

| Ngày | Báo cáo | Trạng thái |
| --- | --- | --- |
| 2026-07-17 | `System_Status_Report_2026-07-17.md` | Documentation rollup; live trading blocked; Gate A/shadow evidence pending |
| 2026-07-17 | `System_Operational_Update_2026-07-17.md` | Trade provenance implemented; WLD operational correction applied; shadow evidence not started |

Trạng thái hiện tại:

```text
Trade provenance taxonomy: IMPLEMENTED
System paper vs user Telegram/UI/CLI distinction: IMPLEMENTED
WLD duplicate open correction: APPLIED
Gate A runtime evidence: PENDING
Shadow evidence window: NOT STARTED
Runtime calibration readiness: BLOCKED
Meta promotion readiness: BLOCKED
Live trading: DISABLED
```
