# Phase 0 — Ổn định hệ thống

> Project: `besttime-crypto` — AI Quant Trading Platform  
> Roadmap: Khắc phục thiếu sót sau Phase 7–10  
> Nguyên tắc: Không chuyển phase nếu acceptance criteria chưa đạt.

## 1. Mục tiêu

Loại bỏ lỗi nền tảng, đưa test suite về trạng thái xanh và tạo baseline đáng tin cậy trước khi tiếp tục tích hợp execution hoặc live trading.

## 2. Thời gian dự kiến

```text
1 tuần
```

## 3. Phạm vi
- Fix 4 test failures còn lại
- Chuẩn hóa test pipeline và CI gate
- Rà soát direct CCXT write calls
- Chuẩn hóa logging, exception và collector result
- Code review các module critical

## 4. Danh sách công việc

### Task 0.1 — Fix 4 test failures `[P0]`
- test_rl_exit_shadow_logging
- test_dataset_builder_v3_builds_dataset_with_labels_and_features
- test_train_meta_model_v3_generates_required_artifacts
- test_train_meta_model_v3_outputs_walkforward_and_comparison

Checklist kỹ thuật:
- [ ] Chạy từng test với -vv -s
- [ ] Phân loại schema/artifact/fixture/regression
- [ ] Sửa implementation trước khi sửa test
- [ ] Chạy lại toàn bộ suite

### Task 0.2 — Chuẩn hóa test pipeline `[P0]`
- Tạo lệnh pytest thống nhất
- Thêm CI fail-fast
- Lưu report before/after
- Chặn merge khi test fail

### Task 0.3 — Loại bỏ direct CCXT order `[P0]`
- Quét create_order và exchange.*
- Chỉ ExecutionEngine được quyền write
- Cho phép read-only market data và mock

### Task 0.4 — Chuẩn hóa logging/error handling `[P0]`
- Không dùng except: pass
- Log phải có signal_id/symbol/stage
- Collector optional trả success/skipped/error

### Task 0.5 — Critical code review `[P0]`
- main.py
- multi_agent.py
- meta_model.py
- dataset_builder_v3.py
- execution_engine.py
- collectors/

Checklist kỹ thuật:
- [ ] Không look-ahead
- [ ] Không fake-neutral
- [ ] Không overwrite model ngoài gate

## 5. Deliverables
- 321/321 tests passed
- Critical code review report
- Danh sách direct CCXT calls đã xử lý
- Logging/error handling standard
- Baseline system report

## 6. Acceptance Criteria
- [ ] Toàn bộ tests pass
- [ ] Không còn direct CCXT write ngoài execution layer
- [ ] Không còn except: pass ở luồng critical
- [ ] CI chặn merge khi fail
- [ ] Baseline report được lưu

## 7. Test Plan
- Full pytest suite
- Static scan direct exchange calls
- Failure injection collector
- Artifact path/model missing tests

## 8. Rủi ro và giảm thiểu

| Rủi ro | Mức độ | Giảm thiểu |
|---|---:|---|
| Sửa test thay vì sửa bug | Cao | Review implementation trước |
| Schema regression | Cao | Version schema + migration |
| Hidden exchange path | Cao | Static scan + integration test |

## 9. Điều kiện chuyển phase

```text
All tests pass, không còn direct execution path và baseline được phê duyệt.
```
