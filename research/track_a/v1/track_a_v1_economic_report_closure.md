# TRACK A V1 — ECONOMIC INTEGRITY CLOSURE REPORT

**Repository:** `jarm237/besttime-crypto`  
**Branch:** `research/s5-p0-economic-opportunity`  
**Base Commit:** `49ae5a2435b66e3f2ab36d547b93461d96512d1a`  
**Target Policy:** Track A v1 (Donchian Multi-Horizon 20/55/90, 2-Day Confirmation, 20% No-Trade Band)  
**Evaluation Window:** 2022-01-01 00:00:00 UTC to 2026-11-18 23:00:00 UTC (4.88 years)  
**Execution Clock:** 00:00 UTC Decision (Cutoff D-1), 01:00 UTC Execution at Hourly Open  
**Primary Cost:** 30.0 bps one-way fee with realistic capital conservation (`solve_post_fee_equity`)  
**Closure Verdict:** `TRACK_A_V1_NO_DEMONSTRATED_EDGE`

---

## 1. Executive Summary & Economic Interpretation

Báo cáo này hoàn tất kiểm toán toàn vẹn kinh tế (**Economic Integrity Closure**) cho chiến lược **Track A v1 Multi-Horizon Trend Following**, đối chiếu lại với baseline S5 Daily Trend BTC theo chuẩn mực toán học S5-P0B, chuẩn hóa công thức đo lường turnover, thay thế các cờ toàn vẹn tĩnh bằng các hàm kiểm tra runtime động, và bảo toàn tính bất biến của pre-registration ban đầu.

### Phân định rõ 4 trạng thái kinh tế:

1. **`HISTORICAL_NET_PROFIT_POSITIVE` (ĐÃ XÁC NHẬN):**  
   Track A v1 duy trì lợi nhuận ròng dương sau phí thực tế trên toàn bộ các kịch bản phí từ 12 bps đến 50 bps. Tại mức phí chuẩn 30 bps, vốn ban đầu $10,000 tăng lên **$15,419.98** (+54.20% lợi nhuận tích lũy, **CAGR +9.28%**), vượt trội so với BTC Buy & Hold ($13,477.24, CAGR +6.30%).
2. **`INCREMENTAL_VALUE_VS_BASELINE` (ĐÃ XÁC NHẬN VƯỢT TRỘI):**  
   So với baseline S5 Daily Trend BTC (vốn bị bào mòn nặng nề bởi chi phí giao dịch, Final Equity $9,339.38, CAGR -1.39%), Track A v1 tạo ra alpha vượt trội **+10.67% CAGR delta**, cải thiện Max Drawdown **+7.31%** (-42.08% vs -49.39%), Calmar **0.22 vs -0.03**, và giảm vòng quay vốn **14.4 lần** (4.67x vs 67.50x), tiết kiệm **$8,741.76 tiền phí**.
3. **`RISK_GATE_FAILED` (VI PHẠM GATE TIỀN ĐĂNG KÝ):**  
   Mức sụt giảm tối đa lịch sử của Track A v1 là **-42.08%** (xảy ra trong giai đoạn bear market 2022), vượt ngưỡng chặn rủi ro định sẵn $\le 40.00\%$. Do đó, theo đúng nguyên tắc pre-registration không viết lại lịch sử, phán quyết khoa học chính thức được giữ nguyên: **`TRACK_A_V1_NO_DEMONSTRATED_EDGE`**.
4. **`FORWARD_PROFIT_NOT_CONFIRMED` (KHÔNG TỰ Ý SUY RỘNG):**  
   Dữ liệu lịch sử 2022–2026 đã được tái sử dụng trong quá trình chẩn đoán nghiên cứu, không thể dùng làm bằng chứng xác nhận lợi nhuận tương lai. Track A v1 chỉ đủ điều kiện làm ứng viên quan sát paper forward (**FORWARD_PAPER_CANDIDATE = YES**), tuyệt đối không được cấp quyền triển khai vốn thật (**PRODUCTION_AUTHORIZATION = NO**).

---

## 2. Before / After Comparison Table (Sửa lỗi toàn vẹn)

Dưới đây là bảng đối chiếu chi tiết giữa kết quả ban đầu (v1 original) và kết quả sau khi chuẩn hóa toàn vẹn (v1 corrected) tại mức phí 30 bps:

| Metric | Track A v1 (Original) | Track A v1 (Corrected) | S5 Daily (Original Positional) | S5 Daily (Corrected Causal) | BTC Buy & Hold |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Final Equity** | $15,419.98 | **$15,419.98** | $8,916.77 | **$9,339.38** | $13,477.24 |
| **Net Cumulative Return** | +54.20% | **+54.20%** | -10.83% | **-6.61%** | +34.77% |
| **CAGR** | +9.28% | **+9.28%** | -2.32% | **-1.39%** | +6.30% |
| **Max Drawdown** | -42.08% | **-42.08%** | -49.39% | **-49.39%** | -67.38% |
| **Calmar Ratio** | 0.22 | **0.22** | -0.05 | **-0.03** | 0.09 |
| **Sharpe Ratio ($\sqrt{8760}$)** | 0.44 | **0.44** | 0.09 | **0.12** | 0.37 |
| **Annualized Turnover** | 4.75x (avg eq) | **4.67x (pre-trade eq)** | 66.79x | **67.50x** | 0.20x |
| **Total Fees Paid** | $1,047.28 | **$1,047.28** | $9,551.87 | **$9,789.04** | $29.91 |
| **Traded Notional** | $349,091.97 | **$349,091.97** | $3,183,955.82 | **$3,263,013.35** | $9,970.09 |
| **Rebalance Trades** | 63 | **63** | 334 | **339** | 1 |
| **Avg BTC Exposure** | 57.15% | **57.15%** | 50.76% | **50.81%** | 100.0% |
| **Avg Cash Exposure** | 42.85% | **42.85%** | 49.24% | **49.19%** | 0.0% |
| **Integrity Assertion** | Hardcoded PASS | **Dynamic PASS** | Hardcoded PASS | **Dynamic PASS** | **Dynamic PASS** |

### Nhận xét về sự thay đổi sau hiệu chỉnh:
1. **Chuẩn hóa Turnover:** Track A v1 chuyển từ việc chia cho `avg_equity` sang công thức chuẩn mực $\sum (\text{traded\_notional} / \text{pre\_trade\_equity}) / \text{years}$, giúp vòng quay vốn chính xác là **4.67x/năm** (thay vì 4.75x). Tổng traded notional ($349,091.97) và tổng phí ($1,047.28) giữ nguyên tuyệt đối.
2. **Khôi phục tính chuẩn mực của S5 Baseline:** Việc loại bỏ `shift(168)` vị trí và thay bằng truy vấn lịch 168 giờ chuẩn S5-P0B (`compute_market_trend_168h`) phát hiện chính xác 7 ngày có khoảng trống dữ liệu sàn (đặc biệt là sự cố mất kết nối sàn Binance ngày `2023-03-24 13:00 UTC`). Tại các ngày này, baseline kích hoạt đúng quy tắc `HOLD_DATA_GAP` thay vì tính lệch 169 giờ. Lợi nhuận của S5 Baseline sau sửa đổi tăng nhẹ từ -$1,083 lên -$660 (Final Equity $9,339.38 vs $8,916.77), nhưng vẫn thua lỗ nặng nề do tần suất đảo vị thế quá cao (turnover 67.5x, ngốn gần $10,000 tiền phí).

---

## 3. Targeted Implementation Corrections

### 3.1. S5 Baseline Causal Calendar Lookback & HOLD_DATA_GAP
- Trong mã nguồn gốc, `pct_168 = (closes_df / closes_df.shift(168)) - 1.0` dùng positional shift. Khi gặp giờ bị khuyết (`2023-03-24 13:00 UTC`), dòng thứ 168 lùi về quá khứ tương ứng với 169 giờ thực tế trên đồng hồ.
- Mã nguồn hiệu chỉnh đã tích hợp hàm chuẩn `compute_market_trend_168h` từ `s5_economic_replay.py`:
  - Tạo `idx = pd.date_range(cutoff - 168h, cutoff, freq="h", tz="UTC")` với 169 mốc giờ liên tục.
  - Kiểm tra tính đầy đủ trên toàn bộ 4 tài sản trong `UNIVERSE`.
  - Nếu thiếu bất kỳ mốc nến nào, trả về `None`, kích hoạt `HOLD_DATA_GAP` và giữ nguyên tỷ trọng mục tiêu trước đó.

### 3.2. Dynamic Runtime Integrity Checkers
Thay thế cờ tĩnh `True` bằng hai hàm kiểm định runtime độc lập:
1. **`verify_replay_accounting_integrity(res)`:**
   - Kiểm tra bảo toàn vốn trên từng lệnh giao dịch thông qua nghiệm phương trình phi tuyến `solve_post_fee_equity`: $|V_{\text{post}} + \text{fee} - V_{\text{pre}}| < 10^{-5} \times V_{\text{pre}}$.
   - Kiểm tra số dư tiền mặt không âm: $\min(\text{cash\_history}) \ge -10^{-6}$.
   - Kiểm tra số dư BTC không âm: $\min(\text{btc\_holdings}) \ge -10^{-8}$.
   - Kiểm tra quỹ đạo vốn luôn dương: $\min(\text{equities}) > 0$.
   - Kiểm tra phí và giá trị giao dịch không âm trên sổ cái quyết định (`decision_ledger`).
2. **`verify_replay_causal_integrity(res, signals)`:**
   - Kiểm tra tính nhân quả của đồng hồ thực thi: `execution_ts > decision_ts` (01:00 UTC > 00:00 UTC).
   - Kiểm tra không có rò rỉ dữ liệu tương lai (lookahead): nến ngày $D-1$ đóng lúc 23:59 UTC, quyết định thực hiện tại 00:00 UTC ngày $D$, khớp lệnh tại giá mở cửa 01:00 UTC ngày $D$.
   - Toàn bộ 1,783 dòng trong decision ledger của Track A v1 và S5 Daily Trend đều vượt qua kiểm định động: **PASS**.

### 3.3. Daily OHLCV Completeness & Exchange Outages
- Kiểm toán toàn bộ 2,148 nến ngày UTC từ `2021-01-01` đến `2026-11-18`.
- Xác nhận có đúng 7 ngày khuyết giờ giao dịch do bảo trì sàn Binance Spot chính thức (không chèn nến nhân tạo/synthetic candle):
  - `2021-02-11`: 23/24 giờ
  - `2021-03-06`: 23/24 giờ
  - `2021-04-20`: 22/24 giờ
  - `2021-04-25`: 21/24 giờ
  - `2021-08-13`: 20/24 giờ
  - `2021-09-29`: 22/24 giờ
  - `2023-03-24`: 23/24 giờ (khuyết mốc 13:00 UTC)
- Tất cả các nến ngày này được gom cụm tổng hợp từ các nến 1h có thật; khối lượng và biên độ giá phản ánh đúng dữ liệu gốc từ Binance checksummed archive.

---

## 4. Cost Sweep Sensitivity Analysis

| Fee Tier | Metric | Track A v1 (Donchian Step) | S5 Daily Trend BTC | BTC Buy & Hold |
| :---: | :--- | :---: | :---: | :---: |
| **12.0 bps** | Final Equity | **$16,065.79** | $16,915.70 | $13,501.47 |
| | CAGR | **+10.20%** | +11.37% | +6.34% |
| | Max Drawdown | **-40.92%** | -39.07% | -67.38% |
| | Calmar | **0.25** | 0.29 | 0.09 |
| | Sharpe | **0.47** | 0.49 | 0.37 |
| | Total Fees | **$428.93** | $5,408.67 | $11.99 |
| **20.0 bps** | Final Equity | **$15,775.49** | $12,990.80 | $13,490.69 |
| | CAGR | **+9.79%** | +5.51% | +6.33% |
| | Max Drawdown | **-41.44%** | -43.57% | -67.38% |
| | Calmar | **0.24** | 0.13 | 0.09 |
| | Sharpe | **0.46** | 0.33 | 0.37 |
| | Total Fees | **$707.40** | $7,783.66 | $19.96 |
| **30.0 bps** | Final Equity | **$15,419.98** | $9,339.38 | $13,477.24 |
| *(Primary)* | CAGR | **+9.28%** | -1.39% | +6.30% |
| | Max Drawdown | **-42.08%** | -49.39% | -67.38% |
| | Calmar | **0.22** | -0.03 | 0.09 |
| | Sharpe | **0.44** | 0.12 | 0.37 |
| | Total Fees | **$1,047.28** | $9,789.04 | $29.91 |
| **50.0 bps** | Final Equity | **$14,732.81** | $4,827.02 | $13,450.42 |
| | CAGR | **+8.26%** | -13.86% | +6.26% |
| | Max Drawdown | **-43.35%** | -61.66% | -67.38% |
| | Calmar | **0.19** | -0.22 | 0.09 |
| | Sharpe | **0.41** | -0.29 | 0.37 |
| | Total Fees | **$1,700.45** | $11,756.75 | $49.75 |

### Nhận định về độ nhạy cảm chi phí:
- **Track A v1 cực kỳ bền bỉ với chi phí:** Ngay cả khi nâng phí lên 50 bps, Track A v1 vẫn đạt lợi nhuận cuối kỳ $14,732.81 (+8.26% CAGR), vượt BTC Buy & Hold ($13,450.42). Nhờ cơ chế lọc 2-day confirmation và dải đệm không giao dịch 20%, chiến lược chỉ đảo danh mục 63 lần trong gần 5 năm.
- **S5 Daily Trend bị phá hủy bởi chi phí:** Ở mức phí 12 bps, S5 có lợi nhuận khả quan ($16,915.70), nhưng khi nâng lên 30 bps, toàn bộ lợi nhuận bị phí ăn mòn (-$660.62), và tại 50 bps bị sụt giảm hơn 51% vốn ($4,827.02, phí ngốn $11,756.75).

---

## 5. Calendar & Macro Regime Decomposition (at 30 bps)

### 5.1. Calendar Year Breakdown
| Period | Track A Net Return | Track A MaxDD | S5 Daily Net Return | S5 Daily MaxDD | BTC B&H Net Return | BTC B&H MaxDD |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **2022** | **-26.69%** | **-35.32%** | -36.42% | -42.84% | -64.44% | -67.38% |
| **2023** | **+44.75%** | **-14.88%** | +60.72% | -19.46% | +156.09% | -20.08% |
| **2024** | **+51.81%** | **-17.72%** | +36.19% | -28.91% | +120.25% | -23.59% |
| **2025** | **-3.79%** | **-17.18%** | -24.46% | -27.81% | -7.21% | -31.33% |
| **2026 YTD** | **+4.00%** | **-9.37%** | -13.06% | -24.62% | +3.44% | -24.36% |
| **FULL (22-26)**| **+54.20%** | **-42.08%** | -6.61% | -49.39% | +34.77% | -67.38% |

### 5.2. Market Regime Breakdown
1. **BEAR DELEVERAGING 2022 (2022-01-01 to 2022-12-31):**  
   - Track A: -26.69% (bảo toàn vốn vượt trội so với mức sụp đổ -64.44% của Buy & Hold nhờ giữ trung bình 74% Cash).
2. **EARLY RECOVERY 2023 (2023-01-01 to 2023-10-15):**  
   - Track A: +12.39% (tham gia thận trọng vào đà hồi phục).
3. **STRONG UPTREND ETF (2023-10-16 to 2024-03-31):**  
   - Track A: +55.25% (nắm bắt trọn vẹn sóng tăng trưởng thể chế ETF với tỷ trọng 100% BTC).
4. **SIDEWAYS CHOP 2024 (2024-04-01 to 2024-10-31):**  
   - Track A: -2.01% (hạn chế tối đa hiện tượng whipsaw nhờ dải đệm 20%).
5. **POST ELECTION BULL (2024-11-01 to 2025-01-31):**  
   - Track A: +22.01% (tăng tốc cùng sóng bầu cử).
6. **MACRO EXPANSION / CONSOLIDATION (2025-02-01 to 2026-11-18):**  
   - Track A: -3.89% (giữ tiền mặt khi thị trường đi vào vùng phân phối).

---

## 6. Official Gate Evaluation & Scientific Decision

| Gate Identifier | Pre-Registered Requirement | Evaluated Metric | Status |
| :--- | :--- | :---: | :---: |
| `net_cagr_gt_0` | Lợi nhuận ròng sau phí CAGR > 0% | +9.28% | **PASS** |
| `max_dd_lte_40pct` | Mức sụt giảm tối đa $|MaxDD| \le 40.00\%$ | **-42.08%** | **FAIL** |
| `annualized_turnover_lte_25x` | Vòng quay vốn danh mục $\le 25.0$x | 4.67x | **PASS** |
| `sharpe_gte_0_30` | Tỷ số Sharpe chuẩn hóa $\ge 0.30$ | 0.44 | **PASS** |
| `calmar_gte_0_35` | Tỷ số Calmar $\ge 0.35$ | 0.22 | **FAIL** |
| `avg_btc_exposure_gte_20pct` | Tỷ trọng đầu tư BTC trung bình $\ge 20.0\%$ | 57.15% | **PASS** |
| `accounting_integrity_pass` | Kiểm định bảo toàn vốn và số dư không âm | Dynamic | **PASS** |
| `causal_integrity_pass` | Kiểm định đồng hồ thực thi và không lookahead | Dynamic | **PASS** |

### Kết luận Khoa học:
Mặc dù Track A v1 chứng minh được giá trị kinh tế thực chất và vượt trội rõ ràng so với S5 Baseline và BTC B&H, chiến lược vẫn vi phạm tiêu chí chặn rủi ro đã đóng băng trong Pre-Registration (Max Drawdown -42.08% vượt ngưỡng -40.0%). 

Do đó, theo đúng tinh thần khoa học khách quan:
- **SCIENTIFIC VERDICT:** `TRACK_A_V1_NO_DEMONSTRATED_EDGE`.
- Không sửa tiêu chí gate hồi tố để biến kết quả thành PASS.
- Không đưa vào giao dịch vốn thật: **`PRODUCTION_AUTHORIZATION = NO`**.

---

## 7. Next Action & Forward Paper Protocol

Dựa trên việc Track A v1 có lợi nhuận dương sau phí ổn định qua 4 kịch bản chi phí, có tỷ số Calmar dương (0.22) và kiểm soát rủi ro tốt hơn hẳn Buy & Hold (-42% vs -67%), hành động kinh tế duy nhất được phê duyệt là:

**`FORWARD_PAPER_CANDIDATE = YES`**

### Quy tắc quan sát Forward Paper Shadow:
1. **Giữ nguyên chính sách nguyên bản:** Quan sát đúng Track A v1 (Donchian 20/55/90, 2-day confirmation, 20% no-trade buffer, BTC/Cash). **Tuyệt đối không áp dụng ATR stop, không can thiệp volatility sizing, không đổi sang Track A v1.1 hay Neural Policy.**
2. **Công cụ quan sát độc lập:** Thiết lập script terminal thủ công `scripts/run_track_a_v1_paper_observer.py`.
   - Script hoạt động độc lập, không gắn với bất kỳ API sàn hay tài khoản giao dịch nào.
   - Định kỳ quan sát sau khi nến ngày đóng (00:05 UTC), tính toán kênh Donchian và tín hiệu 2-day confirmation.
   - Nếu độ lệch $> 20\%$, mô phỏng khớp lệnh tại giá mở cửa 01:00 UTC với phí 30 bps (`solve_post_fee_equity`).
   - Ghi nhận lịch sử vào `research/track_a/paper/track_a_v1_paper_ledger.csv` và `research/track_a/paper/track_a_v1_paper_state.json`.
3. **Tiêu chuẩn nghiệm thu Forward:** Thu thập dữ liệu paper tối thiểu 90 ngày liên tục ngoài mẫu để làm căn cứ đánh giá tiếp theo.
