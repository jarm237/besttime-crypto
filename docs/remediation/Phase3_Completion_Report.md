# Phase 3 — Báo cáo Hoàn thành Model Governance & Continuous Learning

> **Ngày hoàn thành:** 2026-07-11  
> **Trạng thái Phase 3:** ✅ FUNCTIONALLY PASSED

## Tổng kết

Đã bổ sung registry file-based cho vòng đời model. Production chỉ thay đổi qua promotion gate; version cũ được archive để rollback, và schema/artifact được xác thực trước khi load.

## Hạng mục đã hoàn thành

| Task | Kết quả |
|---|---|
| 3.1 Model states | Registry tách `production/`, `challenger/`, `archive/`, `rejected/`, `shadow/`. |
| 3.2 Promotion gate | Kiểm tra sample count, CV AUC, holdout AUC, calibration error, và CV–holdout gap. |
| 3.3 Overwrite protection | Kết quả rõ ràng `PROMOTED` hoặc `REJECTED`; model rejected không thể thay production. |
| 3.4 Versioning/rollback | SHA-256 artifact, feature-schema hash, atomic copy/swap, archive và rollback history. |
| 3.5 Shadow A/B | Log probability production/challenger, disagreement, outcome và PnL impact. |
| 3.6 Calibration | ECE, Brier score, reliability buckets, và bucket high-confidence ≥0.8. |
| 3.7 Governance dashboard | `ModelRegistry.dashboard()` trả current model, challenger, decisions, rollback history và shadow calibration. |

## Kiểm thử

Targeted: **13 passed** — governance registry, promotion rejection, schema mismatch, rollback, shadow metrics, calibration và meta-model regression tests.  
Full suite: **371 passed, 5 subtests passed**.

## Acceptance criteria

| Criterion | Trạng thái |
|---|---|
| Không auto overwrite production | ✅ |
| Mọi model có metadata/version | ✅ |
| Gate tự động | ✅ qua `ModelRegistry.promote()` |
| Rollback test pass | ✅ |
| Schema mismatch chặn load | ✅ |
| High-confidence bucket được monitor | ✅ |

## Files chính

- `btc_scraper/ml_engine/model_governance.py`
- `tests/test_phase3_model_governance.py`

## Lưu ý vận hành

Training job cần đăng ký artifact qua `ModelRegistry.register()` và gọi `promote()`; không được copy artifact trực tiếp vào `production/`. `load_production(features)` bắt buộc schema runtime đúng với schema đã được train.
