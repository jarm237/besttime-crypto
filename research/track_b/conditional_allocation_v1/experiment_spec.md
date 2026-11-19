# Experiment Spec — Track B1 Regime-Conditioned Capital Allocation

## 1. Overview & Falsifiable Economic Hypothesis (Hypothesis B1)
Track A v1 (Donchian 20/55/90) generates robust long-term compounding (+9.28% CAGR) but experiences substantial drawdowns (-42.08%) when holding exposure into severe corrections.
**Hypothesis B1:** A regime-conditioned allocation head that scales base exposure dynamically based on 90-day trend momentum, 30-day realized downside volatility, and 30-day multi-asset breadth will improve post-fee risk-adjusted wealth growth without increasing transaction churn.

## 2. Model Architecture & Monotonic Parameterization
- **Base Exposure:** Frozen Track A v1 approved exposure ($w_{\text{base}} \in \{0.0, 0.333, 0.667, 1.0\}$).
- **Features:**
  1. `trend_90d`: BTC 90-day log return, observing closed candle $D-1$.
  2. `downside_risk_30d`: BTC 30-day realized semi-deviation of negative daily log returns.
  3. `breadth_30d`: Fraction of [ETH, SOL, BNB] with positive 30-day return at Day $D-1$.
- **Allocation Head:**
  $$\text{logit} = \text{bias} + c_{\text{trend}} \cdot z_{\text{trend}} - c_{\text{risk}} \cdot z_{\text{risk}} + c_{\text{breadth}} \cdot z_{\text{breadth}}$$
  $$\text{risk\_gate} = \sigma(\text{logit}) \in (0, 1)$$
  $$\text{capital\_multiplier} = 0.5 + \text{risk\_gate} \in (0.5, 1.5)$$
  $$w_{\text{target}} = \text{clip}(w_{\text{base}} \times \text{capital\_multiplier}, 0.0, 1.0)$$
- **Monotonicity Enforcement:**
  $c_{\text{trend}}, c_{\text{risk}}, c_{\text{breadth}} = \text{softplus}(\theta) \ge 0$.
  Guarantees:
  - Higher trend $\implies$ non-decreasing exposure.
  - Higher downside risk $\implies$ non-increasing exposure.
  - Higher breadth $\implies$ non-decreasing exposure.
  - Base weight zero $\implies$ target weight strictly zero.

## 3. Strict Chronological Splits & Boundary Purging
- **Warmup:** 2021 (365 days) — Lookback stabilization.
- **Train:** 2022-01-01 → 2023-12-31 (Purged at 2023-12-30; 729 labeled samples).
- **Validation:** 2024-01-01 → 2024-12-31 (Purged at 2024-12-30; 365 labeled samples).
- **Reused Test:** 2025-01-01 → 2026-11-18 (686 labeled samples).
- **Full Diagnostic:** 2022-01-01 → 2026-11-18 (1782 labeled samples).

## 4. Fair Benchmark Controls
To confirm whether dynamic timing creates real alpha or merely scales down beta:
- **Constant-Multiplier Track A:** Evaluates Track A with a constant multiplier ($M_{\text{const}} = 1.0177$) determined strictly from Train.
- **Track A v1 Frozen:** Unmodified trend-following benchmark.
- **Learned Policy v1 Corrected:** Previous compact neural policy.
- **BTC 50/50 Rebalanced:** Naive periodic rebalanced allocation.
- **BTC Buy & Hold:** Passive market exposure.
- **Cash 100%:** Capital preservation.
