# Báo cáo khắc phục dữ liệu Alternative Data bị thay thế bằng 0

**Ngày thực hiện:** 2026-07-13  
**Phạm vi:** Alternative-data collectors, normalization contract, feature metadata và regression tests  
**Nguyên tắc áp dụng:** `missing_data != 0.0`

## 1. Tổng quan

Pipeline trước đây có thể ghi `0.0` và đánh dấu `available: true` cho một số feature dù collector không lấy hoặc không parse được dữ liệu. Các trường bị ảnh hưởng rõ nhất gồm:

- `open_interest`
- `stablecoin_supply`
- `stablecoin_supply_total`
- `options_iv`
- `iv_skew`
- `sentiment_score`
- `social_sentiment`

Đợt khắc phục này thay đổi cả collector và normalization boundary. Mục tiêu là ngăn lỗi tương tự tái xuất hiện ngay cả khi một collector cũ vẫn vô tình trả fallback bằng 0.

## 2. Nguyên nhân gốc đã xác nhận

### Binance

- Collector khởi tạo `open_interest` bằng `0.0`.
- Sử dụng endpoint lịch sử OI thay vì endpoint current open interest.
- Khi response không đúng schema hoặc không có dữ liệu, giá trị mặc định vẫn được giữ nguyên.
- `orderbook_imbalance` không được lấy từ order book thật.
- Phần trăm thay đổi OI từng bị ghi nhầm vào trường `orderbook_imbalance`.

### DefiLlama

- Hàm chuyển kiểu trả `0.0` cho mọi lỗi parse.
- Parser không xử lý đúng schema `peggedAssets[].circulating.peggedUSD`.
- Fallback chart có nguy cơ cộng nhiều observation lịch sử thay vì lấy observation mới nhất.
- Các expression dạng `float(value or 0.0)` biến missing thành dữ liệu zero.

### Deribit

- Collector chọn phần tử cuối của book summary mà không bảo đảm đó là BTC option hợp lệ.
- `mark_iv` của Deribit có thể dùng đơn vị phần trăm nhưng chưa được chuẩn hóa sang decimal.
- `iv_skew` trước đây thực chất là best ask IV trừ best bid IV, không phải put-call volatility skew.
- Exception path trả `0.0` cho cả IV và skew.

### Google Trends và Reddit

- Collector bị tắt, rate-limited hoặc không có mẫu vẫn giữ neutral fallback `0.0`.
- Aggregate collector chưa ghi source status riêng cho Google Trends và Reddit.
- Không có điều kiện minimum sample để xác nhận zero là sentiment trung tính quan sát được.

### Metadata và normalization

- Availability chủ yếu dựa trên điều kiện `value is not None`.
- Không có field-level status để phân biệt `invalid`, `missing` và `source_error`.
- Không bắt buộc `sample_count` đối với các feature có thể bằng chính xác 0.

## 3. Các thay đổi đã thực hiện

### 3.1 Binance Futures

File: `btc_scraper/collectors/binance_collector.py`

- Funding rate được truy vấn theo đúng symbol:

  `GET /fapi/v1/fundingRate?symbol=BTCUSDT&limit=1`

- Current OI được truy vấn từ:

  `GET /fapi/v1/openInterest?symbol=BTCUSDT`

- OI được validate bằng điều kiện `open_interest > 0`.
- OI bằng 0 hoặc không parse được sẽ trả:

  - value: `null`
  - status: `invalid`
  - reason: `zero_or_missing_open_interest`

- Order-book imbalance được tính từ Futures depth:

  `(bid_volume - ask_volume) / (bid_volume + ask_volume)`

- Ghi nhận số lượng depth samples.
- Funding, OI và imbalance không còn được khởi tạo bằng `0.0`.

### 3.2 Open-interest pressure

File: `btc_scraper/collectors/alternative_data.py`

- Phần trăm thay đổi OI nay được ghi đúng vào `open_interest_pressure`:

  `(OI_now - OI_previous) / OI_previous`

- Không còn ghi đè `orderbook_imbalance` bằng OI change.
- Không tính pressure nếu previous OI không tồn tại hoặc không dương.

### 3.3 DefiLlama stablecoin supply

File: `btc_scraper/collectors/defillama_collector.py`

- Hàm parse số trả `None` khi dữ liệu không hợp lệ.
- Hỗ trợ các response schema:

  - `total`
  - `data.totalStablecoins.value`
  - `peggedAssets[].circulating.peggedUSD`
  - latest row của `stablecoincharts/all`

- Không cộng dồn các row lịch sử của stablecoin chart.
- `stablecoin_supply` và `stablecoin_supply_total` chỉ available khi tổng supply dương.
- Bổ sung `stablecoin_sample_count` và raw supply.
- TVL, chain TVL và protocol TVL cũng giữ `None` khi không có dữ liệu hợp lệ.

### 3.4 Deribit DVOL và IV skew

File: `btc_scraper/collectors/deribit_collector.py`

- `options_iv` ưu tiên Deribit volatility index endpoint.
- DVOL raw theo phần trăm được chuẩn hóa:

  `normalized_iv = raw_iv / 100.0`

- Payload lưu:

  - `raw_options_iv`
  - `options_iv`
  - `options_iv_unit: "decimal"`
  - `options_iv_sample_count`

- Có fallback sử dụng median `mark_iv` của các BTC option hợp lệ.
- `iv_skew` được tính theo:

  `IV_put_25d - IV_call_25d`

- Put và call được ghép theo cùng expiry và delta gần 0.25.
- Khi book summary không có greeks, delta được ước lượng bằng Black-Scholes từ underlying price, strike, expiry và mark IV.
- Không còn sử dụng ask-bid IV spread làm `iv_skew`.
- Thiếu put/call samples sẽ trả `null` với reason `insufficient_25d_put_call_samples`.

### 3.5 Google Trends

File: `btc_scraper/collectors/google_trends_collector.py`

- Collector disabled, thiếu samples, rate-limited hoặc lỗi không còn trả `0.0`.
- Bổ sung:

  - `sample_count`
  - `raw_sentiment_score`
  - field-level status và reason

- Cache lưu cả raw value và sample count.

### 3.6 Reddit sentiment

File: `btc_scraper/collectors/reddit_collector.py`

- Collector disabled hoặc OAuth collection không có dữ liệu trả `null`.
- Chỉ công bố sentiment khi đủ số mẫu.
- Ngưỡng mặc định là 10 bài viết, có thể cấu hình bằng:

  `REDDIT_MIN_SENTIMENT_SAMPLES`

- Thiếu mẫu trả reason `collector_disabled_or_no_samples`.

### 3.7 Missing-data contract

File: `btc_scraper/collectors/alternative_data.py`

Các feature bắt buộc dương dưới đây bị chuyển thành missing nếu giá trị `<= 0`:

- `open_interest`
- `stablecoin_supply`
- `stablecoin_supply_total`
- `options_iv`

Các feature có thể bằng 0 thật chỉ được giữ zero khi có `sample_count > 0`:

- `iv_skew`
- `sentiment_score`
- `social_sentiment`
- `orderbook_imbalance`

Nếu không có evidence, zero được chuyển thành `null` và `available: false`.

### 3.8 Feature metadata

Files:

- `btc_scraper/collectors/alternative_data.py`
- `btc_scraper/collectors/feature_source_registry.py`
- `btc_scraper/collectors/alternative_quality.py`

Metadata của mỗi feature nay có thêm:

- `available`
- `status`
- `reason`
- `source`
- `observed_at`
- `raw_value`
- `sample_count`
- `confidence`
- `age_seconds`
- `is_stale`

Các status `error`, `skipped`, `missing`, `invalid`, `fallback` và `rate_limited` không được xem là available.

Bounds của các trường bắt buộc dương đã được đổi từ 0 thành `1e-12`.

## 4. Kết quả smoke test API thực tế

Smoke test được chạy trực tiếp, không ghi output file:

| Source | Feature | Giá trị quan sát |
| --- | --- | ---: |
| Binance | `funding_rate` | `1.521e-05` |
| Binance | `open_interest` | `100050.564` |
| Binance | `orderbook_imbalance` | `0.3255821549` |
| DefiLlama | `stablecoin_supply` | `311620444822.39166` |
| Deribit | raw DVOL | `37.77` |
| Deribit | normalized `options_iv` | `0.3777` |
| Deribit | `iv_skew` | `0.0540` |

Ba collector đều trả `status: success` và không còn field-level error trong lần kiểm tra này.

Các giá trị trên là observation tại thời điểm smoke test, không phải hằng số hoặc fixture.

## 5. Kiểm thử

Các nhóm test đã chạy:

- Alternative-data normalization và snapshot
- Phase 2 data-quality metadata
- Binance và DefiLlama collector parsing
- Deribit IV/DVOL parsing
- Alternative feature engineering
- Regime feature consumers
- Phase 7 downstream tests

Kết quả:

- 63 test liên quan pass qua hai test suite.
- Lượt regression cuối: 32 test pass.
- `git diff --check` pass.
- Python compile check pass.

Các warning còn lại là warning có sẵn về pandas DataFrame fragmentation và một deprecation warning của `datetime.utcnow()`; không liên quan đến thay đổi collector.

## 6. File code và test đã thay đổi

### Code

- `btc_scraper/collectors/alternative_data.py`
- `btc_scraper/collectors/alternative_quality.py`
- `btc_scraper/collectors/binance_collector.py`
- `btc_scraper/collectors/defillama_collector.py`
- `btc_scraper/collectors/deribit_collector.py`
- `btc_scraper/collectors/feature_source_registry.py`
- `btc_scraper/collectors/google_trends_collector.py`
- `btc_scraper/collectors/reddit_collector.py`

### Tests

- `tests/test_alternative_data.py`
- `tests/test_phase2_data_quality.py`
- `tests/test_phase7_sprint2.py`
- `tests/test_phase7_sprint3.py`

## 7. Phạm vi chưa thực hiện

Đợt sửa này tập trung vào các lỗi zero fallback và ba nguồn ưu tiên Binance, DefiLlama, Deribit. Các hạng mục sau chưa được bổ sung trong đợt này:

- Farside ETF flow parser/cache mới
- Mempool.space whale hoặc large-transaction proxy
- Exchange wallet registry và exchange netflow
- Bitcoin full-node/indexer cho active addresses
- Defi liquidity composite hoàn chỉnh
- Thay đổi default của `AlternativeLayer` trong world-state

Các feature chưa có nguồn đáng tin cậy vẫn nên tiếp tục giữ `null`.

## 8. Hành vi kỳ vọng sau triển khai

Ví dụ missing:

```json
{
  "value": null,
  "available": false,
  "status": "missing",
  "reason": "collector_disabled_or_no_samples",
  "raw_value": null,
  "sample_count": 0
}
```

Ví dụ neutral zero có evidence:

```json
{
  "value": 0.0,
  "available": true,
  "status": "available",
  "raw_value": 0.0,
  "sample_count": 25,
  "observed_at": "2026-07-13T00:00:00+00:00"
}
```

Snapshot mới sẽ áp dụng contract này ở lần collection tiếp theo.
