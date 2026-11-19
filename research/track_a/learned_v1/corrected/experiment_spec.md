# Experiment Spec — Learned Policy v1 (Corrected Economic Integrity)

## 1. Overview & Scientific Objective
The objective of **Learned Policy v1 (Corrected)** is to evaluate whether a compact neural policy mapping Point-in-Time causal features to a continuous BTC allocation creates genuine post-fee economic value after correcting for:
1. Label boundary leakage across chronological splits.
2. Synthetic zero-padding at terminal boundary.
3. Execution price conventions.
4. Capital conservation and trade notional reconciliation.
5. Comparisons against passive & periodic 50/50 BTC/Cash benchmarks.

## 2. Chronological Data Splits & Boundary Purging
To enforce strict leakage isolation:

| Split Name | Window | Labeled Days | Inception Capital | Role |
| :--- | :--- | :---: | :--- | :--- |
| **Warmup** | 2021-01-01 → 2021-12-31 | 365 | N/A | Feature calculation lookback stabilization |
| **Train** | 2022-01-01 → 2023-12-31 | 729 | $10,000 USDT | Policy fitting & feature scaling fit (purged at 2023-12-30) |
| **Validation** | 2024-01-01 → 2024-12-31 | 365 | $10,000 USDT | Model selection & checkpoint freeze (purged at 2024-12-30) |
| **Reused Test** | 2025-01-01 → 2026-11-18 | 686 | $10,000 USDT | Reused historical diagnostic (not untouched OOS) |
| **Full Diagnostic** | 2022-01-01 → 2026-11-18 | 1782 | $10,000 USDT | Continuous cumulative economic evaluation |

> [!IMPORTANT]
> - Decisions on 2023-12-31 are strictly purged from training labels because their next execution (2024-01-01 01:00 UTC) belongs to Validation.
> - Decisions on 2024-12-31 are strictly purged from validation selection labels because their next execution (2025-01-01 01:00 UTC) belongs to Reused Test.
> - The terminal date 2026-11-18 is dropped cleanly without appending synthetic 0.0 return.

## 3. Causal Feature Engineering
All features are computed Point-in-Time:
- **Decision Timestamp:** 00:00 UTC daily.
- **Available Data:** Only closed daily candles up to Day $D-1$ (closing at 23:59:59 UTC).
- **Execution Timestamp:** 01:00 UTC daily at bar open.
- **Universe:** BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT (Binance Spot audited hourly data).

### Feature Set (23 Features):
- Multi-horizon BTC returns: 1d, 3d, 7d, 14d, 30d.
- Realized volatility: 7d, 14d, 30d rolling standard deviation.
- Downside volatility: 14d, 30d semi-deviation of negative returns.
- Momentum: SMA(7)/SMA(30) ratio, SMA(20)/SMA(60) ratio, 14d Sharpe proxy.
- Volume: Volume(7d) / Volume(30d) liquidity proxy.
- Cross-asset returns: ETH, SOL, BNB 7d & 30d returns.
- Relative strength: BTC 7d & 30d excess return over altcoin basket.
- Cross-asset correlation: BTC-ETH 30d rolling correlation.

## 4. Policy Architecture
- **Model:** `CompactUnifiedPolicy` (1409 parameters).
- **Inputs:** Normalized feature vector (23 dims) + previous portfolio BTC weight (1 dim).
- **Hidden Layers:** Linear(32) → LayerNorm → ReLU → Dropout(0.05) → Linear(16) → ReLU → Linear(1) → Sigmoid.
- **Output:** BTC Target Weight in [0, 1]; Cash Target Weight = 1 - BTC_TARGET_WEIGHT.

## 5. Differentiable Surrogate Objective vs Actual Economic Replay
There is an intentional, fundamental distinction between the optimization loss and the evaluation replay:

1. **Differentiable Surrogate Objective (Training & Early Stopping):**
   - Direct gradient backpropagation requires smooth, continuous functions.
   - Computes daily compounding via $\sum_t \log(1 + r_{\text{net}, t})$ where $r_{\text{net}, t} = w_t \cdot r_{\text{fwd}, t} - \text{fee\_rate} \cdot |w_t - w_{t-1}|$.
   - Uses a smooth turnover penalty ($\lambda=0.05$) and downside semi-deviation penalty ($\lambda=2.0$).
   - Omits discrete deadband filtering (e.g. 5%) because hard threshold steps have zero gradients almost everywhere.

2. **Actual Fee-Aware Economic Replay (Evaluation & Benchmark Truth):**
   - Stateful hourly mark-to-market across 8,760 hours/year.
   - Path-dependent execution at 01:00 UTC with exact non-linear capital conservation solver `solve_post_fee_equity`:
     $$V_{\text{post}} = V_{\text{pre}} - \text{fee\_rate} \cdot |w_{\text{target}} V_{\text{post}} - N_{\text{pre}}|$$
   - Discrete 5% no-trade deadband filter to eliminate churn.
   - Strict solvency guarantee ($C_{\text{post}} \ge 0$, $H_{\text{post}} \ge 0$).

These two regimes are **not numerically identical**; the former is a surrogate proxy for training, while the latter is the definitive ground truth for capital accounting and economic verdicts.
