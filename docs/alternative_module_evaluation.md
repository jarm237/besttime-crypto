# Đánh Giá Module Đặc Trưng Thay Thế (Alternative Module Evaluation)

Bản đánh giá này phân tích chi tiết kiến trúc hiện tại của **Alternative Features Module** trong Phase 8 Feature Engineering pipeline, chỉ ra các điểm mạnh, lỗi logic/cú pháp nghiêm trọng đang tồn tại, và đề xuất giải pháp khắc phục.

---

## 1. Tổng Quan Kiến Trúc & Vai Trò

Module alternative data chịu trách nhiệm xử lý các nguồn dữ liệu thay thế (alternative data) bao gồm:
*   **On-chain**: Whale score, stablecoin supply, TVL, active addresses, hashrate.
*   **Macro / Market**: DXY, VIX, US10Y, Gold, Options IV, IV Skew.
*   **Sentiment**: Sentiment score (Glassnode/Alternative.me), social sentiment (Reddit/Google Trends).
*   **Trading state**: Funding rate, Open Interest, Orderbook imbalance, Liquidity pressure.

`AlternativeFeatureBuilder` ([alternative_features.py](file:///d:/Workspaces/Vọc%20vạch/btc_scraper/feature_engineering/alternative_features.py)) tự động mở rộng 24 chỉ số gốc này thành **100 đặc trưng đầu vào** cho ML Model thông qua việc tính toán:
1.  **Z-Score** biến động (`alt_z_*`).
2.  **Momentum** thay đổi phần trăm (`alt_mom_*`).
3.  **Difference** chênh lệch tuyệt đối (`alt_chg_*`).
4.  **Rank** phân hạng tương đối (`alt_rank_*`).
5.  **Composite indicators**: Các điểm số tổng hợp về Macro Stress, Onchain Strength, Sentiment Spread, và Liquidity Risk.

---

## 2. Điểm Mạnh (Strengths)

1.  **Thiết kế Đầu Vào Sẵn Sàng Cho Mô Hình (Model-Ready)**: Cách tiếp cận chuẩn hóa qua Z-Score và Rank giúp phân phối dữ liệu ổn định hơn, triệt tiêu ảnh hưởng của các trị số tuyệt đối quá lớn (như TVL hàng tỷ USD so với Funding rate dạng số thập phân).
2.  **Đảm Bảo An Toàn Tránh Thiên Kiến Nhìn Trước (Point-in-Time Safety)**: Việc sắp xếp dữ liệu theo thời gian (`_temporal_sort`) trước khi thực hiện rolling windows giúp ngăn ngừa rò rỉ dữ liệu lịch sử (look-ahead bias).
3.  **Chỉ Số Tổng Hợp Có Ý Nghĩa Kinh Tế (Composite Indicators)**: Tạo ra các chỉ số stress/risk trực quan, gom cụm các chiều dữ liệu macro hoặc on-chain phức tạp thành 1 điểm số duy nhất để mô hình dễ hội tụ.

---

## 3. Các Lỗi Nghiêm Trọng Đang Tồn Tại (Critical Issues & Bugs)

Trong quá trình đánh giá mã nguồn và chạy thử nghiệm, chúng tôi phát hiện 2 lỗi nghiêm trọng làm giảm hiệu năng hoặc làm tê liệt một phần chức năng của module:

### 🔴 Lỗi 1: Code Nạp CSV Bị Khóa Không Thể Chạy Được (Unreachable Code)
Trong file [build_alternative_features.py](file:///d:/Workspaces/Vọc%20vạch/scripts/build_alternative_features.py#L41-L50), nhánh xử lý nạp file `.csv` bị viết thụt lề thụ động bên trong khối điều kiện `.json`, và nằm ngay sau lệnh `return`:

```python
41:     if suffix == ".json":
42:         raw = json.loads(path.read_text(encoding="utf-8"))
43:         if isinstance(raw, dict):
44:             raw = [raw]
45:         if not isinstance(raw, list):
46:             raise ValueError("JSON input must be a dict or a list of records")
47:         return pd.DataFrame(raw)
48:         if suffix == ".csv":           # <-- Lỗi thụt lề thụ động bên trong nhánh `.json`
49:             return smart_read_csv(path) # <-- Dòng code này hoàn toàn bị cô lập (Unreachable)
```
*   **Hậu quả**: Script luôn bắn lỗi `ValueError: Unsupported input format: .csv` nếu người dùng truyền file đầu vào định dạng CSV.

---

### 🔴 Lỗi 2: Trôi Mất Dữ Liệu Lịch Sử Khi Tính Z-Score (Single-Row Snapshot Execution)
Trong thiết kế chạy pipeline chính ([run_phase8_pipeline.py](file:///d:/Workspaces/Vọc%20vạch/scripts/run_phase8_pipeline.py#L204)):
*   Script gọi `build_alternative_features.py` với đầu vào duy nhất là `data/alternative_data.json`.
*   Tuy nhiên, `alternative_data.json` là một tệp chỉ chứa **1 dòng snapshot mới nhất** được ghi đè bởi collector.
*   Khi `AlternativeFeatureBuilder` xử lý DataFrame có 1 hàng dữ liệu duy nhất:
    *   Các phép tính rolling (`rolling(window=24, min_periods=2)`) không đủ chu kỳ để tính toán, trả về `NaN`.
    *   Sau đó, hệ thống gọi `.fillna(0.0)`, khiến tất cả các cột `alt_z_*`, `alt_mom_*`, `alt_chg_*` đều bị gán cứng về `0.0`.
*   **Hậu quả**: Triệt tiêu hoàn toàn giá trị của các đặc trưng động (rolling features), mô hình chỉ nhận được các giá trị tĩnh không có thông tin về xu hướng.

---

## 4. Kiểm Thử Thử Nghiệm Aggregation (Giải Pháp Tích Hợp Dữ Liệu)

Chúng tôi đã viết một scratch script để thu thập và hợp nhất toàn bộ dữ liệu lịch sử trong thư mục chứa log thô của collector [data/raw_alternative/](file:///d:/Workspaces/Vọc%20vạch/data/raw_alternative) (chứa 204 files tương đương 204 snapshots 15-phút):

*   **Kết quả chạy thử**:
    *   Nạp thành công 204 file JSON lịch sử $\rightarrow$ DataFrame kích thước `(204, 41)`.
    *   Sau khi chạy qua `AlternativeFeatureBuilder` $\rightarrow$ DataFrame kích thước `(204, 141)`.
    *   **Số lượng các trị số Z-Score hợp lệ (khác 0): 536 điểm**.
*   Điều này xác nhận: **Hệ thống xử lý toán học hoàn toàn chính xác, vấn đề nằm ở khâu gom dữ liệu đầu vào trước khi chạy builder.**

---

## 5. Đề Xuất Khắc Phục (Recommendations)

1.  **Sửa lỗi cú pháp load CSV**:
    Đưa điều kiện `if suffix == ".csv":` ra ngoài khối `.json` để nạp file CSV bình thường.
2.  **Bổ sung bước Aggregator trước khi build**:
    Thay vì nạp trực tiếp `alternative_data.json` đơn lẻ, hệ thống nên có một cơ chế quét toàn bộ tệp thô trong `data/raw_alternative/*.json`, gộp chúng lại theo thời gian rồi mới truyền vào `AlternativeFeatureBuilder`.
3.  **Tối ưu hóa DataFrame Fragmentation**:
    Trong quá trình build, gán trực tiếp nhiều cột mới vào DataFrame gây ra warning cảnh báo phân mảnh của Pandas. Nên chuyển sang tích lũy các cột mới vào một Dictionary sau đó `pd.concat` một lần duy nhất.

---

## 6. Cập Nhật Trạng Thái — Phase 7 Hoàn Thành (07/07/2026)

Các lỗi và gap đã được xử lý trong Phase 7 Alternative Data (Sprint 9):

| Hạng mục | Trạng thái | Ghi chú |
|:---|:---:|:---|
| Xóa `api.example.com` placeholders | ✅ | Sprint 9.1 — `validate_collectors_on_startup()` added |
| ETF collector thay bằng Parse.bot Farside | ✅ | `parsebot_farside_collector.py` |
| DefiLlama endpoint 404 → patched | ✅ | `stablecoins.llama.fi/stablecoins` |
| Reddit OAuth thay placeholder | ✅ | `reddit_collector.py` |
| Google Trends 429 spam → 6h cache | ✅ | LKV fallback + cadence fix |
| ETF flow lưu MongoDB | ✅ | `alternative_data_etf_flows` collection + upsert per `flow_date` |
| Scheduler tự động chạy ETF jobs | ✅ | `AlternativeDataScheduler._collect()` timezone-aware |
| Monitoring/Alert ETF stale/fail | ✅ | `check_etf_alert_conditions()` → Telegram |
| Dashboard hiển thị ETF status | ✅ | `print_dashboard()` ETF Flow Status block |
| Confidence weighting vào WorldState | ✅ | `effective_*` features trong `causal_context_bridge.py` |
| FRED 400 Bad Request | ✅ | Yahoo Finance REST fallback |
| yfinance thiếu | ✅ | REST fallback trong `yahoo_collector.py` và `macro_collector.py` |
| Causal Bridge `None` TypeError | ✅ | `_get_float()` safe helper |

**Test kết quả**: `pytest tests/test_phase7_sprint7.py` → **29/29 PASSED**
