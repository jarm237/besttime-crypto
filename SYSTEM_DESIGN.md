# AI Quant Trading System Design Document (TDD)

Tài liệu này đóng vai trò là **Technical Design Document (TDD)** tổng thể, mô tả toàn bộ kiến trúc, luồng dữ liệu, feature engineering và định hướng phát triển từ một Signal Bot thành nền tảng **AI Quant Trading Platform** hoàn chỉnh.

---

## 1. Architecture Diagram

Sơ đồ kiến trúc tổng thể mô tả luồng xử lý từ dữ liệu thị trường cho đến bước thực thi lệnh tự động.

```text
Market Data (Binance OHLCV)
            │
            ▼
Indicator Engine
(ATR, RSI, EMA, SMA, MACD, BB)
            │
            ▼
Signal Engine (7 Layers)
            │
            ▼
Feature Extractor
            │
            ▼
Meta Model (RF/Ensemble)
            │
            ▼
Signal Scoring
(meta_confidence)
            │
            ▼
Risk Manager
(Position Sizing, Circuit Breaker)
            │
            ▼
Portfolio Optimizer
            │
            ▼
Execution Engine (CCXT)
            │
            ▼
Position Manager
            │
            ▼
RL Exit Agent
            │
            ▼
Dashboard + Telegram + API
```

---

## 2. Data Pipeline

### 2.1. Data Flow

Luồng dữ liệu liên tục phục vụ cho quá trình **Continuous Learning**.

```text
Binance API
      │
      ▼
OHLCV Cache
      │
      ▼
Feature Extraction
      │
      ▼
Signal Generation
      │
      ▼
Trade Execution
      │
      ▼
Closed Positions
      │
      ▼
ML Dataset
      │
      ▼
Continuous Learning
```

### 2.2. Dataset Schema

Dữ liệu được chuẩn hoá thành một bộ khung (schema) rõ ràng để hỗ trợ Retrain, Feature Selection, Explainable AI và Dataset Versioning.

```python
timestamp               # Thời gian đóng nến
coin                    # Ký hiệu (VD: BTCUSDT)
direction               # Chiều vị thế (LONG / SHORT)
signal_score            # Điểm tín hiệu rule-based
rsi                     # Relative Strength Index
macd_hist               # MACD Histogram
atr_pct                 # Normalized ATR (độ biến động)
volume_ratio            # Đột biến thanh khoản
fear_greed              # Chỉ số F&G Index (-1.0 đến 1.0)
ema_distance_pct        # Khoảng cách từ giá đến đường EMA
bb_width_pct            # Độ nén Bollinger Bands
adx                     # Sức mạnh xu hướng
mtf_alignment           # Đồng thuận đa khung thời gian
regime                  # Trạng thái thị trường
meta_confidence         # Xác suất chiến thắng (mô hình AI dự đoán)
entry_price             # Giá vào lệnh
sl_price                # Giá Stop Loss
tp_price                # Giá Take Profit
hold_hours              # Thời gian giữ lệnh (giờ)
is_win                  # Label mục tiêu (1 = Win, 0 = Loss)
```

---

## 3. Feature Engineering Roadmap

Hệ thống đang mở rộng bộ đặc trưng kỹ thuật từ **14 Features** lên **40-60 Features** để tăng cường sức mạnh phán đoán cho các mô hình Machine Learning.

### Momentum
```python
return_15m
return_1h
return_4h
return_1d
roc_14
roc_50
```

### Trend
```python
ema9_slope
ema21_slope
sma50_slope
sma200_slope
trend_strength
```

### Volatility
```python
realized_vol_20
realized_vol_50
atr_percentile
hv20
hv60
```

### Liquidity
```python
obv
cmf
mfi
volume_percentile
volume_acceleration
```

### Market Structure
```python
distance_support
distance_resistance
higher_high
lower_low
bos
choch
```

---

## 4. Explainable AI (XAI)

XAI được áp dụng để đảm bảo AI Quant Trading không phải là một "hộp đen", cho phép giải thích được lý do đằng sau các quyết định vào lệnh.

### Feature Importance
Đánh giá mức độ quan trọng của đặc trưng trực tiếp từ cây quyết định:
```python
RandomForest.feature_importances_
```

### SHAP (SHapley Additive exPlanations)
Phân tích chi tiết mức đóng góp của từng feature vào một dự đoán cụ thể:
```python
shap.TreeExplainer
```

### Permutation Importance
Đo lường độ sụt giảm độ chính xác của model khi giá trị của một tính năng bị xáo trộn:
```python
sklearn.inspection.permutation_importance
```

**Tích hợp Dashboard:**
- Top Alpha Features (Những đặc trưng mang lại lợi thế cao nhất)
- Feature Drift (Cảnh báo khi phân phối dữ liệu đầu vào bị lệch)
- Feature Correlation (Mức độ tương quan giữa các đặc trưng)

---

## 5. Dynamic Position Sizing

Thay vì rủi ro cố định `Risk = 2%` cho mọi lệnh, hệ thống sử dụng **Kelly Fraction** để phân bổ vốn tối ưu dựa trên độ tin cậy của lệnh. Rõ ràng, một tín hiệu có `95% confidence` phải được vào vốn mạnh hơn so với `85% confidence`.

### Kelly Fraction Formula

$$f^* = \frac{bp - q}{b}$$

Trong đó:
- **b** = Reward/Risk Ratio (Tỷ lệ lợi nhuận / rủi ro)
- **p** = `meta_confidence` (Xác suất thắng dự đoán bởi AI)
- **q** = $1 - p$ (Xác suất thua)

**Triển khai:**
```python
# Giảm hệ số Kelly (Fractional Kelly) để quản trị rủi ro tốt hơn
position_size = 0.25 * kelly_fraction
```

---

## 6. Walk Forward Validation

Thay vì sử dụng k-fold CV truyền thống (gây rò rỉ dữ liệu trong chuỗi thời gian), hệ thống áp dụng kỹ thuật cửa sổ trượt để kiểm thử liên tục.

**Sliding Window Strategy:**
```text
Train: Jan-Jun  -->  Test: Jul
Train: Feb-Jul  -->  Test: Aug
Train: Mar-Aug  -->  Test: Sep
...
```

**Các Metrics đo lường hiệu năng:**
- ROC-AUC
- Accuracy, Precision, Recall, F1-Score
- Profit Factor
- Sharpe Ratio
- Max Drawdown (MDD)

---

## 7. Market Regime Engine v2

Nâng cấp bộ phân tích cấu trúc vĩ mô để đánh giá sâu hơn về "Thời tiết thị trường".

**Các trạng thái:**
```text
Strong Trend
Weak Trend
Compression
Breakout
Mean Reversion
Panic Sell
Low Liquidity
Pump Risk
```

**Tác động của Regime:**
- **TP/SL**: Nới rộng biên độ TP trong `Strong Trend`, đánh nhanh thắng nhanh trong `Ranging`.
- **Position Size**: Giảm khối lượng khi `Low Liquidity` hoặc `Panic Sell`.
- **Meta Threshold**: Tăng độ khó khi ra quyết định trong thị trường nhiễu.
- **RL Reward**: Thay đổi hàm thưởng cho tác tử (agent) thoát lệnh tự động.

---

## 8. Portfolio Metrics

Hệ thống đánh giá hiệu suất rủi ro tổng thể của danh mục bằng các chỉ số chuyên sâu thay vì chỉ tập trung vào PnL tuyệt đối.

### Sharpe Ratio
Đo lường lợi nhuận vượt trội trên mỗi đơn vị rủi ro tổng thể.
$$S = \frac{R_p - R_f}{\sigma_p}$$

### Sortino Ratio
Đo lường lợi nhuận trên mỗi đơn vị rủi ro giảm giá (chỉ tính những lệnh lỗ).
```text
Sortino = (Rp − Rf) / DownsideDeviation
```

### Maximum Drawdown (MDD)
Sự sụt giảm tài khoản lớn nhất từ mức đỉnh.
```text
MDD = (Peak − Trough) / Peak
```

### Calmar Ratio
Đo lường sự ổn định của lợi nhuận so với rủi ro sụt giảm cực đại.
```text
Calmar = CAGR / MaxDrawdown
```

---

## 9. Online Learning Workflow

Quy trình tự động tinh chỉnh (fine-tuning) model với dữ liệu thị trường mới nhất.

```text
Closed Trade
      │
      ▼
Append Dataset
      │
      ▼
Feature Validation
      │
      ▼
Retrain Candidate Model
      │
      ▼
Walk Forward Evaluation
      │
      ▼
Concept Drift Detection
      │
      ▼
Deploy New Model
      │
      ▼
Shadow Prediction
      │
      ▼
Production
```

---

## 10. Lộ trình phát triển tổng thể (Roadmap)

```text
Phase 1
Feature Engineering + Regime Detection
        │
        ▼
Phase 2
Ensemble ML + Explainable AI
        │
        ▼
Phase 3
Dynamic TP/SL + Kelly Sizing
        │
        ▼
Phase 4
RL Exit Manager
        │
        ▼
Phase 5
Portfolio Optimization
        │
        ▼
Phase 6
Online Learning + Multi-Agent AI
        │
        ▼
AI Quant Trading Platform
```
