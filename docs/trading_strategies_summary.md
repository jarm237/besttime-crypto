# CHIẾN LƯỢC GIAO DỊCH & CÔNG THỨC TOÁN HỌC ĐANG SỬ DỤNG

Tài liệu tổng hợp toàn bộ chỉ báo kỹ thuật, công thức, quy tắc tín hiệu (7 lớp lọc), quản lý vị thế, RL Exit Manager và Causal World Model trong hệ thống bot giao dịch Crypto.

> **Cập nhật lần cuối**: 14/07/2026 — Bổ sung ngữ nghĩa signal_score, MTF confluence, AutoTrader gate và liên kết đánh giá signal flow

---

## 0. Web Dashboard & UI

- **React / Vite dashboard** tại `http://localhost:3000` kết nối backend `api/server.py` (port 8000).
- **Tab chính**:
  - `Tín Hiệu Thị Trường`: Live signals, RSI, trend, chandelier, meta confidence, causal risk level.
  - `Vị Thế Đang Mở`: Quản lý vị thế, mở/đóng lệnh, xem PnL, SL, TP.
  - `CCXT Auto Trading Monitor`: Dry Run / Live, Circuit Breaker, daily trade limit, audit logs.
  - `Meta Model Analytics`: Feature importance, calibration buckets, ROC-AUC.
  - `Gemini AI Insights`: Báo cáo AI từ `data/latest_ai_analysis.json`.
- **Signal Tracker**: Tín hiệu đã phát trước đó được theo dõi bền vững (TTL 90 phút), hiển thị trong Telegram dưới mục "THEO DÕI TÍN HIỆU ĐÃ CÓ TRƯỚC ĐÓ".

---

## 1. Các Chỉ báo Kỹ thuật & Công thức Toán học

Hệ thống tính toán hoàn toàn bằng **Pandas / NumPy vectorized** — không dùng vòng lặp Python thuần.

### 1.1. Average True Range (ATR - 14)
* **Mục đích**: Đo biến động — nền tảng tính SL/TP.
* **Công thức**:
  $$TR = \max(High - Low,\ |High - Close_{prev}|,\ |Low - Close_{prev}|)$$
  $$ATR_{14} = \frac{ATR_{t-1} \times 13 + TR_t}{14} \quad (\text{Wilder's Smoothing})$$

### 1.2. Relative Strength Index (RSI - 14)
* **Mục đích**: Đo động lượng — quá mua (>70), quá bán (<30).
* **Công thức**: Wilder's Smoothing cho AvgGain/AvgLoss; $RSI = 100 - \frac{100}{1 + RS}$

### 1.3. EMA (9 & 21)
$$EMA_t = (Close_t - EMA_{t-1}) \times k + EMA_{t-1}, \quad k = \frac{2}{N+1}$$

### 1.4. SMA (50 & 200)
$$SMA_N = \frac{1}{N} \sum_{i=0}^{N-1} Close_{t-i}$$

### 1.5. MACD (12, 26, 9)
* MACD Line = $EMA_{12} - EMA_{26}$; Signal = $EMA_9(MACD)$; Histogram = MACD − Signal

### 1.6. Bollinger Bands (BB - 20, std=2)
* Middle = $SMA_{20}$; Upper/Lower = Middle ± 2σ — TP1 (Middle), TP2 (Upper/Lower Band)

### 1.7. Chandelier Exit (22, 3.0)
* $LongStop = Highest\_High_{22} - 3.0 \times ATR_{22}$ → Close < LongStop: **BEAR**
* $ShortStop = Lowest\_Low_{22} + 3.0 \times ATR_{22}$ → Close > ShortStop: **BULL**

### 1.8. Volume SMA (20) & Volume Spike
* $VolumeSpike = (Volume_{current} > 1.3 \times VolumeSMA_{20})$

---

## 2. Chiến lược Tín hiệu (7 Lớp Lọc Quyết Định)

```
Nến đóng cửa
    → [L1] SMA200 Trend Filter      (Bull/Bear context)
    → [L2] SMA50 Pullback Zone      (BUY Pullback entry)
    → [L3] EMA 9/21 Crossover       (Golden/Death Cross)
    → [L4] Chandelier Exit          (Block BUY khi BEAR)
    → [L5] Volume + SFP Sweep       (Confirm momentum)
    → [L6] Fear & Greed Sentiment   (Downgrade extreme)
    → [L7] ML Ensemble Scoring      (meta_confidence + Kelly)
    → [Causal Gate] WorldState Risk (CRITICAL → NEUTRAL override)
    → OUTPUT: BUY / SELL / NEUTRAL (Score 0-100 + Position Size)
```

### L1 — SMA 200 Trend Filter
* Bull: $Close > SMA_{200}$ → cho phép BUY
* Bear: $Close < SMA_{200}$ → chỉ cho phép SELL

### L2 — SMA 50 Pullback Zone
* EMA9 < EMA21, $SMA_{50} \times 0.99 \leq Close \leq EMA_{21}$, nến xanh, SMA50 dốc lên, Close > SMA200, Chandelier=BULL, RSI < 55.

### L3 — EMA Crossover Matrix
* **Golden Cross**: prev_EMA9 ≤ prev_EMA21 AND curr_EMA9 > curr_EMA21 → BUY
* **Death Cross**: prev_EMA9 ≥ prev_EMA21 AND curr_EMA9 < curr_EMA21 → SELL

### L4 — Chandelier Exit Filter
* Chandelier=BEAR → Block tất cả BUY → hạ cấp WEAK BUY (Crossover-Blocked)

### L5 — Volume Spike & SFP
* **SFP Bullish**: Low < Support₅₀ AND Close > Support₅₀ AND RSI < 45
* **SFP Bearish**: High > Resistance₅₀ AND Close < Resistance₅₀ AND RSI > 55 AND below SMA200
* **RSI Turning Up**: prev_RSI ≤ 30 AND curr_RSI > 30 → STRONG BUY
* **RSI Turning Down**: prev_RSI ≥ 70 AND curr_RSI < 70 → STRONG SELL

### L6 — Fear & Greed Sentiment
* Nguồn: `alternative.me/fng`, cache 1h. Mapping: raw 0–100 → [-1.0, +1.0]
* **Extreme Fear** (score < −0.6): Hạ STRONG BUY → WEAK BUY
* **Extreme Greed** (score > +0.6): Hạ STRONG SELL → WEAK SELL

### Score Semantics & AutoTrader Gate (cập nhật 14/07/2026)

Đánh giá đầy đủ: [`SIGNAL_DETECTION_AND_SCORING_ASSESSMENT.md`](../evaluations/SIGNAL_DETECTION_AND_SCORING_ASSESSMENT.md).

`signal_score.py` dùng score nội bộ hai chiều:

```text
0   = strongest SELL
50  = NEUTRAL
100 = strongest BUY
```

Vì vậy UI/Telegram dùng `display_score` để chuẩn hóa sức mạnh theo chiều tín hiệu:

- BUY: `display_score = score`
- SELL: `display_score = 100 - score`
- NEUTRAL: `display_score = 0`

AutoTrader hiện chỉ xem xét lệnh khi:

- signal có BUY hoặc SELL rõ ràng, không phải `WEAK`;
- có `meta_confidence`;
- meta confidence và signal score vượt ngưỡng cấu hình;
- không bị causal conflict, circuit breaker, duplicate position, correlation filter, VaR hoặc exposure cap chặn.

Ghi chú vận hành: AutoTrader dùng `strength`, không dùng raw directional `score`, nên STRONG SELL có raw score thấp vẫn vượt ngưỡng đúng như STRONG BUY.

### L7 — ML Ensemble Scoring (MetaDecisionEngine)
* **Mô hình**: RandomForest + LightGBM + CatBoost + XGBoost, Optuna tuning.
* **Hiệu chuẩn**: Platt Sigmoid scaling → xác suất chính xác.
* **Đầu ra**: `meta_confidence` [0,1] + `kelly_fraction` + `action`.
* **Continuous Learning**: Hàng tuần auto-retrain (Concept Drift → CV ROC-AUC ≥ 0.55).

### Causal Gate (Phase B — Production)
* `CRITICAL` risk (từ WorldState) → override `signal_score.action` → `NEUTRAL`; AutoTrader hard-block nếu action không còn BUY/SELL trước execution
* `HIGH / MEDIUM` risk → Warning flag `causal_warning=True` (soft gate, không override)
* `LOW` risk → Pass through không thay đổi
* Điều chỉnh bởi `CAUSAL_ALPHA` env var (0.0=rule-only, 0.1+=Bayesian blend)

---

## 3. Entry, Stop Loss (SL) & Take Profit (TP)

Tham số mặc định: `atr_sl_mult = 1.2`, `atr_tp_mult = 3.5`

### 3.1. Lệnh BUY (Long)

| Level | Công thức | Logic |
|-------|-----------|-------|
| **Entry** | $Close$ | Giá đóng cửa |
| **SL** | $\max(Entry - 1.2 \times ATR,\ Support \times 0.998)$ | Chọn mức gần hơn |
| **TP1** | $\min(BB\_Middle,\ Entry + 3.5 \times ATR)$ | Mục tiêu bảo thủ |
| **TP2** | $\min([Resistance \times 0.998,\ BB\_Upper \times 0.998,\ Entry + 7.0 \times ATR])$ | Chỉ xét > TP1 |

### 3.2. Lệnh SELL (Short)

| Level | Công thức | Logic |
|-------|-----------|-------|
| **Entry** | $Close$ | Giá đóng cửa |
| **SL** | $\min(Entry + 1.2 \times ATR,\ Resistance \times 1.002)$ | Chọn mức gần hơn |
| **TP1** | $\max(BB\_Middle,\ Entry - 3.5 \times ATR)$ | Mục tiêu bảo thủ |
| **TP2** | $\max([Support \times 1.002,\ BB\_Lower \times 1.002,\ Entry - 7.0 \times ATR])$ | Chỉ xét < TP1 |

### 3.3. Backtest TP/SL (8,000 nến)

| Tham số TP1 | WR BUY | TP1 Hit Rate |
|-------------|--------|-------------|
| ATR × 3.5 (hiện tại) | 70.5% | 27% |
| ATR × 2.0 (đề xuất) | ~75% est | ~45% est |

---

## 4. Signal Tracker (Persistent — mới)

`btc_scraper/analysis/signal_tracker.py` — theo dõi trạng thái tín hiệu bền vững:

- **Storage**: `data/tracked_signals.json` (per-coin, append-only với dedup theo timestamp)
- **TTL**: 90 phút — tự động prune sau khi hết hạn
- **States**: `Running (Van con hieu luc)` → `Hit TP1` / `Hit TP2` / `Hit SL`
- **Evaluation**: So sánh current_close với TP1/TP2/SL của mỗi signal còn active

```python
from btc_scraper.analysis.signal_tracker import signal_tracker

# Đăng ký tín hiệu mới
signal_tracker.register_signal(
    coin="BTC", signal_time="2026-07-02T09:00",
    signal="STRONG BUY", entry=65000.0,
    tp_sl={"tp1": 67000, "tp2": 70000, "sl": 63000},
    reason="RSI Reversal + Golden Cross"
)

# Đánh giá tín hiệu đang theo dõi
tracked = signal_tracker.evaluate_signals("BTC", current_close=66000.0)
```

---

## 5. Quản lý Vị thế

### 5.1. Khuyến nghị tự động (evaluate_positions)

| Tình huống | Khuyến nghị | Urgency |
|-----------|------------|---------|
| Close ≤ SL (LONG) hoặc Close ≥ SL (SHORT) | 🚨 CẮT LỖ NGAY | HIGH |
| Close ≥ TP2 (LONG) hoặc Close ≤ TP2 (SHORT) | 🎯 CHỐT LỜI TP2 | HIGH |
| Close ≥ TP1 (LONG) hoặc Close ≤ TP1 (SHORT) | ✅ Xem xét CHỐT TP1 (50%) | MEDIUM |
| Tín hiệu đảo chiều ngược hướng vị thế | ⚠️ XEM XÉT ĐÓNG LỆNH | MEDIUM |
| PnL < −3% | ⚠️ CẢNH BÁO LỖ | MEDIUM |
| Còn lại | 💤 GIỮ LỆNH | LOW |

### 5.2. Công thức Hiệu suất

$$PnL\%_{LONG} = \frac{ExitPrice - EntryPrice}{EntryPrice} \times 100$$
$$PnL\%_{SHORT} = \frac{EntryPrice - ExitPrice}{EntryPrice} \times 100$$
$$R = \frac{PnL\%}{Risk\%}, \quad Risk\% = \frac{|Entry - SL|}{Entry} \times 100$$

**Phí giao dịch** (0.1% mỗi chiều — Binance Futures):
$$Fee = Invested \times 0.001 + (Invested + PnL_{USD}) \times 0.001$$

---

## 6. Reinforcement Learning Exit Manager (Phase 4)

### Môi trường (Gymnasium — `rl_trading_env.py`)

**State Space (18D)**:
- Technical: RSI→[-1,1], MACD Hist (tanh), ATR% (tanh), ADX→[0,1], BB Width% (tanh)
- Position: PnL% (tanh scaled), Hold Time (/ max_episode_length=50)
- Context: meta_confidence [0,1], FearGreed→[-1,1], Volume Ratio (tanh)
- Regime: One-hot 8D (STRONG_TREND, WEAK_TREND, COMPRESSION, BREAKOUT, MEAN_REVERSION, PANIC_SELL, LOW_LIQUIDITY, PUMP_RISK)

**Action Space (6 discrete)**:
| Action | Mô tả |
|--------|-------|
| `0: HOLD` | Tiếp tục giữ vị thế |
| `1: PARTIAL_CLOSE_50` | Chốt/cắt 50% vị thế |
| `2: MOVE_SL_TO_BREAKEVEN` | Dịch SL về entry (zero-risk) |
| `3: TAKE_PROFIT` | Chốt toàn bộ thủ công |
| `4: EXIT` | Thoát khẩn cấp toàn bộ |
| `5: TRAILING_SL_ATR` | Trailing SL = 1.5×ATR |

**Reward Shaping**:
```python
reward = pnl * reward_scale
if pnl < 0: reward -= drawdown_penalty   # Phạt gồng lỗ
if hold_pnl < 0: reward -= 0.002         # Holding penalty mỗi step
if hold_pnl > 0: reward += 0.01 + pnl*0.002  # Holding bonus gồng lãi
if exiting_near_peak: reward += sharpe_bonus
# Trừ phí round-trip 0.3% khi kết thúc lệnh
```

### Kết quả thực nghiệm (PPO 500k steps)

| Metric | Rule-Based | RL Agent (PPO) |
|--------|-----------|---------------|
| Mean Reward | -4.157 | **-2.509** (+1.648) |
| Mean PnL thực tế | -0.134% | -0.304% |
| SL Hit | 72.1% | 40.4% |
| TP Hit | 26.6% | 11.6% |
| PARTIAL_CLOSE_50 | — | 28.4% exits |

**Nghịch lý Reward-PnL**: Agent tối ưu reward nhân tạo → chốt lời non → phí 0.3% ăn 30-60% lợi nhuận.

**Huấn luyện**:
```bash
python train_rl_exit_manager.py --algo ppo --train --steps 100000 --n-trades 500
python evaluate_rl_phase4.py
```

**Roadmap cải thiện**:
- Simplify reward về net PnL thuần (bỏ heuristic bonuses)
- Chuyển sang `MlpLstmPolicy` để nhớ lịch sử chuỗi
- Tăng step size 15m → 1h để giảm market noise
- Thêm asset volatility profile vào State Space

---

## 7. Causal World Model Integration

### 7.1. WorldState (5 Layers)
```python
WorldState
  ├─ macro:     DXY, FedRate, RealYield, BondYield, VIX
  ├─ liquidity: BTC_Funding, OI_Delta, Funding_Z, LongShortRatio
  ├─ crypto:    BTC_Price, ETH_Price, volumes
  ├─ sentiment: FearGreed, SocialVolume
  └─ risk:      CurrentDrawdown, Volatility, VaR95, Sharpe
```

### 7.2. HybridContextProvider
```python
# Alpha=0.0 → 100% rules (safe mode, default)
# Alpha=0.3 → 70% rules + 30% Bayesian
provider = HybridContextProvider.build(
    alpha=float(os.environ.get("CAUSAL_ALPHA", "0.0")),
    graph_path="data/causal_graph.json",
    rules_path="data/context_rules.json",
)
report = provider.generate_context_report(original_score=0.75, world_state=state)
# → ContextReport: adjusted_score=0.52, risk_level="HIGH", adjustments=[...]
```

### 7.3. CounterfactualEngine (Phase D)
```python
# ExecutionAgent tự động chạy sau mỗi cycle cho losing trades
engine = CounterfactualEngine()
result = engine.analyze_trade(
    trade={"pnl": -120, "entry_price": 61000, "exit_price": 60000, "size": 0.1},
    base_state=world_state,
    intervention=Intervention(type=InterventionType.CUSTOM, target_node="DXY", value=5.0)
)
# → {"actual_pnl": -120, "counterfactual_pnl": -85.3, "delta_pnl": 34.7, ...}
# Saved to: logs/counterfactual_log.json (max 200 records)
```

---

## 8. Giao dịch Tự động (Auto-Trading CCXT)

### 8.1. Điều kiện Kích hoạt (`should_trade`)
1. Coin trong whitelist `AUTO_TRADE_COINS`
2. Tín hiệu BUY/SELL rõ ràng (không WEAK/NEUTRAL)
3. `meta_confidence` ≥ ngưỡng (mặc định **85%**)
4. `signal_score` ≥ 75
5. Không có vị thế cùng chiều đang mở
6. Circuit Breaker & daily limit bình thường
7. Causal Gate không override → NEUTRAL

### 8.2. Position Sizing (Fixed-Fractional Risk)
$$Risk\_USDT = Account\_USDT \times 2\%$$
$$Position = \frac{Risk\_USDT}{SL\_Distance\%}$$

Min: 10 USDT / Max: 100 USDT

### 8.3. Circuit Breaker
- **Daily limit**: 5 lệnh/ngày
- **Consecutive loss gate**: 5 lệnh thua liên tiếp → dừng 24h
- **Drawdown gate** (RiskManagerAgent): drawdown > 10% → tất cả tín hiệu → NEUTRAL

### 8.4. Auto Close
- Mỗi 5 phút: kiểm tra giá vs SL/TP của vị thế `[AUTO-...]`
- SL hit → Market close + "LOSS" vào Circuit Breaker + Telegram alert
- TP2 hit → Market close + "WIN" + Telegram

---

## 9. Portfolio Optimization & Multi-Agent

### 9.1. Portfolio Sizing (khi ≥ 2 tín hiệu đồng thời)
1. **Tương quan returns**: ma trận covariance 100 nến 15m gần nhất.
2. **MVO**: Tối đa hóa Sharpe dựa trên expected returns (meta_confidence) và covariance.
3. **Risk Parity**: Cân bằng đóng góp rủi ro của mỗi tài sản.

### 9.2. Kiến trúc 6-Agent

| Agent | Vai trò |
|-------|---------|
| `MarketAnalystAgent` | Phân tích 15m + MTF, HTF trend summary |
| `SignalGeneratorAgent` | ML scoring + Causal Context Bridge + CausalGate |
| `RiskManagerAgent` | Drawdown cap, chuỗi thua, risk multiplier |
| `PortfolioManagerAgent` | MVO/Risk Parity allocation |
| `RLExitAgent` | PPO model loader, shadow mode |
| `ExecutionAgent` | CCXT async, shadow log, CounterfactualEngine |

---

## 10. Kết quả Backtest v2 (Tham khảo)

```bash
python -X utf8 backtest_eval.py
```

| Nhóm tín hiệu | Hold tối ưu | Win Rate | Profit Factor |
|---------------|------------|---------|---------------|
| **STRONG BUY** | 1h (4 nến) | **70.5%** | **2.95** |
| **STRONG SELL** | 6h (24 nến) | **66.4%** | **2.92** |
| WEAK BUY | — | ~35% | 0.24 |
| WEAK SELL | — | ~25% | 0.54 |

**Sub-type hiệu quả nhất**:
* BUY — **RSI Reversal** (72.4% WR, hold 1h): 86% tổng tín hiệu BUY
* SELL — **EMA Death Cross** (87.1% WR, hold 4h) và **Break SMA50** (87.1% WR, hold 6h)
