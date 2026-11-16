# Research Input Inventory & Architectural Audit (Phase R0)

**Repository**: `https://github.com/jarm237/besttime-crypto`  
**Active Branch**: `research/carm-shadow-observer`  
**Verified Commit**: `4b29fa15205aed29c4fc5467916d81f9fc210992`  
**Audit Date**: 2026-11-17  
**Scope**: Comprehensive inventory of historical data, feature engineering, causal/regime modules, runtime wiring, and decision pathways for the Unified Neural Trading Policy.

---

## 1. Executive Summary & Audit Verdict

Mục tiêu của nghiên cứu là xây dựng một nền tảng **Historical Market Replay** chuẩn xác về mặt quan hệ nhân quả (causally valid) và từng bước khám phá **Unified Neural Trading Policy** nhằm tìm kiếm lợi thế kinh tế thực sự (alpha sau phí giao dịch).

Kết quả kiểm toán hệ thống hiện hữu (Phase R0) cho thấy:
1. **Sự ngắt quãng giữa mã nguồn và thực thi (Implementation vs. Active Wiring)**: Nhiều module tồn tại mã nguồn rất phong phú (Causal Bayesian Networks, TimeGAN, Macro Stress Composites, Regime Multipliers) nhưng trong thực tế vận hành:
   - Tham số nhân quả `CAUSAL_ALPHA` mặc định bằng `0.0` (tắt 100% Bayesian Provider, chỉ dùng heuristic rules).
   - Cơ chế quyết định của `DecisionEngine` thực chất là bộ phối hợp trọng số cố định (heuristic linear blender), không phải policy thích nghi học được.
   - Chính sách rủi ro `apply_final_risk_gate` và `PAPER_ECONOMIC_POLICY` triệt tiêu toàn bộ lệnh thực thi chủ động khi điều kiện không đạt.
2. **Nguy cơ rò rỉ thông tin trong dữ liệu cũ (Lookahead & PIT Violations)**:
   - Đồ thị nhân quả `causal_graph.json` được học tĩnh từ toàn bộ tập dữ liệu, vi phạm nghiêm trọng tính Point-In-Time (PIT) nếu áp dụng hồi quy vào các giai đoạn trước đó.
   - Các biến vĩ mô (Macro) và tâm lý (Fear & Greed) là dữ liệu tần suất ngày (daily), nếu ghép nối trực tiếp vào nến 1h mà không có độ trễ công bố (publication lag) sẽ dẫn đến thiên kiến nhìn trước tương lai (lookahead bias).
3. **Thành công duy nhất đã được chứng minh kinh tế (Economic Parity Baseline)**:
   - Chiến lược **CARM Weekly Momentum** (`0d9f6660` / `CARM_UTC_SUNDAY_CANONICAL_V1`) là chiến lược duy nhất có tính nhân quả nghiêm ngặt (độ trễ `shift(2)`, không nhìn trước), không phụ thuộc vào các nhãn giả lập, và có hồ sơ kinh tế thực tế rõ ràng để làm chuẩn đối sánh (benchmark).

---

## 2. Structured Feature & Data Inventory

### Bảng phân loại quy ước:
- `IMPLEMENTED`: Đã có source code trong repository.
- `WIRED`: Có đường truyền dữ liệu thực tế đến consumer / decision engine.
- `DATA_AVAILABLE`: Có nguồn dữ liệu lịch sử thực tế có thể tải hoặc đã lưu trữ.
- `PIT_VALIDATED`: Đã kiểm chứng tính Point-In-Time (không rò rỉ dữ liệu tương lai).
- `ECONOMICALLY_TESTED`: Đã đo lường hiệu quả kinh tế sau chi phí giao dịch (phí 12 bps, trượt giá, turnover).
- `NOT_AVAILABLE`: Chưa có nguồn dữ liệu tin cậy hoặc không khả thi trong quá khứ.

| Nhóm | Feature / Tín hiệu | Source | Implementation | Data Availability | PIT Validity | Runtime Wiring | Economic Evidence | Nhận xét kiểm toán |
|---|---|---|---|---|---|---|---|---|
| **Market** | OHLCV (1h, 4h, 1d) | Binance Spot / Futures Public API | `IMPLEMENTED` (`carm_market_data.py`, `fetch_historical_range.py`) | `DATA_AVAILABLE` (Continuous 2021–2026 cho 8 coins) | `PIT_VALIDATED` (Nến đóng, shift ≥ 1 bar) | `WIRED` (CARM Observer, Feature Store) | `ECONOMICALLY_TESTED` (Baseline CARM, BTC B&H) | Nhóm dữ liệu nền tảng tin cậy nhất. Nến 1h đóng cung cấp ground truth không tranh cãi. |
| **Technical** | Returns, SMA, EMA, ATR, ADX, FracDiff | Derived từ OHLCV | `IMPLEMENTED` (`market_regime.py`, `fractional_diff.py`) | `DATA_AVAILABLE` (Nội suy từ OHLCV với warmup) | `PIT_VALIDATED` (Rolling windows strictly $\le t-1$) | `WIRED` (Regime Detector, Feature Validator) | `ECONOMICALLY_TESTED` (HMR v1–v5: Churn cao nếu thiếu penalty) | Rất dễ tạo tín hiệu giả nếu không kiểm soát turnover và chi phí giao dịch. |
| **Regime** | Trend, Range, Extreme, Volatility | Heuristic rules (`market_regime.py`) | `IMPLEMENTED` (`market_regime.py`, `contract.py`) | `DATA_AVAILABLE` (Backfill từ OHLCV) | `PIT_VALIDATED` (Calculated trên $t-1$) | `WIRED` (0.15 weight trong `DecisionEngine`) | `ECONOMICALLY_TESTED` (Giảm drawdown mùa gấu, nhưng trễ khi đảo chiều V-shape) | Hiện là rule cứng dựa trên ngưỡng ADX/ATR, chưa phải latent learned regime representation. |
| **Causal** | Causal Graph, Bayesian Posterior | Static JSON (`causal_graph.json`, `bayesian_context_provider.py`) | `IMPLEMENTED` (`causal_context_bridge.py`) | `NOT_AVAILABLE` (Chưa có rolling dynamic graph cho 2022–2026) | `NOT_PROVEN` (Đồ thị học full-sample gây rò rỉ dữ liệu) | `NOT_WIRED` (`CAUSAL_ALPHA=0.0`, bị vô hiệu hóa mặc định) | `ECONOMICALLY_TESTED` (Không tạo thêm alpha so với rule đơn giản) | **Khoảng trống lớn**: Causal graph hiện chỉ là metadata/logging, Gaussian priors bị gán cứng. |
| **Derivatives** | Funding Rate (8h) | Binance Futures Public API | `IMPLEMENTED` (`fetch_binance_funding_history.py`) | `DATA_AVAILABLE` (2023–2026 trong `data/historical/normalized/`) | `PIT_VALIDATED` (Ghi nhận đúng mốc 00:00, 08:00, 16:00 UTC) | `WIRED` (`AlternativeFeatureBuilder`) | `ECONOMICALLY_TESTED` (Wave 1: Tín hiệu yếu, chỉ có ý nghĩa khi cực đoan) | Có giá trị cảnh báo quá nhiệt (crowded trades), nhưng độ trễ 8h làm giảm độ nhạy ngắn hạn. |
| **Derivatives** | Open Interest, Long/Short Ratio | Binance Futures Metrics API | `IMPLEMENTED` (`data/historical/normalized/futures_metrics/`) | `DATA_AVAILABLE` (2023–2026, 5m/1h) | `PIT_VALIDATED` (Timestamp metric có sẵn) | `PARTIAL` (Trong alternative builder, chưa vào policy) | `NOT_PROVEN` (Chưa kiểm chứng độc lập sau phí) | Dữ liệu futures metrics chỉ có từ khi Binance hỗ trợ endpoint lưu trữ. |
| **Liquidity** | Order Book Depth, Liquidations | Real-time WebSockets / Level 2 Depth | `IMPLEMENTED` (Collectors thời gian thực) | `NOT_AVAILABLE` (Không có lịch sử L2/L3 liên tục 2022–2026) | `NOT_AVAILABLE` | `NOT_WIRED` (Chỉ dùng cho execution paper thời gian thực) | `NOT_AVAILABLE` | **Blocker**: Không có dữ liệu lịch sử order book chiều sâu tick-by-tick cho toàn bộ giai đoạn 2022–2026. |
| **Cross-Asset** | Relative Strength, Dispersion, Beta to BTC | Cross-sectional matrix của 8–22 coins | `IMPLEMENTED` (`cross_sectional_features.py`) | `DATA_AVAILABLE` (Tính từ OHLCV toàn universe) | `PIT_VALIDATED` (Tính đồng thời tại timestamp $t$) | `WIRED` (Cốt lõi của xếp hạng CARM) | `ECONOMICALLY_TESTED` (Là động lực chính tạo ra excess return của CARM) | Nhóm tín hiệu có bằng chứng kinh tế thực nghiệm vững chắc nhất trên thị trường crypto. |
| **Macro** | DXY, VIX, US 10Y Yield, Fed Rate | FRED / Yahoo Finance | `IMPLEMENTED` (`macro_collector.py`, `treasury_yields_1990_2026.parquet`) | `DATA_AVAILABLE` (Daily từ 1990–2026) | `PIT_VALIDATED` (Chỉ hợp lệ khi kèm publication lag $\ge 24\text{h}$) | `WIRED` (`WorldState.macro`, `alt_macro_stress_composite`) | `ECONOMICALLY_TESTED` (Hỗ trợ thoát hàng chu kỳ thắt chặt tiền tệ 2022) | Tần suất ngày; bắt buộc phải forward-fill và thêm trễ công bố để tránh lookahead bias. |
| **Sentiment** | Fear & Greed Index | Alternative.me API | `IMPLEMENTED` (`fear_and_greed_2018_2026.parquet`) | `DATA_AVAILABLE` (Daily từ 2018–2026) | `PIT_VALIDATED` (Daily cập nhật 00:00 UTC, ffill cho các giờ) | `WIRED` (`DecisionEngine` 0.15 weight) | `ECONOMICALLY_TESTED` (Chỉ báo đảo chiều tại vùng cực đoan < 20) | Tần suất ngày, độ phân giải thấp, không cung cấp alpha cho các biến động trong ngày. |
| **News / Events** | Event tags, Economic Releases | RSS feeds, Parsebot ETF jobs | `IMPLEMENTED` (Scraper code) | `NOT_AVAILABLE` (Không có lịch sử tin tức chuẩn hóa có PIT timestamp) | `NOT_PROVEN` | `NOT_WIRED` (Không có trong trading pipeline) | `NOT_AVAILABLE` | **Loại bỏ khỏi candidate set ban đầu**: Dữ liệu tin tức không có độ tin cậy lịch sử cao. |

---

## 3. Deep Forensic Audit of Critical Pathways

### 3.1. Tuyến: `Regime → Feature → Model/Decision`
- **Mã nguồn**: [btc_scraper/regime/market_regime.py](file:///d:/Workspaces/besttime-crypto/btc_scraper/regime/market_regime.py) & [btc_scraper/ml_engine/decision_engine.py](file:///d:/Workspaces/besttime-crypto/btc_scraper/ml_engine/decision_engine.py).
- **Cơ chế**:
  - `detect_regime()` tính toán ADX(14), ATR%(14), SMA200, SMA50, EMA21 để gán nhãn: `TREND_BULL`, `TREND_BEAR`, `BREAKOUT`, `RANGE`, `COMPRESSION`, `EXTREME_PANIC`, `EXTREME_PUMP`.
  - Kết quả được chuyển thành `RegimeSnapshot` và nạp vào `DecisionEngine`.
  - Trong `DecisionEngine`, regime được ánh xạ sang xác suất hỗ trợ hành động thông qua bảng tĩnh `REGIME_DIRECTION_SUPPORT` (ví dụ: `TREND_BULL` gán 0.9 BUY / 0.1 SELL).
- **Lỗ hổng & Khoảng trống**:
  - Tín hiệu regime không tác động trực tiếp vào việc huấn luyện mô hình (neural model conditioning), mà chỉ được ghép thủ công theo trọng số cố định:
    `evidence_score = 0.55 * meta + 0.15 * sentiment + 0.15 * regime + 0.15 * volatility`.
  - Đây là sự pha trộn kinh nghiệm chủ quan (heuristic linear blending), làm mất đi tính phi tuyến và khả năng tự thích ứng của mô hình học sâu.

### 3.2. Tuyến: `Causal Context → Risk/Decision → Execution`
- **Mã nguồn**: [btc_scraper/ml_engine/causal_context_bridge.py](file:///d:/Workspaces/besttime-crypto/btc_scraper/ml_engine/causal_context_bridge.py) & [btc_scraper/ml_engine/bayesian_context_provider.py](file:///d:/Workspaces/besttime-crypto/btc_scraper/ml_engine/bayesian_context_provider.py).
- **Cơ chế**:
  - `enhance_signal_with_causal_context` đọc biến môi trường `CAUSAL_ALPHA`.
  - Hàm `_get_causal_alpha()` trả về mặc định `0.0` (chế độ an toàn 100% rule-based).
  - Khi `alpha=0.0`, toàn bộ thành phần Bayes và mạng nhân quả bị bỏ qua hoàn toàn.
  - Khi bật `alpha > 0`, `BayesianContextProvider` tính hợp lý (likelihood) dựa trên các giá trị trung bình Gauss **được gán cứng** (`bullish_mean=100.0` cho DXY, v.v.), không phải phân phối xác suất được học nội sinh từ lịch sử PIT.
- **Lỗ hổng & Khoảng trống**:
  - Causal graph không có tác động thực tế đến việc định cỡ vị thế (sizing) trong runtime mặc định.
  - Nguy cơ rò rỉ tương lai cực cao nếu áp dụng đồ thị nhân quả tĩnh cho backtest lịch sử từ 2022.

### 3.3. Tuyến: `RiskManager / PortfolioManager → Actual Executed Decision`
- **Mã nguồn**: [btc_scraper/trading/portfolio_manager.py](file:///d:/Workspaces/besttime-crypto/btc_scraper/trading/portfolio_manager.py) & [btc_scraper/execution/execution_engine.py](file:///d:/Workspaces/besttime-crypto/btc_scraper/execution/execution_engine.py).
- **Cơ chế**:
  - Sau khi tín hiệu được sinh ra, hàm `apply_final_risk_gate()` kiểm tra mức rủi ro (`CRITICAL` chuyển thành `ALLOW_EXIT_ONLY`, `HIGH` chặn lệnh mở vị thế mới `BLOCK_ENTRY`).
  - Hàm `apply_economic_policy_to_final_decision()` áp dụng chính sách kinh tế: Nếu `PAPER_ECONOMIC_POLICY in {NO_TRADE_SHADOW, NO_TRADE, SHADOW}`, mọi hành động BUY/SELL bị ép chuyển về `HOLD`.
- **Lỗ hổng & Khoảng trống**:
  - Hệ thống paper trading trước đây bị khóa chặt ở chế độ `NO_TRADE_SHADOW`, dẫn đến việc không có lệnh thực thi kinh tế thực tế nào được sinh ra ngoài các bản ghi log giả định.

---

## 4. Proposed Research Architecture: Unified Neural Discovery

Thay vì duy trì cấu trúc chắp vá nhiều module độc lập (nhiều mô hình nhỏ + rule ghép tín hiệu thủ công), kiến trúc nghiên cứu đề xuất hướng tới một **Unified Neural Trading Policy** tinh gọn, chuẩn tắc nhân quả:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   HISTORICAL TIME CURSOR (Timestamp T)                 │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ Only information available at <= T
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   CAUSAL INPUT TENSORS (POINT-IN-TIME)                 │
│  - Market OHLCV 1h (8 Assets, T-Lookback to T-1)                       │
│  - Cross-Sectional Momentum & Relative Strengths (Cross-Asset Matrix)  │
│  - Rolling Volatility & Normalized Returns (Risk/Uncertainty Context)  │
│  - Optional Verified Macro/Derivatives (Lag-aligned Funding, DXY)      │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   UNIFIED NEURAL TRADING POLICY                        │
│  Architecture: Multi-Asset Temporal Encoder (TCN / GRU / Transformer)  │
│  Key Capabilities:                                                     │
│    1. Shared Temporal Representation across Universe                   │
│    2. Endogenous Cross-Asset Attention (Learned Relative Value)        │
│    3. Cost-Aware & Turnover-Penalized Loss Function                    │
│    4. Explicit Portfolio Allocation Head: [w_1, w_2, ..., w_N, w_cash] │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼ Target Portfolio Weights (Sum = 1.0)
┌────────────────────────────────────────────────────────────────────────┐
│                   CAUSAL REPLAY & EXECUTION ENGINE                     │
│  - Causal Execution Delay: Order executed at T open/close prices       │
│  - Transaction Costs: 12 bps execution friction per traded leg         │
│  - Monotonic Accounting: Portfolio Equity, Fees, Turnover, Drawdown    │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   BENCHMARK SCORECARD COMPARISON                       │
│  - Baseline 1: Cash ($10,000.00, 0% Return)                            │
│  - Baseline 2: BTC Buy & Hold (100% BTC Spot Hold)                     │
│  - Baseline 3: Equal-Weight Buy & Hold (1/8 each asset)                │
│  - Baseline 4: Canonical CARM Weekly (0d9f6660 Reference)              │
│  - Candidate:  Unified Neural Policy                                   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Evidence-Backed Gaps & Next Implementation Slice

### Các khoảng trống kỹ thuật cần xử lý ngay:
1. **Thiếu Historical Replay Engine độc lập**:
   - Hiện tại codebase có runner forward observer (`run_carm_forward_observation.py`) nhưng chưa có CLI chuẩn hóa `scripts/run_full_historical_replay.py` có thể nhận `--start`, `--end`, `--interval`, `--mode research` để replay từng nến trong quá khứ một cách xác định (deterministic).
2. **Kho chứa dữ liệu lịch sử chuẩn hóa riêng biệt**:
   - Theo nguyên tắc bắt buộc: Không ghi đè vào `data/historical/` hay các thư mục `data/neural_n1_*`. Cần thiết lập thư mục dữ liệu nghiên cứu cô lập `data/historical_unified_replay/`.
3. **Lát cắt triển khai đầu tiên (First End-to-End Slice)**:
   - Triển khai historical data loader tải và xác thực chuỗi OHLCV 1h đầy đủ cho vũ trụ 8 coin từ 2022 đến cuối 2026.
   - Xây dựng `scripts/run_full_historical_replay.py` mô phỏng khớp lệnh tại nến tiếp theo, khấu trừ phí 12 bps, hạch toán danh mục chính xác.
   - Chạy replay toàn diện 4 baseline: **Cash**, **BTC Buy & Hold**, **Equal-Weight Buy & Hold**, và **Canonical CARM Weekly** (`simulate_carm_top_momentum_strategy`).
   - Lập bảng so sánh kinh tế khách quan đầu tiên trên cùng một không gian thời gian.
