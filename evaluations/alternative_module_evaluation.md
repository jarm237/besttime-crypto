# Báo Cáo Đánh Giá Module Alternative Data

Ngày đánh giá: 2026-07-16

## Tóm Tắt Điều Hành

Module Alternative Data hiện đã đủ nền tảng để vận hành production ở mức thu thập và giám sát: collector có nhiều nguồn dữ liệu, raw-store chạy đều, metadata/provenance rõ hơn trước, missing-data contract đã tránh lỗi fake-neutral, và test hẹp liên quan pass.

Tuy nhiên module chưa nên xem là hoàn tất cho training/feature engineering vì còn hai gap quan trọng:

1. `scripts/build_alternative_features.py` vẫn chỉ đọc tốt JSON/parquet; nhánh CSV đang nằm sau `return` nên không bao giờ chạy.
2. `scripts/run_phase8_pipeline.py` vẫn build alternative features từ `data/alternative_data.json`, tức snapshot mới nhất một dòng. Với input một dòng, các đặc trưng rolling/z-score/momentum gần như không có đủ lịch sử để tạo tín hiệu động.

Kết luận: **collector/quality layer: tốt; feature build pipeline: cần sửa trước khi dùng nghiêm túc cho ML retraining**.

## Phạm Vi Đánh Giá

Các thành phần đã rà:

- Collector orchestration: `btc_scraper/collectors/alternative_data.py`
- Registry/provenance: `btc_scraper/collectors/feature_source_registry.py`
- Scheduler/backfill/replay: `btc_scraper/collectors/alternative_scheduler.py`, `btc_scraper/collectors/alternative_backfill.py`
- Quality monitor/dashboard: `btc_scraper/collectors/alternative_quality.py`
- Feature engineering: `btc_scraper/feature_engineering/alternative_features.py`
- Build script/pipeline: `scripts/build_alternative_features.py`, `scripts/run_phase8_pipeline.py`
- Data artifacts: `data/alternative_data.json`, `data/raw_alternative/`, `data/alternative_quality.json`

## Kiến Trúc Hiện Tại

Luồng chính:

1. `AlternativeDataCollector` gọi các collector con: Binance, DefiLlama, FRED/Yahoo, Alternative.me, Glassnode, Blockchain, Blockchair, WhaleAlert, Deribit, ETF, Google Trends, Reddit.
2. Payload được normalize qua `normalize_alternative_payload()`, áp dụng missing-data contract, tính một số derived fields như `funding_pressure`, `open_interest_pressure`, `liquidity_pressure`, `macro_risk_score`, `risk_on_score`, `effective_*`.
3. Snapshot mới nhất ghi vào `data/alternative_data.json` và `data/alternative_feature_snapshot.json`.
4. Lịch sử từng lần collect ghi vào `data/raw_alternative/alternative_<timestamp>.json`.
5. `AlternativeFeatureBuilder` mở rộng 24 base columns thành z-score, momentum, change, rank và composite features.
6. `DataQualityChecker`/`CollectorHealthMonitor` kiểm tra required fields, range, freshness và cảnh báo ETF flow.

## Số Liệu Dữ Liệu Thực Tế

Đo trên `data/raw_alternative/`:

- Raw snapshots: **1.306 files**
- Load thành công: **1.306/1.306**
- Khoảng thời gian: **2026-07-03 06:24:49 UTC → 2026-07-16 01:23:40 UTC**
- Median cadence: **15,19 phút**
- Latest snapshot: `2026-07-16T01:23:40.052075+00:00`
- Latest `_errors`: **rỗng**
- Latest `feature_metadata`: **22 features**, **16 available**, **0 stale**

Coverage các trường chính:

| Field | Coverage | Non-null |
|---|---:|---:|
| `dxy`, `vix`, `us10y`, `gold` | 100,00% | 1306 |
| `funding_rate`, `open_interest`, `stablecoin_supply`, `tvl`, `hashrate`, `options_iv` | 99,92% | 1305 |
| `stablecoin_supply_total`, `chain_tvl`, `iv_skew` | 99,77% | 1303 |
| `fear_greed_raw` | 99,16% | 1295 |
| `risk_on_score` | 99,69% | 1302 |
| `sentiment_score`, `social_sentiment` | 79,48% | 1038 |
| `etf_flow` | 68,91% | 900 |
| `orderbook_imbalance` | 65,47% | 855 |
| `active_addresses`, `whale_score`, `liquidity_pressure` | 29,40% | 384 |
| `exchange_netflow` | 29,86% | 390 |

Latest missing features theo metadata: `active_addresses`, `etf_flow`, `exchange_netflow`, `sentiment_score`, `social_sentiment`, `whale_score`.

## Điểm Mạnh

1. **Raw-store hoạt động ổn định**  
   Snapshot lịch sử có cadence đều khoảng 15 phút, không thấy lỗi parse/load trong 1.306 file.

2. **Missing-data contract tốt hơn trước**  
   Boundary normalize giữ `None` cho nguồn thiếu, reject zero không có evidence, và thêm field status/metadata. Điều này giảm rủi ro đưa neutral giả vào model.

3. **Feature provenance rõ ràng**  
   `FEATURE_SOURCE_REGISTRY` định nghĩa source, requiredness, confidence, freshness, min/max. `feature_metadata` attach availability/status/confidence cho từng feature.

4. **Quality monitoring có chiều sâu**  
   `DataQualityChecker` kiểm tra timestamp stale, required fields, bounds, feature-level freshness. `CollectorHealthMonitor` có cảnh báo thiếu/stale và ETF-specific alerts.

5. **Feature builder point-in-time conscious**  
   Dữ liệu được sort theo `coin + timestamp` hoặc `entry_time` trước khi rolling transform. Builder cũng preserve missing values và thêm `<feature>__missing` flags.

6. **Test hẹp đang xanh**  
   Lệnh đã chạy:

   ```bash
   .venv/bin/pytest tests/test_alternative_data.py tests/test_alternative_features.py tests/test_phase2_data_quality.py tests/test_phase7_sprint7.py tests/test_alternative_quality_etf_alerts.py -q
   ```

   Kết quả: **45 passed**.

## Vấn Đề Và Rủi Ro

### P0 - Feature build pipeline dùng một snapshot duy nhất

`scripts/run_phase8_pipeline.py` gọi:

```text
scripts/build_alternative_features.py --input data/alternative_data.json
```

`data/alternative_data.json` là latest snapshot một dòng. Trong khi đó `AlternativeFeatureBuilder` cần chuỗi thời gian để rolling z-score, momentum và diff có ý nghĩa. Với một dòng:

- z-score không đủ `min_periods=2`
- momentum không đủ window
- rank cross-sectional không có tác dụng nếu chỉ một record
- composite phụ thuộc z-score sẽ thiếu hoặc không hữu ích

Tác động: feature store có thể được tạo thành công về mặt kỹ thuật, nhưng tín hiệu động của alternative data bị triệt tiêu khi training/scoring.

### P0 - CSV loader unreachable

Trong `scripts/build_alternative_features.py`, nhánh:

```python
if suffix == ".csv":
    return smart_read_csv(path)
```

đang nằm sau `return pd.DataFrame(raw)` bên trong block `.json`, nên không thể chạy. Input CSV sẽ rơi xuống `Unsupported input format: .csv`.

### P1 - Coverage một số nguồn còn thấp

Nhóm low coverage:

- `active_addresses`: 29,40%
- `whale_score`: 29,40%
- `exchange_netflow`: 29,86%
- `liquidity_pressure`: 29,40%
- `orderbook_imbalance`: 65,47%
- `etf_flow`: 68,91%

Các trường này nên được xem là optional/low-confidence trong model hoặc cần chiến lược backfill/provider fallback trước khi tăng weight.

### P1 - Latest snapshot thiếu 6 features optional

Latest snapshot không stale và không có `_errors`, nhưng metadata báo thiếu: `active_addresses`, `etf_flow`, `exchange_netflow`, `sentiment_score`, `social_sentiment`, `whale_score`.

Điều này không làm collector fail, nhưng downstream cần dùng `feature_metadata`/missing flags để tránh coi thiếu dữ liệu là tín hiệu trung lập.

### P2 - PerformanceWarning: DataFrame fragmentation

Test pass nhưng `AlternativeFeatureBuilder` phát nhiều warning do insert từng cột vào DataFrame. Với dữ liệu lớn, cách này có thể chậm và tốn bộ nhớ.

Nên gom generated columns vào dict/DataFrame phụ rồi `pd.concat(axis=1)` một lần.

### P2 - Một số derived metric vẫn placeholder

`defi_liquidity_score` đang để `None` với comment cần change 1d/7d. `large_tx_proxy_score`, `options_iv_rank`, `options_skew` cũng chưa được tính trong normalize hiện tại. Không phải lỗi nếu được thiết kế là optional, nhưng nên ghi rõ contract để downstream không kỳ vọng nhầm.

## Đề Xuất Ưu Tiên

1. **Sửa `load_frame()` cho CSV**  
   Di chuyển nhánh `.csv` ra ngang hàng với `.json` và thêm test trực tiếp cho `scripts/build_alternative_features.py`.

2. **Thêm raw-store aggregator cho feature build**  
   Cho `build_alternative_features.py` nhận `--input data/raw_alternative --input-format raw-store` hoặc thêm script `scripts/build_alternative_history.py` để gộp `alternative_*.json` thành DataFrame lịch sử trước khi build features.

3. **Đổi Phase 8 pipeline sang dùng lịch sử**  
   `run_phase8_pipeline.py` nên build từ raw-store/history table thay vì latest snapshot. Có thể giới hạn window rolling gần nhất nếu cần tốc độ.

4. **Thêm quality gate cho feature output**  
   Fail/warn nếu input rows < `max(zscore_window, momentum_window) + 1`, hoặc nếu tỷ lệ `alt_z_*` non-null quá thấp.

5. **Tối ưu `AlternativeFeatureBuilder`**  
   Tạo các cột generated trong dict và concat một lần để giảm fragmentation warning.

6. **Theo dõi low-coverage sources bằng dashboard riêng**  
   Tạo threshold alert theo coverage 24h/7d cho ETF, sentiment, whale/on-chain proxy.

## Trạng Thái Đề Xuất

| Hạng mục | Trạng thái |
|---|---|
| Collector orchestration | Tốt |
| Raw-store persistence | Tốt |
| Missing-data contract | Tốt |
| Feature metadata/provenance | Tốt |
| Quality dashboard/alerts | Tốt |
| Alternative feature math | Khá, cần tối ưu performance |
| Phase 8 integration | Cần sửa P0 |
| CSV input support | Cần sửa P0 |
| Training readiness | Chưa đạt nếu vẫn build từ one-row snapshot |

## Kết Luận

Alternative Data module đã vượt qua giai đoạn "collector demo" và có nền tảng vận hành khá chắc: thu thập đều, có raw history, metadata, quality checks và test coverage tương đối tốt. Điểm nghẽn lớn nhất hiện không nằm ở collector mà nằm ở **cách đưa dữ liệu vào feature engineering**.

Ưu tiên tiếp theo nên là sửa CSV loader và chuyển Phase 8 build từ latest snapshot sang chuỗi lịch sử trong `data/raw_alternative/`. Sau hai bước này, module mới thật sự phát huy được các feature rolling/momentum đã được thiết kế.
