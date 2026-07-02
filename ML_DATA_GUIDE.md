# ML Data Preparation, Training & Causal Integration Guide

> **Cập nhật lần cuối**: 02/07/2026 — Thêm Causal Dataset Schema, CausalDiscovery workflow, Phase 3.0-D data pipelines

Hướng dẫn chuẩn bị dữ liệu cho ML training, RAG (Retrieval-Augmented Generation) và Causal World Model trong hệ thống `besttime-crypto`.

---

## 📊 Scripts Chuẩn Bị Dữ Liệu

### 1. `scripts/prepare_ml_data.py` — Xuất dataset ML

Chuyển đổi lịch sử giao dịch đã đóng thành dataset cấu trúc cho ML training.

```bash
python scripts/prepare_ml_data.py
```

**Output:**
- `data/ml_training_data.csv` — Dataset 30+ cột:
  - Cơ bản: `coin`, `direction`, `entry_price`, `sell_price`, `pnl_pct`, `result`
  - Kỹ thuật: `entry_distance_to_sl_pct`, `entry_distance_to_tp1_pct`, `suggested_rr1`
  - Causal: `causal_risk_level`, `causal_alpha`, `causal_context_skipped`
  - Thời gian: `hold_hours`
  - Nhãn: `is_win` (0/1)

- `data/ml_rag_context.json` — RAG context cấu trúc:
  - Global stats: Win rate, avg PnL, profit factor
  - Per-coin stats: Win rate, avg PnL, 3 lệnh gần nhất
  - Directional stats: LONG vs SHORT performance
  - Signal stats: Win rate per signal type
  - Causal stats: Win rate per risk level (LOW/MEDIUM/HIGH/CRITICAL)

### 2. `scripts/generate_rag_prompts.py` — Sinh RAG narratives

```bash
python scripts/generate_rag_prompts.py
```

**Output:**
- `data/rag_prompts.md` — Markdown narratives cho Gemini AI:
  - Tóm tắt toàn cục + per-coin
  - Phân tích LONG vs SHORT
  - Cảnh báo tín hiệu yếu
  - Causal risk level distribution

---

## 🔄 Quy trình Chuẩn Bị Dữ Liệu Đầy Đủ

### Bước 1: Thu thập dữ liệu

```bash
# Chạy bot để tích lũy lệnh
python main.py

# Đóng lệnh khi ready
./pos close BTC 65000

# Hoặc fetch dữ liệu lịch sử bulk
python fetch_historical_range.py
```

### Bước 2: Xuất dataset

```bash
python scripts/prepare_ml_data.py
head -5 data/ml_training_data.csv
cat data/ml_rag_context.json | python -m json.tool | head -30
```

### Bước 3: Sinh RAG prompts

```bash
python scripts/generate_rag_prompts.py
cat data/rag_prompts.md
```

### Bước 4: Parallel build per-coin + merge

```bash
# Build signals per-coin song song (auto-detect coins từ config.py)
python scripts/build_coins_parallel.py --jobs 8

# Gộp outputs per-coin vào file dataset chung
python scripts/merge_adaptive_signals.py

# Train meta-model (--skip-build để tránh rebuild)
python scripts/build_and_train.py --skip-build --n 200
```

### Bước 5: Continuous Learning (tự động hàng tuần)

```bash
python scripts/continuous_learning.py
```

Script này sẽ:
1. Lấy OHLCV 30 ngày gần nhất + warmup period.
2. Mô phỏng backtest → tự gán nhãn WIN/LOSS.
3. Huấn luyện lại RandomForest → LightGBM → CatBoost → XGBoost ensemble.
4. Cross-Validation ROC-AUC (Concept Drift check ≥ 0.55 → auto-deploy).
5. Gửi báo cáo kết quả lên Telegram.

> *Đã được tự động lên lịch 23:30 Chủ Nhật hàng tuần trong `main.py`.*

---

## 📈 Lộ trình ML (Tất cả đã hoàn thành)

### Phase 1: Feature Engineering & Signal Confidence ✅
- **18 tháng dữ liệu** (01/2025 - 06/2026), **18,908 mẫu giao dịch đóng**.
- `fetch_historical_range.py` → cào dữ liệu lịch sử Binance.
- `train_april_model.py` → train RandomForest + lưu `logs/adaptive_model.joblib`.
- Calibration buckets 5 nhóm xác suất → `logs/meta_model.json`.

### Phase 2: Ensemble ML ✅
- `EnsembleMetaModel`: RandomForest + LightGBM + CatBoost + XGBoost.
- Probability Calibration (Platt Sigmoid / Isotonic Regression).
- **CV ROC-AUC: 0.6355 ± 0.0081**; Holdout: 0.642.

### Phase 3: Dynamic Tuning & Risk Management ✅
- Optuna Bayesian Optimization hàng tuần (`scripts/optimize_hyperparameters.py`).
- ATR multipliers, signal cutoff, kelly multiplier, regime scaling.
- `RiskManager`: drawdown < 10%, consecutive loss streak gate.

### Phase 4: RL Exit Manager ✅
- Gymnasium environment (`rl_trading_env.py`): 18D state / 6 actions.
- PPO training (`train_rl_exit_manager.py`) → `logs/rl_models/`.
- Evaluation vs rule-based (`evaluate_rl_phase4.py`).

### Phase 5: Portfolio Optimization & Multi-Agent ✅
- MVO + Risk Parity (`portfolio_manager.py`).
- 6-Agent system: `AgentOrchestrator` điều phối tuần tự.

### Phase 6+: Causal World Model ✅ (Phases 2.1 → D)
- **196/196 integration tests PASSED**.
- Chi tiết xem: [causal_implementation_plan.md](causal_implementation_plan.md).

---

## 🧠 Causal Dataset Schema (mới — Phase 3.0+)

Dataset training nên bổ sung các cột causal để phân tích tương quan hiệu quả:

```python
# Causal context features (ghi nhận từ SignalGeneratorAgent)
causal_risk_level        # "LOW" / "MEDIUM" / "HIGH" / "CRITICAL"
causal_alpha             # CAUSAL_ALPHA khi tạo tín hiệu (0.0, 0.1, ...)
causal_overridden        # bool: True nếu CausalGate override → NEUTRAL
causal_context_skipped   # bool: True nếu provider không áp dụng context
context_adjustment       # float: adjusted_posterior - original_posterior
context_risk_raw         # float: raw risk score từ ContextReport

# Macro state (từ WorldState khi tạo tín hiệu)
world_DXY                # US Dollar Index tại thời điểm tín hiệu
world_VIX                # VIX tại thời điểm tín hiệu
world_FearGreed          # Fear & Greed khi tạo tín hiệu
world_BTC_Funding        # Funding rate BTC
world_regime             # MarketRegime: risk_on / risk_off / transitioning

# Counterfactual (từ logs/counterfactual_log.json — Phase D)
cf_delta_pnl             # Difference giữa actual PnL và counterfactual PnL
cf_intervention_node     # Node bị shock (VD: "DXY")
cf_intervention_value    # Magnitude của shock (+5.0)
```

**Phân tích đề xuất từ causal dataset:**
```python
# Win rate theo causal risk level
df.groupby("causal_risk_level")["is_win"].mean()
# → Kỳ vọng: LOW > MEDIUM > HIGH > CRITICAL

# Counterfactual impact
df[df["causal_overridden"] == True]["pnl_pct"].mean()
# → Các lệnh bị override nên thua nhiều → confirms CausalGate is working

# Alpha blending impact
df.groupby(pd.cut(df["causal_alpha"], [0, 0.1, 0.3, 0.5, 1.0]))["is_win"].mean()
```

---

## 🔍 CausalDiscovery Data Workflow

`CausalDiscoveryEngine` tự động phát hiện mối quan hệ nhân quả từ dữ liệu lịch sử:

```bash
# Chạy weekly discovery (khuyến nghị khi có ≥ 6 tháng data)
python -c "
from btc_scraper.ml_engine.causal_discovery import CausalDiscoveryEngine
engine = CausalDiscoveryEngine()
result = engine.discover()
print(f'Discovered {len(result[\"new_edges\"])} new edges')
"
```

**Discovery pipeline**:
1. Load lịch sử macro + crypto time series.
2. Lagged correlation analysis (lag 1-24h).
3. Simplified Granger causality test.
4. Write discovered edges vào `data/causal_graph.json` với `source="learned"`.
5. **Không bao giờ ghi đè manual edges** (`source="manual"`).

**Config** (`data/context_rules.json`):
```json
{
  "enable_learned_rules": false,  // true sau khi review discovered edges
  "causal_discovery_min_confidence": 0.6,
  "causal_discovery_max_lag_hours": 24
}
```

---

## 🤖 RAG Integration (Gemini AI)

### Current Implementation

`btc_scraper/ai_analyst/` đã dùng RAG từ `logs/closed_positions.json` và ML dataset để enrich Gemini prompt:
- Win rate & average PnL theo coin
- Hiệu suất LONG/SHORT
- Causal risk level distribution trong recent decisions
- Counterfactual insights từ `logs/counterfactual_log.json`

### Improved RAG Pipeline

```python
import json
from pathlib import Path

# Load structured RAG context
rag = json.loads(Path("data/ml_rag_context.json").read_text())
cf_log = json.loads(Path("logs/counterfactual_log.json").read_text())

# Build prompt section
prompt = f"""
=== LỊCH SỬ GIAO DỊCH (RAG) ===
Win Rate toàn hệ thống: {rag['global_stats']['win_rate']:.1%}
Profit Factor: {rag['global_stats']['profit_factor']:.2f}
Causal CRITICAL overrides gần đây: {rag.get('causal_stats', {}).get('critical_count', 0)}

=== COUNTERFACTUAL INSIGHTS ===
{len(cf_log)} phân tích lệnh thua được ghi nhận.
Avg delta PnL nếu DXY tăng +5%: {sum(r['delta_pnl'] for r in cf_log[-5:]) / max(len(cf_log[-5:]), 1):.2f} USD
"""
```

### UI Integration
- `api/server.py` exposes `/api/ai-analysis` và `/api/meta-model`.
- Dashboard hiển thị AI reports từ `data/latest_ai_analysis.json`.
- Causal monitoring metrics từ `btc_scraper/ml_engine/causal_monitoring.py`.

---

## 📁 File Structure (Đầy đủ)

```
data/
├── ml_training_data.csv       ← Dataset cho model training
├── ml_rag_context.json        ← Structured RAG context
├── rag_prompts.md             ← Markdown narratives cho Gemini AI
├── causal_graph.json          ← Knowledge graph (v2.0): manual + learned edges
├── context_rules.json         ← Context rules config + enable_learned_rules flag
├── tracked_signals.json       ← Persistent signal tracker state (TTL 90m)
├── latest_signals.json        ← Latest analysis snapshot (read by Dashboard)
└── latest_ai_analysis.json    ← Latest Gemini AI report (read by Dashboard)

logs/
├── closed_positions.json      ← Append-only closed trade log (RAG source)
├── counterfactual_log.json    ← Phase D: Counterfactual analysis (max 200 records)
├── auto_trade_log.json        ← CCXT auto trade audit log
├── auto_trade_circuit.json    ← Circuit Breaker state
├── adaptive_model.joblib      ← Trained Adaptive ML model
├── meta_model.json            ← Meta confidence calibration buckets
├── adaptive_signals_v2.json   ← Merged ML training dataset
└── rl_models/
    └── rl_exit_ppo_*.zip      ← PPO model checkpoints

scripts/
├── prepare_ml_data.py         ← Xuất CSV + RAG context
├── generate_rag_prompts.py    ← Sinh markdown narratives
├── continuous_learning.py     ← Weekly auto-retrain (Concept Drift check)
├── weekly_job.py              ← Weekly report generator
├── build_coins_parallel.py    ← Parallel per-coin build
├── merge_adaptive_signals.py  ← Merge per-coin datasets
└── build_and_train.py         ← Full build + train pipeline
```

---

## ⚙️ Cách Tính Các Cột Kỹ Thuật Chính

### `entry_distance_to_sl_pct`
```
= |entry_price - suggested_sl| / entry_price * 100
```
SL gần (thấp) = rủi ro cao; SL xa (cao) = rủi ro thấp.

### `suggested_rr1` (Risk:Reward ratio cho TP1)
```
= |suggested_tp1 - entry_price| / |entry_price - suggested_sl|
```
Target > 1.5 là tốt, > 2.0 là xuất sắc.

### `causal_risk_level` → `is_win` correlation
```python
# Kỳ vọng: LOW risk → win rate cao hơn CRITICAL risk
df.groupby("causal_risk_level")["is_win"].agg(["mean", "count"])
```

### `cf_delta_pnl` (Counterfactual PnL delta)
```
= counterfactual_pnl - actual_pnl
```
Dương = nếu DXY tăng thêm, lệnh sẽ tốt hơn.
Âm = DXY tăng sẽ làm lệnh tệ hơn → macro exposure cao.

---

## 🎯 Best Practices

1. **Chạy `prepare_ml_data.py` định kỳ** — hàng tuần hoặc sau 5+ lệnh đóng mới.
2. **Review `rag_prompts.md`** — kiểm tra cảnh báo causal risk cao bất thường.
3. **Bắt đầu ML training khi ≥ 50 lệnh** — sample nhỏ dễ overfit.
4. **Validate trên test set** — không train trên toàn bộ dữ liệu.
5. **A/B test model mới** — shadow mode 2-4 tuần trước khi deploy live.
6. **Weekly CausalDiscovery** — review discovered edges trước khi `enable_learned_rules=true`.
7. **Monitor `counterfactual_log.json`** — nếu avg delta_pnl âm lớn → hệ thống nhạy cảm với macro shock.
8. **CAUSAL_ALPHA rollout**: 0.0 (safe) → 0.1 (sau shadow validation) → 0.2-0.3 (dần dần).

---

## 📞 Troubleshooting

**Q: Script báo "Không tìm thấy dữ liệu lệnh đã đóng"**
A: Chạy `./pos close BTC 65000` để tạo dữ liệu, hoặc dùng `fetch_historical_range.py`.

**Q: `ml_training_data.csv` bị rỗng**
A: Kiểm tra `logs/closed_positions.json`. Nếu thiếu, tạo lệnh bằng `./pos add BTC 65000`.

**Q: `counterfactual_log.json` không có dữ liệu**
A: ExecutionAgent chỉ chạy CounterfactualEngine khi có losing trades (PnL < -0.5%). Đảm bảo `position_tracker.get_performance_summary("ALL")` trả về trades.

**Q: CausalDiscovery không tìm thấy edges mới**
A: Cần ít nhất 3-6 tháng data với đủ variance trong macro indicators. Tăng lookback period hoặc giảm `causal_discovery_min_confidence`.

**Q: Làm sao thêm cột kỹ thuật mới vào dataset?**
A: Sửa hàm `normalize_trade()` trong `prepare_ml_data.py`, thêm vào `FIELDNAMES`. Sau đó retrain model với feature mới.

**Q: `CAUSAL_ALPHA` nên đặt bao nhiêu?**
A: Bắt đầu 0.0 (rule-only, safe). Sau 2-4 tuần shadow mode với đủ dữ liệu, thử 0.1. Tăng dần sau khi xác nhận shadow PnL cải thiện.
