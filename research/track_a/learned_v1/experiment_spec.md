# Experiment Spec — Learned Policy v1

## 1. Overview & Scientific Objective
The objective of **Learned Policy v1** is to investigate whether a compact, unified learned neural policy directly optimized for post-fee wealth growth and downside risk can generate sustainable net profit after transaction costs and outperform the frozen Track A v1 Donchian benchmark.

## 2. Chronological Data Splits
To ensure strict statistical discipline and eliminate lookahead bias:

| Split Name | Window | Duration | Inception Capital | Role |
| :--- | :--- | :--- | :--- | :--- |
| **Warmup** | 2021-01-01 → 2021-12-31 | 365 days | N/A | Feature calculation lookback stabilization |
| **Train** | 2022-01-01 → 2023-12-31 | 730 days | $10,000 USDT | Policy fitting & feature scaling fit |
| **Validation** | 2024-01-01 → 2024-12-31 | 366 days | $10,000 USDT | Model selection & early stopping checkpoint |
| **Reused Test** | 2025-01-01 → 2026-11-18 | 687 days | $10,000 USDT | Reused historical diagnostic (not untouched OOS) |
| **Full Diagnostic** | 2022-01-01 → 2026-11-18 | 1783 days | $10,000 USDT | Continuous economic trajectory comparison |

> [!IMPORTANT]
> Because 2024–2026 was encountered during prior research stages, the Reused Test split is strictly an independent historical diagnostic rather than an untouched out-of-sample partition.

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

## 4. Policy Architecture & Optimization
- **Model:** `CompactUnifiedPolicy` (1409 parameters).
- **Inputs:** Normalized feature vector (23 dims) + previous portfolio BTC weight (1 dim).
- **Hidden Layers:** Linear(32) → LayerNorm → ReLU → Dropout(0.05) → Linear(16) → ReLU → Linear(1) → Sigmoid.
- **Output:** BTC Target Weight in [0, 1]; Cash Target Weight = 1 - BTC_TARGET_WEIGHT.
- **Loss Function:** Direct differentiable causal portfolio wealth rollout with 30 bps transaction cost deduction, downside penalty (lambda=2.0), and turnover penalty (lambda=0.05).
- **Optimizer:** AdamW, learning rate 1e-3, weight decay 1e-4.
