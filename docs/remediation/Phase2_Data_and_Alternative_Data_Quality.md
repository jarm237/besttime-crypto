# Phase 2 — Dữ liệu & Alternative Data Quality

> Project: `besttime-crypto` — AI Quant Trading Platform  
> Roadmap: Khắc phục thiếu sót sau Phase 7–10  
> Nguyên tắc: Không chuyển phase nếu acceptance criteria chưa đạt.

## 1. Mục tiêu

Phân biệt missing với neutral, bổ sung metadata nguồn/freshness/confidence và kiểm soát completeness của Alternative Data.

## 2. Thời gian dự kiến

```text
2–3 tuần
```

## 3. Phạm vi
- None != 0.0
- Feature metadata
- Health monitor required vs optional
- Loại fillna(0.0) toàn cục
- Collector resilience
- Feature source registry

## 4. Danh sách công việc

### Task 2.1 — Sửa data semantics `[P0]`
- None=missing
- 0.0=giá trị thật
- NaN không persist
- Audit toàn bộ alt features

### Task 2.2 — Metadata cho feature `[P0]`
- available
- status
- source
- confidence
- observed_at
- age_seconds
- is_stale

### Task 2.3 — Alternative Data Monitor `[P1]`
- required health
- optional health
- snapshot_count_24h
- freshness
- completeness

### Task 2.4 — Loại fake-neutral `[P1]`
- Bỏ global fillna(0.0)
- Imputer chỉ ở ML pipeline
- Thêm feature__missing

### Task 2.5 — Collector resilience `[P1]`
- Timeout/retry/backoff
- 429 handling
- Circuit breaker/cache/fallback
- Schema validation

### Task 2.6 — Feature source registry `[P1]`
- Map DefiLlama/Binance/Yahoo/ETF providers
- Range và missing policy cho từng field

## 5. Deliverables
- Missing-data standard
- Feature metadata schema
- AlternativeDataMonitor
- Feature source registry
- Data quality dashboard

## 6. Acceptance Criteria
- [ ] Không dùng 0.0 cho missing
- [ ] Critical features có metadata
- [ ] Tách health required/optional
- [ ] Không còn global fillna(0.0)
- [ ] Optional collector fail không hỏng cycle
- [ ] Freshness/completeness alert hoạt động

## 7. Test Plan
- Missing raw input
- Stale source
- Empty API values
- 404/429/500
- Insufficient history
- Real zero
- Schema drift

## 8. Rủi ro và giảm thiểu

| Rủi ro | Mức độ | Giảm thiểu |
|---|---:|---|
| None làm model pipeline fail | Cao | Imputer + missing flags |
| Fallback data lệch nghĩa | Cao | Bắt buộc source/confidence |
| Lịch sử chưa đủ | Trung bình | Warm-up status |

## 9. Điều kiện chuyển phase

```text
Không fake-neutral; source, confidence, freshness và health dashboard đầy đủ.
```
