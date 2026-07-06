# So sánh Source Code vs Implementation Plans — Phase 7 (CẬP NHẬT)

**Nguồn đánh giá:**
- [Phase7_Alternative_Data_Implementation_Plan.md](file:///d:/Workspaces/Vọc vạch/Phase7_Alternative_Data_Implementation_Plan.md)
- [Phase7_Alternative_Data_Implementation_Plan_UPDATED.md](file:///d:/Workspaces/Vọc vạch/Phase7_Alternative_Data_Implementation_Plan_UPDATED.md)
- [Phase7_Parsebot_Farside_ETF_Flow_Frequency_Improvement_Plan.md](file:///d:/Workspaces/Vọc vạch/Phase7_Parsebot_Farside_ETF_Flow_Frequency_Improvement_Plan.md)

---

## A. Tổng quan mức độ hoàn thành

| Nhóm | Kế hoạch gốc | Kế hoạch UPDATED | ETF Frequency Plan |
|:---|:---:|:---:|:---:|
| Foundation: collector_base, world_state, causal bridge | ✅ | ✅ | ✅ |
| Sprint 2-4: Collectors (Binance, FRED, Yahoo, DeFiLlama, Glassnode, Reddit, Trends) | ✅ | ✅ | ✅ |
| Sprint 5-8: Normalization, Replay, Dashboard, Production | ✅ | ✅ | ✅ |
| Sprint 9.1: Loại bỏ `api.example.com` | ✅ | ✅ | ✅ |
| Sprint 9.2: ETF Flow Provider Chain + Parse.bot | ✅ | ✅ | ✅ |
| Sprint 9.3: DefiLlama stablecoin endpoint patch | ✅ | ✅ | - |
| Sprint 9.4: Reddit OAuth | ✅ | ✅ | - |
| Sprint 9.5: Google Trends cadence fix (6h cache) | ✅ | ✅ | - |
| Sprint 9.6: Confidence layer (effective features weight) | ✅ | ✅ | - |
| Phase A–D: ETF Frequency (Config, Collector, Jobs) | ✅ | - | ✅ |
| **Phase C (ETF): Storage vào DB/MongoDB** | ✅ | - | ✅ |
| **Phase E: ETF Scoring weight logic** | ✅ | - | ✅ |
| **Phase F: Monitoring/Alert ETF** | ✅ | - | ✅ |
| **§14: Dashboard ETF flow status** | ✅ | - | ✅ |

---

## B. Chi tiết từng checklist của ETF Frequency Plan (§16)

### Phase A — Config ✅ Hoàn thành
| Yêu cầu | Trạng thái | Giải pháp / File |
|:---|:---:|:---|
| Parse.bot config vào `.env` | ✅ | Định nghĩa `PARSEBOT_ENABLED=false`, `PARSEBOT_API_KEY`, `PARSEBOT_BASE_URL` trong [.env](file:///d:/Workspaces/Vọc vạch/.env) dòng 75-85. |
| Endpoint name config | ✅ | Cấu hình trong `.env` dòng 91-99. |
| Cron config | ✅ | Cấu hình trong `.env` dòng 108-110. |
| Supported symbols config | ✅ | Cấu hình trong `.env` dòng 120-122. |
| Fallback/data quality config | ✅ | Cấu hình trong `.env` dòng 141-145. |
| Cập nhật `.env.example` | ✅ | Cập nhật đầy đủ các trường tương tự trong [.env.example](file:///d:/Workspaces/Vọc vạch/.env.example) dòng 74-154. |

---

### Phase B — Collector ✅ Hoàn thành
| Yêu cầu | Trạng thái | Giải pháp / File |
|:---|:---:|:---|
| Tạo `ParsebotFarsideETFCollector` | ✅ | Khởi tạo hoàn chỉnh trong [parsebot_farside_collector.py](file:///d:/Workspaces/Vọc vạch/btc_scraper/collectors/parsebot_farside_collector.py). |
| `fetch(symbol, mode)` | ✅ | Triển khai logic fetch kèm retry, timeout và xử lý biệt lập từng symbol/mode. |
| Retry + timeout | ✅ | Tích hợp tham số `PARSEBOT_MAX_RETRIES` và `PARSEBOT_TIMEOUT_SECONDS` từ `.env`. |
| Endpoint resolver `get_parsebot_endpoint()` | ✅ | Tự động phân giải các endpoint của BTC, ETH, SOL, và FUND. |
| Unsupported symbol handling → status `"unsupported"` | ✅ | Trả về thông báo lỗi chất lượng và status `"unsupported"` thay vì crash. |
| Không dùng default fake data | ✅ | Trả về trạng thái thực tế `"failed"`, `"stale"`, `"missing"` và trả `None` thay vì số `0.0` giả khi `ETF_FLOW_ALLOW_DEFAULT_FAKE_DATA=false`. |

---

### Phase C — Storage ✅ Hoàn thành
| Yêu cầu | Trạng thái | Giải pháp / File |
|:---|:---:|:---|
| Collection `alternative_data_etf_flows` (MongoDB) | ✅ | Khai báo và kết nối thành công trong [db.py](file:///d:/Workspaces/Vọc vạch/btc_scraper/core/db.py#L22). |
| Collection `alternative_data_fetch_logs` | ✅ | Khai báo và kết nối thành công trong `db.py` dòng 23. |
| Index theo `source + symbol + flow_date` | ✅ | Tạo index duy nhất trong `db.py` dòng 39-41 giúp tối ưu hóa truy vấn. |
| Upsert theo ngày | ✅ | Hàm `_parse_and_save_records_to_db` trong `parsebot_farside_collector.py` tự động bóc tách từng ngày và thực hiện `update_one` (upsert). |
| Lưu `raw response` để debug | ✅ | Lưu trữ toàn bộ object thô trong cột `raw` của document MongoDB. |
| Lưu `data_quality` / `status` | ✅ | Lưu đầy đủ các chỉ số chất lượng dữ liệu để phục vụ cho scoring & monitoring. |

---

### Phase D — Scheduler ✅ Hoàn thành
| Yêu cầu | Trạng thái | Giải pháp / File |
|:---|:---:|:---|
| Job `recent`: 06:00, 07:00, 08:00, 09:00 VN | ✅ | Định nghĩa CLI trong [fetch_parsebot_etf_jobs.py](file:///d:/Workspaces/Vọc vạch/scripts/fetch_parsebot_etf_jobs.py). |
| Job `all`: 09:30 VN | ✅ | CLI tích hợp `--job all`. |
| Job `fund_info`: 10:00 VN | ✅ | CLI tích hợp `--job fund`. |
| Không gọi Parse.bot trong scan 15m | ✅ | [etf_collector.py](file:///d:/Workspaces/Vọc vạch/btc_scraper/collectors/etf_collector.py) sẽ đọc từ cache JSON nếu `PARSEBOT_ENABLED=true`. |
| Tích hợp cron tự động (scheduler thực tế) | ✅ | Tích hợp timezone-aware check (`Asia/Ho_Chi_Minh`) chạy tự động trong hàm `_collect` của [alternative_scheduler.py](file:///d:/Workspaces/Vọc vạch/btc_scraper/collectors/alternative_scheduler.py#L148-L188). |

---

### Phase E — Scoring ✅ Hoàn thành
| Yêu cầu | Trạng thái | Giải pháp / File |
|:---|:---:|:---|
| Load ETF flow từ cache/DB | ✅ | Sử dụng `get_etf_feature_for_scoring()` để đọc cache. |
| `status != ok` → `weight = 0` | ✅ | Đã loại bỏ trọng số khi dữ liệu không ở trạng thái `"ok"`. |
| `stale` → `weight = 0` | ✅ | Kiểm tra freshness và vô hiệu hóa weight khi quá 36 giờ. |
| `unsupported` → `weight = 0` | ✅ | Check symbol hỗ trợ trong biến `SUPPORTED_ETF_FLOW_SYMBOLS`. |
| `ok` → `compute_etf_flow_score()` | ✅ | Chuyển đổi lượng USD ròng (triệu USD) sang điểm score từ `[-1.0, 1.0]` theo §13. |
| Log rõ ETF feature được dùng hay bị skip | ✅ | Ghi nhật ký cấp `INFO`/`WARNING` chi tiết ở từng chu kỳ quét. |

---

### Phase F — Monitoring/Alert ✅ Hoàn thành
| Yêu cầu | Trạng thái | Giải pháp / File |
|:---|:---:|:---|
| Log endpoint fail theo `symbol/mode` | ✅ | Ghi nhật ký chi tiết vào collection `alternative_data_fetch_logs`. |
| Alert nếu `failed > 2 ngày liên tiếp` | ✅ | Thêm hàm `check_etf_alert_conditions()` trong `CollectorHealthMonitor` tại [alternative_quality.py](file:///d:/Workspaces/Vọc vạch/btc_scraper/collectors/alternative_quality.py) quét lịch sử MongoDB để đếm số lần lỗi liên tục quá 48 giờ. |
| Alert nếu dữ liệu stale > 36h | ✅ | Kiểm tra `fetched_at` của dòng ETF Flow mới nhất trong DB và phát cảnh báo nếu vượt quá 36 giờ. |
| Alert nếu gặp lỗi 401/403 | ✅ | Kiểm tra lỗi xác thực từ Parse.bot trong vòng 24 giờ qua và đẩy cảnh báo tức thì. |
| Dashboard hiển thị trạng thái ETF | ✅ | Cập nhật `print_dashboard()` trong `alternative_quality.py` hiển thị chi tiết cho BTC, ETH, SOL cùng chất lượng dữ liệu. |

---

## C. Sprint 9.6 — Confidence Layer (UPDATED Plan §9.6) ✅ Hoàn thành

| Yêu cầu | Trạng thái | Giải pháp / File |
|:---|:---:|:---|
| `etf_flow_confidence` trong payload | ✅ | Trích xuất và normalization trong `alternative_data.py` dòng 389. |
| `search_interest_confidence` trong Google Trends | ✅ | Gán độ tin cậy `0.35` cho nguồn không chính thống Google Trends. |
| Causal engine dùng `effective_value` | ✅ | [causal_context_bridge.py](file:///d:/Workspaces/Vọc vạch/btc_scraper/ml_engine/causal_context_bridge.py) đã chuyển sang nạp các đặc trưng đã nhân trọng số độ tin cậy (`effective_stablecoin_momentum`, `effective_etf_momentum`, `effective_risk_on_score`) vào WorldState, ngăn các tin cũ/không tin cậy chi phối quyết định. |

---

## D. Phần đã được triển khai ngoài kế hoạch (Bonus)

* **FRED 400 Bad Request Fix:** Tự động fallback sang Yahoo Finance REST API để lấy chỉ số `^TNX` khi key là `"demo"` bị FRED chặn.
* **yfinance REST Fallback:** Tự động lấy dữ liệu qua REST API khi thiếu thư viện `yfinance` giúp các collector DXY, VIX, Gold hoạt động độc lập và ổn định.
* **Causal Context Bridge Hardening:** Dùng hàm `_get_float` an toàn để chuyển đổi kiểu dữ liệu, ngăn crash do `TypeError` khi một số trường dữ liệu thay thế trả về `None`.

---

## E. Kết luận
Mã nguồn hiện tại đã **đáp ứng 100% tất cả các yêu cầu, checklist, sơ đồ luồng và tiêu chí chất lượng** được quy định trong cả 3 văn bản kế hoạch triển khai của Phase 7. Các khoảng trống về MongoDB Storage, Tự động hóa Lên lịch, Giám sát/Cảnh báo chất lượng và Causal Weighting đều đã được triển khai hoàn tất và kiểm thử thành công.
