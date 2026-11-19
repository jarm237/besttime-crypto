# Track A v1: Multi-Horizon Trend Following Economic Report & Replay Evidence

**Author:** Besttime-Crypto Quantitative Strategy & Economic Governance  
**Date:** 2026-11-19  
**Repository:** `https://github.com/jarm237/besttime-crypto`  
**Branch:** `research/s5-p0-economic-opportunity`  
**Reference Commit:** `f101dfe7ad6eaaeb6ad348942332ab5937545a7e`  
**Execution Config:** [track_a_v1_replay_config.json](file:///d:/Workspaces/besttime-crypto/research/track_a/v1/track_a_v1_replay_config.json)  
**Economic Evidence:** [track_a_v1_economic_evidence.json](file:///d:/Workspaces/besttime-crypto/research/track_a/v1/track_a_v1_economic_evidence.json)  
**Decision Ledger:** [track_a_v1_decision_ledger.csv](file:///d:/Workspaces/besttime-crypto/research/track_a/v1/track_a_v1_decision_ledger.csv)  

---

## 1. Git Preflight & System Identification

- **Working Branch:** `research/s5-p0-economic-opportunity`
- **Starting Lineage Commit:** `f101dfe7ad6eaaeb6ad348942332ab5937545a7e` (feat(s5): correct economic replay integrity defects and regenerate S5-P0B evidence)
- **Worktree State:** Clean (các thay đổi mới chỉ bao gồm các module nghiên cứu Track A và dữ liệu kiểm toán bổ sung).

---

## 2. Data Source Provenance & Integrity

Cuộc kiểm toán và tái lập kinh tế sử dụng 100% dữ liệu gốc đã được xác minh tính xác thực độc lập:
1. **Canonical Binance Spot 1h Archives (`2017-08` → `2025-12`):**
   - 365 archives hàng tháng cho BTC, ETH, SOL, BNB trong `data/historical/neural_n1/raw/binance_spot_klines_1h/`.
   - 100% archives khớp chính xác chữ ký SHA-256 từ file sidecar `.sha256`.
2. **Fresh Training Data 1h & 1d (`2026-01` → `2026-06`):**
   - 42 file CSV hàng tháng trong `data/fresh_training_data_2023_2026/`.
3. **Targeted Backfill Holdout Spot Archives (`2026-07` → `2026-11-18`):**
   - 88 archives nén trực tiếp từ Binance Public Vision (`data.binance.vision`) với chữ ký SHA-256 đối chiếu độc lập từ `.CHECKSUM` chính thức.
   - Không chứa bất kỳ dữ liệu nội suy hay nến tổng hợp nhân tạo nào (Zero synthetic candles).

---

## 3. Backfill Summary

Để đảm bảo so sánh công bằng (matched benchmark) trên toàn bộ vũ trụ 4 tài sản (BTC, ETH, SOL, BNB) đến thời điểm nến ngày hoàn tất mới nhất trên sàn:
- Đã backfill thành công **62 archives** nến 1h từ Binance Vision:
  - `SOLUSDT`: 4 monthly archives (`2026-07` đến `2026-10`) + 18 daily archives (`2026-11-01` đến `2026-11-18`).
  - `BNBUSDT`: 4 monthly archives (`2026-07` đến `2026-10`) + 18 daily archives (`2026-11-01` đến `2026-11-18`).
  - `BTCUSDT`: 9 daily archives (`2026-11-10` đến `2026-11-18`).
  - `ETHUSDT`: 9 daily archives (`2026-11-10` đến `2026-11-18`).
- 100% file tải về đã vượt qua kiểm tra mã băm SHA-256 và được lưu trữ nguyên trạng trong `data/historical/raw/holdout_spot/`.

---

## 4. Replay Window & Valid Interval

- **Replay Start:** `2022-01-01 00:00:00 UTC`
- **Replay End:** `2026-11-18 23:00:00 UTC`
- **Tổng thời gian mô phỏng:** 1,784 ngày (4 năm, 10 tháng, 18 ngày liên tục).
- **First Valid Execution:** `2022-01-01 01:00:00 UTC`
- **Latest Valid Execution:** `2026-11-18 01:00:00 UTC`

---

## 5. Number of Validated Candles

- **BTCUSDT 1h bars:** 51,538 nến nạp thực tế (độ bao phủ 99.97% từ `2021-01-01 00:00 UTC` đến `2026-11-18 23:00 UTC`).
- **BTCUSDT 1d daily candles:** 2,148 nến ngày hoàn tất chuẩn UTC.
- **Warmup:** 90 nến ngày hoàn tất trong năm 2021 (`2021-10-03` đến `2021-12-31`) cung cấp đủ điều kiện nhân quả cho Donchian 20, 55, 90 ngày tại thời điểm mở màn `2022-01-01`.

---

## 6. Execution & Cost Semantics

- **Decision Schedule:** 00:00 UTC hàng ngày, dựa trên nến ngày $D-1$ vừa đóng lúc 23:59:59 UTC.
- **Execution Proxy:** Giá mở cửa nến 1h lúc 01:00 UTC ngày $D$ (`open` price). Tuyệt đối không giao dịch tại giá đóng cửa của nến tính tín hiệu (no close-to-close lookahead).
- **Portfolio Accounting:** Áp dụng bộ giải bảo toàn vốn chính xác `solve_post_fee_equity`:
  $$V_{\text{post}} = V_{\text{pre}} - c \sum_i |w_i V_{\text{post}} - N_i|$$
  Phí được trừ trực tiếp vào vốn trước khi phân bổ số lượng vị thế, bảo đảm $V_{\text{post}} + \text{fee} \equiv V_{\text{pre}}$.

---

## 7. Primary Scorecard (30 bps One-Way All-In Cost)

Bảng so sánh đối đầu trên cùng cửa sổ `2022-01-01` → `2026-11-18` ở mức chi phí cơ sở **30 bps (0.0030)**:

| Chỉ tiêu kinh tế | Track A v1 (Donchian Step) | S5 Daily Trend BTC | BTC Buy & Hold | Cash (USDT) |
|---|---|---|---|---|
| **Vốn ban đầu (Initial Capital)** | $10,000.00 | $10,000.00 | $10,000.00 | $10,000.00 |
| **Giá trị cuối kỳ (Final Equity)** | **$15,419.98** | $8,916.77 | $13,477.24 | $10,000.00 |
| **Lợi nhuận ròng (Net PnL)** | **+$5,419.98** | -$1,083.23 | +$3,477.24 | $0.00 |
| **Lợi nhuận lũy kế (Cumulative Return)** | **+54.20%** | -10.83% | +34.77% | 0.00% |
| **CAGR ròng sau phí** | **+9.28%** | **-2.32%** | +6.30% | 0.00% |
| **Sụt giảm vốn tối đa (Max Drawdown)** | **-42.08%** | -49.39% | **-67.38%** | 0.00% |
| **Hệ số Calmar (CAGR / \|MaxDD\|)** | **0.22** | **-0.05** | 0.09 | 0.00 |
| **Hệ số Sharpe (Annualized)** | **0.44** | 0.09 | 0.37 | 0.00 |
| **Tần suất quay vòng vốn (Turnover/năm)** | **4.75x** | **66.79x** | 0.16x | 0.00x |
| **Tổng phí giao dịch đã trả** | **$1,047.28** | **$9,551.87** | $29.91 | $0.00 |
| **Tỷ trọng BTC bình quân** | 55.77% | 50.15% | 100.00% | 0.00% |
| **Tỷ trọng Tiền mặt bình quân** | 44.23% | 49.85% | 0.00% | 100.00% |
| **Số lần giao dịch (Trades)** | 67 | 450 | 1 | 0 |
| **Tháng tồi tệ nhất (Worst Month)** | -16.48% | -18.73% | -37.89% | 0.00% |

---

## 8. Matched S5 Baseline Scorecard Analysis

Chiến lược đối chiếu cơ sở `S5_DAILY_TREND_BTC` bộc lộ sự sụp đổ nghiêm trọng về mặt kinh tế khi đối mặt với chi phí thực tế:
- **Tần suất giao dịch quá mức (Hyper-churning):** Turnover lên tới **66.79x/năm** (450 lần đảo vị thế nhị phân 0/100%).
- **Bào mòn vốn do phí (Fee Drag):** Ở mức phí 30 bps, S5 Daily đã chi trả tới **$9,551.87 tiền phí** (chiếm 95.5% tổng số vốn ban đầu $10,000)!
- **Hệ quả PnL:** S5 Daily bị âm vốn ròng (**CAGR = -2.32%**, kết thúc tại $8,916.77), biến một tín hiệu có vẻ có lãi gộp thành một chiến lược lỗ nặng sau phí.

**Track A v1 khắc phục triệt để khiếm khuyết này:**
- Giảm turnover từ **66.79x xuống 4.75x** (giảm 92.9% khối lượng quay vòng không cần thiết).
- Giảm tổng phí từ **$9,551.87 xuống $1,047.28** (tiết kiệm gần $8,500 tiền phí).
- Chuyển hóa kết quả từ lỗ (**-2.32% CAGR**) thành lãi thực dương vững chắc (**+9.28% CAGR**).

---

## 9. Annual and Regime Breakdowns (At 30 bps)

### 9.1. Calendar Year Breakdown

| Năm | Track A v1 Return | Track A v1 MaxDD | S5 Daily Return | S5 Daily MaxDD | BTC B&H Return | BTC B&H MaxDD |
|---|---|---|---|---|---|---|
| **2022 (Crypto Winter)** | **-25.01%** | **-25.73%** | -35.00% | -41.60% | **-64.65%** | **-67.38%** |
| **2023 (Recovery)** | **+70.18%** | -21.03% | +63.39% | -19.55% | +155.80% | -21.74% |
| **2024 (ETF Bull)** | **+78.79%** | -30.69% | +20.34% | -34.39% | +120.31% | -32.31% |
| **2025 (Chop/Consolidation)** | **-14.32%** | -27.54% | -33.22% | -38.61% | -7.15% | -34.76% |
| **2026 YTD (Late Cycle)** | **-22.14%** | -23.40% | +3.81% | -17.69% | -28.18% | -40.31% |
| **Full Period (2022–2026)** | **+54.20%** | **-42.08%** | **-10.83%** | **-49.39%** | **+34.77%** | **-67.38%** |

### 9.2. Market Regime Diagnostic Breakdown

1. **BEAR_DELEVERAGING_2022 (LUNA, 3AC, FTX collapse):**
   - Track A: **-25.01%** (MaxDD -25.73%)
   - BTC B&H: **-64.65%** (MaxDD -67.38%)
   - *Đánh giá:* Track A bảo toàn vốn vượt trội, cắt giảm gần 40% tổn thất của thị trường.
2. **EARLY_RECOVERY_2023 (Banking crisis & bottom formation):**
   - Track A: **+17.33%** | S5 Daily: +22.90% | BTC B&H: +64.28%
3. **STRONG_UPTREND_ETF (ETF excitement & breakout):**
   - Track A: **+134.92%** | S5 Daily: +55.13% | BTC B&H: +162.62%
   - *Đánh giá:* Track A nắm bắt trọn vẹn sóng tăng lớn nhờ phân bổ tỷ trọng bậc thang tăng dần lên 100% BTC, vượt xa S5 Daily (+134.9% vs +55.1%).
4. **SIDEWAYS_CHOP_2024 (Halving consolidation & range-bound):**
   - Track A: **-16.54%** | S5 Daily: -8.16% | BTC B&H: -1.21%
5. **POST_ELECTION_BULL (Nov 2024 – Jan 2025 rally):**
   - Track A: **+45.97%** | S5 Daily: +15.10% | BTC B&H: +45.97%
   - *Đánh giá:* Bắt kịp 100% đà tăng của BTC Buy & Hold trong khi S5 Daily bị lỡ sóng do whipsaw.
6. **MACRO_EXPANSION_CONSOLIDATION (2025–2026 drawdowns):**
   - Track A: **-38.56%** (MaxDD -38.84%) | S5 Daily: -31.70% (MaxDD -45.49%) | BTC B&H: -38.47% (MaxDD -53.74%)

---

## 10. Transaction Cost Stress Testing

Kiểm tra độ nhạy cảm của các chiến lược trên 4 kịch bản chi phí một chiều (One-Way All-In Fees):

| Chi phí (bps) | Track A CAGR | Track A MaxDD | Track A Final | Track A Fees | S5 Daily CAGR | S5 Daily Final | S5 Daily Fees | BTC B&H CAGR | BTC B&H Final |
|---|---|---|---|---|---|---|---|---|---|
| **12 bps (S5 Ref)** | +10.20% | -40.92% | $16,065.79 | $428.93 | +10.48% | $16,266.96 | $5,287.99 | +6.34% | $13,501.47 |
| **20 bps (Moderate)**| +9.79% | -41.44% | $15,775.49 | $707.40 | +4.60% | $12,452.68 | $7,602.40 | +6.33% | $13,490.69 |
| **30 bps (Primary)** | **+9.28%** | **-42.08%** | **$15,419.98** | **$1,047.28**| **-2.32%** | **$8,916.77** | **$9,551.87** | **+6.30%** | **$13,477.24** |
| **50 bps (Severe)**  | +8.26% | -43.35% | $14,732.81 | $1,700.45 | -14.81% | $4,571.87 | $11,460.38 | +6.26% | $13,450.42 |

**Quan sát then chốt:**
- Khi chi phí tăng từ 12 bps lên 50 bps, Track A chỉ giảm nhẹ CAGR từ 10.20% xuống 8.26% (vẫn giữ vững mức lợi nhuận dương mạnh mẽ).
- Trong khi đó, S5 Daily Trend BTC sụp đổ hoàn toàn từ +10.48% rơi thẳng xuống **-14.81% CAGR**, mất hơn một nửa tài sản do chi phí giao dịch.

---

## 11. Turnover and Fee Drag Evaluation

- **Khối lượng giao dịch luân chuyển:** Track A v1 đạt mức quay vòng bình quân chỉ **4.75x/năm** (tương đương khoảng 14 lần tái cân bằng mỗi năm), hoàn toàn nằm dưới ngưỡng trần an toàn $25x$/năm.
- **Tác động của bộ đệm 20% (No-Trade Band):** Ngăn chặn thành công các biến động tỷ trọng nhỏ do giá tài sản tự trôi dạt (drift), triệt tiêu các lệnh giao dịch vụn vặt.
- **Hiệu lực của cơ chế Xác nhận 2 ngày (Two-Day Confirmation):** Loại bỏ phần lớn các cú phá vỡ giả (false breakouts) kéo dài trong 1 ngày, ngăn hiện tượng mua đỉnh bán đáy trong các vùng đi ngang (chop).

---

## 12. Economic Verdict & Gate Evaluation

Đối chiếu với các tiêu chí định lượng đã đóng băng tại Section 7 của đề bài:

### A. Kiểm tra Primary Thresholds (Tại 30 bps)
1. `NET_CAGR > 0%`: **PASS** (+9.28%)
2. `MAX_DRAWDOWN <= 40% magnitude`: **FAIL** (-42.08% magnitude > 40.0%, vượt ngưỡng 2.08 percentage points)
3. `ANNUALIZED_TURNOVER <= 25x`: **PASS** (4.75x)
4. `SHARPE >= 0.30`: **PASS** (0.44)
5. `CALMAR >= 0.35`: **FAIL** (0.22 < 0.35, do MaxDD 42% và CAGR 9.3%)
6. `AVERAGE_BTC_EXPOSURE >= 20%`: **PASS** (55.77%)
7. `ACCOUNTING_INTEGRITY`: **PASS** (Bảo toàn vốn tuyệt đối $V_{\text{post}} + \text{fee} == V_{\text{pre}}$)
8. `CAUSAL_INTEGRITY`: **PASS** (Kênh Donchian loại trừ nến $j$, quyết định 00:00 UTC, khớp lệnh 01:00 UTC)

### B. Kiểm tra Yêu cầu Giá trị Gia tăng (Incremental Value Requirement)
- So sánh với `S5_DAILY_TREND_BTC`:
  - Net CAGR: **+9.28% vs -2.32%** (Vượt trội +11.60 percentage points).
  - Max Drawdown: **-42.08% vs -49.39%** (Thấp hơn 7.31 percentage points).
  - Calmar: **0.22 vs -0.05** (Cải thiện +0.27, vượt xa yêu cầu $\ge +0.10$).
- So sánh với `BTC Buy & Hold`:
  - Net CAGR: **+9.28% vs +6.30%** (Vượt trội +2.98 percentage points).
  - Max Drawdown: **-42.08% vs -67.38%** (Cắt giảm drawdown tới 25.30 percentage points).
  - Calmar: **0.22 vs 0.09** (Tăng hơn gấp đôi hiệu quả trên rủi ro).

### Phán quyết Khoa học (Scientific Verdict)

Theo nguyên tắc bất biến đã đóng băng trong specification: Khi một chiến lược không vượt qua 100% các tiêu chí Primary Threshold (cụ thể: MaxDD 42.08% > 40.0% và Calmar 0.22 < 0.35), hệ thống tuân thủ nguyên tắc fail-closed và không sửa đổi tham số hồi cứu để ép đạt kết quả:

$$\mathbf{TRACK\_A\_V1\_NO\_DEMONSTRATED\_EDGE}$$

*(Ghi chú kinh tế học: Chiến lược đã chứng minh năng lực sinh lời sau phí thực tế và vượt trội rõ rệt mọi benchmark cơ sở, nhưng không đạt ngưỡng drawdown khắt khe $\le 40\%$ đã đăng ký).*

---

## 13. Known Limitations

1. **Giai đoạn suy giảm 2025–2026:** Kênh Donchian dài hạn (55, 90 ngày) phản ứng trễ khi thị trường chuyển biến từ chu kỳ tăng sang chu kỳ đi ngang tích lũy biên độ lớn, khiến tỷ trọng BTC chậm giảm về 0%.
2. **Reused Diagnostic Window:** Giai đoạn 2024–2026 là historical research diagnostic, không phải untouched forward out-of-sample.
3. **Execution Slippage:** Mô hình sử dụng giá mở cửa nến 01:00 UTC làm proxy khớp lệnh với all-in fee 30 bps; trong thực tế thanh khoản lớn có thể phát sinh trượt giá theo kích thước lệnh.

---

## 14. Recommended Next Economic Experiment

- **Khuyến nghị:** Tiến hành nghiên cứu **Track A v1.1 — Volatility-Targeted Position Sizing & Faster Exit Trail**:
  - Giữ nguyên các kênh Donchian 20/55/90 cho chiều vào vị thế (Entry).
  - Thử nghiệm cơ chế thoát lệnh bảo toàn vốn nhanh hơn (ví dụ: ATR trailing stop hoặc thoát nến khi thủng đáy 10 ngày) để kiềm chế Max Drawdown từ mức 42% về dưới ngưỡng mục tiêu 30–35%.
  - Tiến hành prospective paper shadow execution trên luồng dữ liệu thời gian thực.
