# Báo cáo Quản trị Toàn diện Độ lệch Nhánh so với Main (Branch Delta Governance Disposition)

<!-- METADATA
{
  "source_commit": "f96c6b8b64516dd76d3af132dac316c5672e35be",
  "source_commit_tree": "da720a407ea580e5c67cc8f0035f8322d5f19586",
  "pre_g5_reconciliation_index_tree": "f992221b8ac2d9ec48c06bf1f3c84d33072ad47d",
  "observed_pre_reconciliation_tree": "f745fb75d02ecfd71aef0ae64613f4af8038620a",
  "observed_at_utc": "2026-10-12T01:00:42.5928305Z",
  "generated_at_utc": "2026-10-13T01:10:00Z",
  "generator": {
    "name": "g5-evidence-reconciliation",
    "version": "2.4",
    "mode": "manual-governed"
  },
  "input_hashes": {
    "execution_plan": "5897aefbc6a0a7228c659b901879d1bc0355855a647581fd63d811ed065c5b9c",
    "full_regression_junit": "82a19782f4f84cb0cd693d2252aa861e0572ae67239a978826d293c26a04ecb2"
  }
}
-->

**Repository**: `besttime-crypto`
**Nhánh hiện tại**: `model-coverage/22-symbol-v1-dev`
**Commit nền (HEAD)**: `f96c6b8b64516dd76d3af132dac316c5672e35be`
**Nhánh so sánh**: `main` (Nhánh hiện tại đi trước 98 commits, 0 commit đi sau)
**Ngày lập**: 2026-10-13T01:10:00Z
**Phân loại tài liệu**: `AUTHORITATIVE_GOVERNANCE_DISPOSITION`
**Trạng thái Gate G5**: `REVIEW / FAIL-CLOSED`
**Trạng thái Gate G6**: `BLOCKED` (Do Stop Condition #4: `truncated: true` trên phạm vi branch so sánh với main)
**Kích hoạt WP7 / WP8**: `FORBIDDEN` (Nghiêm cấm paper canary hoặc live trading)

---

## 1. Dữ liệu Đo kiểm GitNexus Toàn diện (Branch-vs-Main Scope)

Khi thực thi phân tích đồ thị quan hệ so sánh trực tiếp với `main`:
```bash
node .gitnexus/run.cjs detect-changes --repo besttime-crypto --scope compare --base-ref main
```

Kết quả trả về từ công cụ GitNexus `1.6.13-rc.103` ghi nhận:
- **Tổng số tệp thay đổi**: **622 files**
- **Tổng số symbols thay đổi**: **2.239 symbols** (Đếm ổn định qua các lần đo; danh sách hiển thị bị giới hạn ở 1.000 symbols)
- **Tổng số execution flows bị ảnh hưởng**: **281 execution flows** (điều chỉnh từ 259 do đồ thị process flows được phát hiện đầy đủ hơn qua re-walk)
- **Mức độ rủi ro tổng thể (Risk Level)**: **`CRITICAL`**
- **Trạng thái danh sách & Truncation**: **`truncated: true`** (`LISTING CAPPED: the changed-symbol list was capped at 1,000`)
- **Đánh giá Tính Tất định (Determinism Scope)**: Hash của 1.000 symbols được liệt kê là bất biến qua các lần chạy lặp lại, nhưng do danh sách bị cắt (`slice(0, 1000)`), kết quả đo này **chưa chứng minh full-set determinism cho toàn bộ 2.239 symbols**.

---

## 2. Phân loại Cấu trúc Độ lệch 98 Commit Tích lũy

Toàn bộ 622 tệp và khối symbol thay đổi tích lũy qua 98 commit được phân loại thành 5 khối chức năng chính:

| Phân hệ | Số tệp ước tính | Tác động Kiến trúc & Rủi ro | Biện pháp Bảo vệ Hiện hữu |
|---|---:|---|---|
| **1. ML Engine & Inference Coordinator** | ~45 files | Mở rộng coverage 22 symbols (MC8/MC9), chuẩn hóa inference interface, signal routing | Unit tests MC8/MC9, smoke inference không ghi evidence |
| **2. Runtime Ownership & Core Resilience** | ~30 files | Khóa PID native trên Windows (`_windows_pid_alive`), CircuitBreakerCollection MongoDB TLS, fallback SQLite | Test multi-restart idempotency, reservation recovery, degraded mode |
| **3. Market Data Collectors & Scrapers** | ~85 files | Bổ sung các pipeline thu thập ETF, Stablecoin, Options, Liquidation, Funding rates | Provenance audit tests, source manifests SHA-256 |
| **4. Unit, Integration & Regression Tests** | ~280 files | Bổ sung 2.069 test cases hermetic, negative tests bảo vệ H14 hard stop | Suite 2.069 tests cung cấp bằng chứng regression mạnh trong phạm vi đã thực thi |
| **5. Research Replay Framework (HMR v1–v4)** | ~182 files | Nghiên cứu dữ liệu lịch sử, parquet benchmarks, phân tích quantile/tail | Cố định đầu ra tmp_path, semantic parity với HEAD |

---

## 3. Đánh giá Bản RC & Ranh giới Nguyên nhân

- Bản cài đặt `gitnexus@1.6.13-rc.103` (đi kèm `@ladybugdb/core@0.21.1`) chỉ được phân loại là **“version-correlated mitigation”** (biện pháp giảm thiểu có tương quan phiên bản).
- Mặc dù kết quả đo kiểm không còn xuất hiện byte NUL và số lượng 2.239 symbols ổn định qua các lần chạy, hiện **chưa đủ bằng chứng độc lập để khẳng định `@ladybugdb/core 0.21.1` đã sửa chính xác root cause** bên trong native memory alignment/allocator.

---

## 4. Kết luận Quản trị và Điều kiện Dừng (Stop Conditions)

1. **Gate G5 Giữ ở `REVIEW / FAIL-CLOSED`**:
   - Mặc dù các mâu thuẫn dữ liệu cơ bản đã được đối chiếu, việc xuất hiện `truncated: true` trên phạm vi toàn nhánh và việc chưa chứng minh full-set determinism cho toàn bộ 2.239 symbols yêu cầu G5 phải tiếp tục duy trì ở trạng thái `REVIEW / FAIL-CLOSED`.
2. **Gate G6 Tiếp tục `BLOCKED`**:
   - Căn cứ theo **Stop Condition #4 (mục 8, dòng 522 của NEXT_STEP_EXECUTION_PLAN_2026-09-22.md)**:
     > “Dừng ngay work package hiện tại và không chuyển gate nếu... GitNexus trả `risk: UNKNOWN`, `partial` hoặc `truncated` cho critical boundary.”
   - Vì phân tích so sánh nhánh trả về `truncated: true`, tài liệu quản trị này **không tự miễn trừ** điều kiện dừng nói trên. Gate G6 tiếp tục bị khóa `BLOCKED`.
3. **Khóa Toàn diện WP7 & WP8**:
   - `WP7 (Paper Canary Activation)`: **`FORBIDDEN`**
   - `WP8 (P8 Economics Sample)`: **`FORBIDDEN`**
   - Không được phép khởi động bất kỳ tiến trình runtime canary hay live trading nào.
