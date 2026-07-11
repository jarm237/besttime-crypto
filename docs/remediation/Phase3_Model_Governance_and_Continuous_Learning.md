# Phase 3 — Model Governance & Continuous Learning

> Project: `besttime-crypto` — AI Quant Trading Platform  
> Roadmap: Khắc phục thiếu sót sau Phase 7–10  
> Nguyên tắc: Không chuyển phase nếu acceptance criteria chưa đạt.

## 1. Mục tiêu

Ngăn model yếu ghi đè production, xây model registry, promotion gate, rollback, shadow A/B và calibration monitoring.

## 2. Thời gian dự kiến

```text
2–3 tuần
```

## 3. Phạm vi
- Production/challenger/shadow states
- Promotion gate
- Versioning và rollback
- Calibration monitor
- Auto-report dashboard

## 4. Danh sách công việc

### Task 3.1 — Tách model states `[P0]`
- production/
- challenger/
- archive/
- rejected/

### Task 3.2 — Promotion gate `[P0]`
- min_samples>=1000
- CV AUC>=0.58
- Holdout AUC>=0.56
- Calibration error<=10%
- CV-holdout gap<=0.05

### Task 3.3 — Chặn overwrite `[P0]`
- PROMOTED/REJECTED/SHADOW_ONLY
- Không báo ready nếu chưa pass

### Task 3.4 — Versioning và rollback `[P1]`
- Artifact hash
- Feature schema hash
- Atomic promotion
- Automatic rollback triggers

### Task 3.5 — Shadow A/B pipeline `[P1]`
- Production vs challenger
- Decision disagreement
- PnL impact
- Calibration

### Task 3.6 — Calibration monitor `[P1]`
- ECE
- Brier score
- Reliability curve
- Bucket 0.8–1.0

### Task 3.7 — Dashboard governance `[P1]`
- Current model
- Latest challenger
- Promotion reasons
- Rollback history

## 5. Deliverables
- Model registry
- Promotion gate
- Shadow pipeline
- Rollback mechanism
- Calibration monitor
- Governance dashboard

## 6. Acceptance Criteria
- [ ] Không auto overwrite production
- [ ] Mọi model có metadata/version
- [ ] Gate tự động
- [ ] Rollback test pass
- [ ] Schema mismatch chặn load
- [ ] High-confidence bucket được monitor

## 7. Test Plan
- Weak holdout
- High calibration error
- Schema mismatch
- Corrupt artifact
- Concurrent retrain
- Rollback

## 8. Rủi ro và giảm thiểu

| Rủi ro | Mức độ | Giảm thiểu |
|---|---:|---|
| Promotion không atomic | Rất cao | Atomic swap |
| Challenger benchmark khác production | Cao | Shared holdout benchmark |
| Shadow sample quá ít | Trung bình | Minimum trade count |

## 9. Điều kiện chuyển phase

```text
Production chỉ thay qua promotion gate, rollback và shadow metrics hoạt động.
```
