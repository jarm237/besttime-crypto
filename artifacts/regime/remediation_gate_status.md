# Regime remediation gate status

**Kết luận:** `NOT_READY_FOR_PRODUCTION_ENFORCEMENT`. Giữ runtime ở `observe`.

| Gate | Trạng thái | Kết luận |
|---|---|---|
| A — Code safety | PASS | Effect mặc định tắt; shadow không thể execute; enforce cần promotion approval và chỉ một effect; mapping bear, ATR và ADX đã được test. |
| B — Contract readiness | PASS | Snapshot canonical, mapping legacy, config/hash, degraded shadow config, entry snapshot immutable và world state tách biệt đã có. |
| C — Evidence readiness | PARTIAL | Lineage mới đã được triển khai, nhưng evidence lịch sử không phải native post-remediation và thiếu detector confidence 100%. |
| D — Research readiness | PARTIAL | Feature/backtest/tuner đã sửa; chưa đủ holdout có timestamp hợp lệ. |
| E — Shadow readiness | BLOCKED | Chưa có control/shadow parity window, native outcomes đủ lớn hoặc promotion artifact được duyệt. |
| F — Production enforcement | BLOCKED | Chưa có rollout giảm rủi ro, rollback drill và phê duyệt riêng từng effect. |

## Bằng chứng định lượng

- Regression suite: 114 test pass; remediation suite: 42 test pass.
- Historical baseline: 2.570.232 nến từ 21 file; source hash `1074112ecb2dcc1060bb397aab9ee07ad5399d4ee7b2bc3910bc995e24c97d2a`.
- Transition frequency: `10.0088%` trước → `6.4332%` sau.
- Average duration: `9.9912` → `15.5443` bars.
- Feature v2: 24.070 dòng; 3.443 dòng `UNKNOWN`; 24.070 dòng thiếu detector confidence do nguồn legacy.
- Governed tuner: train/validation/holdout = `9/2/3`, timestamp coverage không đầy đủ, tất cả fallback về `1.0` với `INSUFFICIENT_EVIDENCE`.

## Promotion decision

`REJECT_ENFORCEMENT_KEEP_OBSERVE`

Các điều kiện còn thiếu: native post-remediation lineage, control/shadow parity trên cùng cutoff, holdout đầy đủ timestamp/cost/slippage, rollout chỉ giảm rủi ro và rollback drill.
