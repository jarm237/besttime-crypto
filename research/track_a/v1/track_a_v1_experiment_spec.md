# Track A v1: Profit-First Multi-Horizon Trend Following Experiment Specification

**Status:** EXECUTED & SEALED  
**Author:** Besttime-Crypto Quantitative Strategy & Research  
**Date:** 2026-11-19  
**Repository:** `https://github.com/jarm237/besttime-crypto`  
**Branch:** `research/s5-p0-economic-opportunity`  
**Reference Commit:** `f101dfe7ad6eaaeb6ad348942332ab5937545a7e`  

---

## 1. Executive Summary & Objective

Mục tiêu của Track A v1 là xây dựng và đánh giá một hệ thống giao dịch **Trend Following đa khung thời gian (Multi-Horizon Donchian Breakout)** trên tài sản `BTCUSDT` (Spot) kết hợp tiền mặt danh nghĩa `CASH` (USDT, 0% yield), theo định hướng **ưu tiên lợi nhuận thực tế sau phí (profit-first)**.

Hệ thống được thiết kế để giải quyết điểm yếu chí mạng của chiến lược `S5_DAILY_TREND_BTC` (vốn bị bào mòn vốn nặng nề do tần suất đảo vị thế nhị phân 0/100% quá cao, dẫn tới turnover 66.8x/năm và ngốn tới 95% vốn ban đầu vào phí giao dịch ở mức phí 30 bps).

---

## 2. Quantitative Strategy Rules (Track A v1)

### 2.1. Trading Universe
- **Target Asset:** `BTCUSDT` (Binance Spot)
- **Safe Asset:** `CASH` (USDT nominal, 0% return)
- **Constraint:** Long-only, không sử dụng margin/leverage, không short.

### 2.2. Multi-Horizon Donchian State Engine
Hệ thống theo dõi độc lập 3 khung thời gian Donchian:
$$\mathcal{H} = [20, 55, 90] \text{ ngày}$$

Với nến ngày vừa đóng $j$ (tại thời điểm $D$ 00:00 UTC, nến ngày hoàn tất $D-1$):
Kênh Donchian của khung thời gian $N$ được tính toán trên $N$ nến ngày **trước $j$**, tuyệt đối loại trừ chính nến $j$:
$$\text{upper}_N[j] = \max_{k \in [j-N, j-1]} \text{high}[k]$$
$$\text{lower}_N[j] = \min_{k \in [j-N, j-1]} \text{low}[k]$$

Trạng thái xu hướng $\text{state}_N[j] \in \{0, 1\}$ được cập nhật nhân quả:
$$\text{state}_N[j] = \begin{cases} 
1 & \text{nếu } \text{close}[j] > \text{upper}_N[j] \quad (\text{Bullish Breakout}) \\ 
0 & \text{nếu } \text{close}[j] < \text{lower}_N[j] \quad (\text{Bearish Breakdown}) \\ 
\text{state}_N[j-1] & \text{ngược lại (giữ nguyên trạng thái)} 
\end{cases}$$

### 2.3. Stepped Exposure Mapping
Tỷ trọng mục tiêu thô (Raw Exposure) được phân cấp bậc thang mượt mà thay vì chuyển đổi nhị phân:
$$\text{raw\_exposure}[j] = \frac{\text{state}_{20}[j] + \text{state}_{55}[j] + \text{state}_{90}[j]}{3.0}$$
- $0$ bullish states $\rightarrow$ $0.00\%$ BTC (100% Cash)
- $1$ bullish state $\rightarrow$ $33.33\%$ BTC (66.67% Cash)
- $2$ bullish states $\rightarrow$ $66.67\%$ BTC (33.33% Cash)
- $3$ bullish states $\rightarrow$ $100.00\%$ BTC (0% Cash)

### 2.4. Two-Day Confirmation Gate
Để loại bỏ các tín hiệu nhiễu tại biên kênh (whipsaw), tỷ trọng mục tiêu chỉ được phê duyệt khi mức `raw_exposure` duy trì giống nhau trong ít nhất 2 nến ngày hoàn tất liên tiếp:
$$\text{approved\_exposure}[j] = \begin{cases} 
\text{raw\_exposure}[j] & \text{nếu } \text{raw\_exposure}[j] == \text{raw\_exposure}[j-1] \\ 
\text{approved\_exposure}[j-1] & \text{ngược lại} 
\end{cases}$$

### 2.5. No-Trade Band (20 Percentage Points Buffer)
Để triệt tiêu giao dịch vi mô do giá biến động làm lệch tỷ trọng vị thế, ngưỡng tái cân bằng được cố định ở mức **20 percentage points (0.20)**:
$$\text{pre\_btc\_weight} = \frac{H_{\text{btc}} \cdot P_{\text{open}}}{V_{\text{pre}}}$$
$$\text{deviation} = |\text{approved\_exposure} - \text{pre\_btc\_weight}|$$

- Nếu $\text{deviation} > 0.20$: Tiến hành tái cân bằng về tỷ trọng $\text{approved\_exposure}$.
- Nếu $\text{deviation} \le 0.20$: **HOLD** (không giao dịch, tiết kiệm 100% phí).

### 2.6. Execution Clock & Fee Accounting
- **Decision Timestamp:** 00:00 UTC (dựa trên nến ngày $D-1$ vừa hoàn tất).
- **Execution Timestamp:** 01:00 UTC (khớp lệnh tại giá mở cửa nến giờ `01:00 UTC`).
- **Accounting Engine:** Sử dụng bộ giải bảo toàn vốn chính xác `solve_post_fee_equity`:
$$V_{\text{post}} = V_{\text{pre}} - c \cdot |\text{target\_btc\_weight} \cdot V_{\text{post}} - N_{\text{pre}}|$$
Đảm bảo $V_{\text{post}} + \text{fee} \equiv V_{\text{pre}}$, không có tiền giả lập hay trượt giá âm thầm.

---

## 3. Matched Benchmark Baseline: S5 Daily Trend BTC

Giữ nguyên cấu trúc tín hiệu đã khóa trong S5-P0B:
- Tín hiệu động lượng: Lợi nhuận trung bình 168 giờ của rổ 4 tài sản (BTC, ETH, SOL, BNB).
- Exposure: Nhị phân $0\%$ (nếu return $\le 0$) hoặc $100\%$ BTC (nếu return $> 0$).
- Buffer: 5 percentage points (0.05).
- Lịch quyết định: 00:00 UTC hàng ngày, thực thi 01:00 UTC.

---

## 4. Replay Protocol & Scope Boundaries

- **Cửa sổ Replay đồng bộ:** `2022-01-01 00:00:00 UTC` đến `2026-11-18 23:00:00 UTC`.
- **Vốn ban đầu:** $10,000.00 USDT.
- **Kịch bản chi phí giao dịch (All-in one-way cost):** 12 bps, 20 bps, 30 bps (Primary), 50 bps.
- **Cam kết nhân quả:** Không grid-search tham số, không điều chỉnh quy tắc sau khi quan sát dữ liệu.
