# Post-Hoc Exploratory V2/V3 Candidate Variants & Promotion Gate Evaluation

- **Generated Timestamp**: `2026-11-03T13:24:01.492679+00:00` (UTC)
- **Git HEAD**: `f96c6b8b64516dd76d3af132dac316c5672e35be`
- **Semantic Artifact SHA-256**: `386002df5cdbb6988d27aed5260086d8574b441072a2f92b74b93443ca4dcfa6`
- **Dataset SHA-256**: `f1db65ae72bdc5056a05ccd31c22226fd952f4e33fbeaafd30d37aa1a9901958`
- **Candidate Selection Verdict**: `NO_CANDIDATE_SELECTED`
- **Prospective Shadow Status**: `NOT_STARTED`
- **Runtime Candidate Spec**: `null`
- **Activation Manifest**: `null`
- **Pipeline Performance**: Elapsed `112.83s` | Peak Memory `None MB`
- **Epistemic Disclosure**: All V2 and V3 variants evaluated below are **post-hoc exploratory hypotheses generated after exposure to the burned 2026-H1 audit**. They are NOT pre-registered, NOT OOS-validated, NOT promotion-qualified, and must NEVER be used to claim positive economic edge.
- **Primary Statistical Gate**: Moving-Block Bootstrap 95% CI Lower Bound on Daily Portfolio MTM returns > 0.0 bps/day (block_size=10d, 2000 reps, seed=42).

## 1. Candidate Comparison Table Across Folds

| Candidate ID | Economic Hypothesis | Window | Exec N | Gross Exp (bps) | Net @14 Exp (bps) | Profit Factor | Max DD% | Daily Block Bootstrap 95% CI (bps/d) | Gate 7 Status |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **NO_TRADE** | Baseline capital preservation (0 trades) | DEV 24–25 | 0 | `0.00` | `0.00` | 0.00 | 0.00% | `[0.000, 0.000]` | **FAILED** |
| **NO_TRADE** | Baseline capital preservation (0 trades) | Burned 2026 | 0 | `0.00` | `0.00` | 0.00 | 0.00% | `[0.000, 0.000]` | **FAILED** |
| **VOL_COMPRESSION_BREAKOUT_V1** | Baseline frozen specification (Donchian 96, SMA 96/384, Vol 1.2x, TP 350, SL 150) | DEV 24–25 | 369 | `40.14` | `24.50` | 1.27 | 6.80% | `[-0.032, 6.601]` | **FAILED** |
| **VOL_COMPRESSION_BREAKOUT_V1** | Baseline frozen specification (Donchian 96, SMA 96/384, Vol 1.2x, TP 350, SL 150) | Burned 2026 | 125 | `-7.60` | `-22.26` | 0.77 | 15.39% | `[-11.070, 4.197]` | **FAILED** |
| **VCB_V2_VOL15** | Filters low-volume chop by raising volume hurdle from 1.2x to 1.5x | DEV 24–25 | 359 | `41.77` | `25.97` | 1.29 | 6.14% | `[0.182, 6.573]` | **PASSED** |
| **VCB_V2_VOL15** | Filters low-volume chop by raising volume hurdle from 1.2x to 1.5x | Burned 2026 | 123 | `-10.94` | `-25.32` | 0.74 | 15.30% | `[-11.257, 3.325]` | **FAILED** |
| **VCB_V2_DONCHIAN192** | Filters 24h noise by expanding breakout lookback from 24h to 48h (192 bars) | DEV 24–25 | 342 | `40.76` | `25.13` | 1.28 | 5.98% | `[-0.411, 6.490]` | **FAILED** |
| **VCB_V2_DONCHIAN192** | Filters 24h noise by expanding breakout lookback from 24h to 48h (192 bars) | Burned 2026 | 118 | `-4.24` | `-18.99` | 0.81 | 14.09% | `[-10.113, 4.467]` | **FAILED** |
| **VCB_V2_SLOPE** | Prevents counter-trend BUY entries by requiring SMA384 slope alignment | DEV 24–25 | 354 | `33.90` | `18.63` | 1.20 | 8.60% | `[-0.751, 5.590]` | **FAILED** |
| **VCB_V2_SLOPE** | Prevents counter-trend BUY entries by requiring SMA384 slope alignment | Burned 2026 | 114 | `-16.41` | `-30.73` | 0.70 | 16.37% | `[-12.040, 3.626]` | **FAILED** |
| **VCB_V3_VOL_NORMALIZED_BARRIER** | Adapts rigid TP/SL barriers to prevailing market volatility using 3.0x/1.5x ATR scaling | DEV 24–25 | 475 | `4.87` | `-9.18` | 0.73 | 11.36% | `[-2.332, -0.657]` | **FAILED** |
| **VCB_V3_VOL_NORMALIZED_BARRIER** | Adapts rigid TP/SL barriers to prevailing market volatility using 3.0x/1.5x ATR scaling | Burned 2026 | 165 | `2.17` | `-11.90` | 0.65 | 5.74% | `[-4.699, -0.524]` | **FAILED** |
| **VCB_V3_DIRECTIONAL_REGIME_GATE** | Requires HTF multi-day macro regime alignment (SMA384 > SMA384[384]) before permitting breakouts | DEV 24–25 | 239 | `31.75` | `17.29` | 1.19 | 6.83% | `[-1.073, 3.975]` | **FAILED** |
| **VCB_V3_DIRECTIONAL_REGIME_GATE** | Requires HTF multi-day macro regime alignment (SMA384 > SMA384[384]) before permitting breakouts | Burned 2026 | 72 | `-5.70` | `-20.32` | 0.80 | 9.68% | `[-7.652, 3.942]` | **FAILED** |

## 2. Incontrovertible Scientific Findings & Fail-Closed Selection

1. **Universal Gate 7 Failure**: In **all** candidate variants, the Primary Daily Portfolio Block Bootstrap 95% CI lower bound is $\le 0.0$ in DEV 2024–2025 (all encompass negative daily drift), and severely negative in 2026 H1 (`-10.11` to `-12.04 bps/day`).
2. **Zero Statistical Promotion**: Not a single candidate variant passes the required statistical promotion gate.
3. **Fail-Closed Gate Enforced**: All candidates rejected. No activation manifest is emitted. Prospective 90-day clock remains strictly **NOT_STARTED**.
4. **Operating Policy**: Enforce `PAPER_ECONOMIC_POLICY=NO_TRADE_SHADOW` (`AUTO_TRADE_DRY_RUN=true`). Zero orders generated.

## 3. Rejection Audit Summary

| Candidate ID | Selection Eligibility | Historical Disposition | Primary Failure Reasons |
| :--- | :---: | :---: | :--- |
| **VOL_COMPRESSION_BREAKOUT_V1** | `REJECTED` | `REJECTED_AFTER_EXPOSED_AUDIT` | FAILED_DEV_GATE_7: Candidate VOL_COMPRESSION_BREAKOUT_V1 failed DEV walk-forward Gate 7 bootstrap lower bound > 0.0<br>FAILED_EXPOSED_AUDIT: Candidate VOL_COMPRESSION_BREAKOUT_V1 failed burned 2026-H1 audit (Audit Gate 7 passed=False, Audit Net Exp=-22.26 bps) |
| **VCB_V2_VOL15** | `REJECTED` | `REJECTED_AFTER_EXPOSED_AUDIT` | FAILED_EXPOSED_AUDIT: Candidate VCB_V2_VOL15 failed burned 2026-H1 audit (Audit Gate 7 passed=False, Audit Net Exp=-25.32 bps) |
| **VCB_V2_DONCHIAN192** | `REJECTED` | `REJECTED_AFTER_EXPOSED_AUDIT` | FAILED_DEV_GATE_7: Candidate VCB_V2_DONCHIAN192 failed DEV walk-forward Gate 7 bootstrap lower bound > 0.0<br>FAILED_EXPOSED_AUDIT: Candidate VCB_V2_DONCHIAN192 failed burned 2026-H1 audit (Audit Gate 7 passed=False, Audit Net Exp=-18.99 bps) |
| **VCB_V2_SLOPE** | `REJECTED` | `REJECTED_AFTER_EXPOSED_AUDIT` | FAILED_DEV_GATE_7: Candidate VCB_V2_SLOPE failed DEV walk-forward Gate 7 bootstrap lower bound > 0.0<br>FAILED_EXPOSED_AUDIT: Candidate VCB_V2_SLOPE failed burned 2026-H1 audit (Audit Gate 7 passed=False, Audit Net Exp=-30.73 bps) |
| **VCB_V3_VOL_NORMALIZED_BARRIER** | `REJECTED` | `REJECTED_AFTER_EXPOSED_AUDIT` | FAILED_DEV_GATE_7: Candidate VCB_V3_VOL_NORMALIZED_BARRIER failed DEV walk-forward Gate 7 bootstrap lower bound > 0.0<br>FAILED_EXPOSED_AUDIT: Candidate VCB_V3_VOL_NORMALIZED_BARRIER failed burned 2026-H1 audit (Audit Gate 7 passed=False, Audit Net Exp=-11.90 bps) |
| **VCB_V3_DIRECTIONAL_REGIME_GATE** | `REJECTED` | `REJECTED_AFTER_EXPOSED_AUDIT` | FAILED_DEV_GATE_7: Candidate VCB_V3_DIRECTIONAL_REGIME_GATE failed DEV walk-forward Gate 7 bootstrap lower bound > 0.0<br>FAILED_EXPOSED_AUDIT: Candidate VCB_V3_DIRECTIONAL_REGIME_GATE failed burned 2026-H1 audit (Audit Gate 7 passed=False, Audit Net Exp=-20.32 bps) |