# VOL_COMPRESSION_BREAKOUT_V1: Economic Attribution & Edge Loss Decomposition

- **Generated Timestamp**: `2026-11-03T13:24:01.492679+00:00` (UTC)
- **Git HEAD**: `f96c6b8b64516dd76d3af132dac316c5672e35be`
- **Semantic Artifact SHA-256**: `1f363597633c3e17cda6b32bda6a02252f7e575d6058d23205160f8a8e7f10c3`
- **Dataset SHA-256**: `f1db65ae72bdc5056a05ccd31c22226fd952f4e33fbeaafd30d37aa1a9901958`
- **Spec SHA-256**: `1a6639922743bbd6ce12ba88e1a407df79171a3e564246696b112c7034f4ecc6`
- **System Operating Disposition**: `RUNTIME_READY, ECONOMIC_NO_GO, NO_TRADE_SHADOW`

## 1. Executive Summary & Period Comparison

| Metric | DEV Walk-Forward (2024–2025) | Burned Exposed Audit (2026 H1) | Delta (Audit - DEV) | Economic Interpretation |
| :--- | :---: | :---: | :---: | :--- |
| **Executed Trades ($N$)** | 369 | 125 | -244 | High sample volume in both periods |
| **Gross Expectancy (bps)** | `+40.14` | `-7.60` | `-47.74 bps` | Gross edge completely evaporated |
| **Net Expectancy @14 (bps)** | `+26.11` | `-21.59` | `-47.70 bps` | Severe negative net return |
| **Net PnL (USD)** | `+$2619.56` | `-$677.42` | `-$3296.98` | Capital drawdown in 2026 H1 |

## 2. Quantitative Decomposition by Dimension

### A. By Symbol

| Symbol | DEV N | DEV Gross (bps) | DEV Net @14 | Burned 2026 N | Burned Gross (bps) | Burned Net @14 | 2026 Net PnL ($) | 2026 WR% | Dollar Loss Share |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **BTC** | 163 | `+42.89` | `+28.86` | 49 | `-27.61` | `-41.59` | `$-514.96` | 28.6% | 76.0% |
| **BNB** | 128 | `+21.22` | `+7.21` | 45 | `-2.78` | `-16.78` | `$-206.87` | 37.8% | 30.5% |
| **ETH** | 78 | `+65.44` | `+51.39` | 31 | `+17.03` | `+3.02` | `$44.41` | 35.5% | -6.6% |

### B. By Side (Directional Asymmetry: BUY vs SELL)

| Side | DEV N | DEV Gross (bps) | DEV Net @14 | Burned 2026 N | Burned Gross (bps) | Burned Net @14 | 2026 Net PnL ($) | 2026 WR% |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **BUY** | 222 | `+45.44` | `+31.41` | 71 | `-27.08` | `-41.06` | `$-701.28` | 29.6% |
| **SELL** | 147 | `+32.14` | `+18.12` | 54 | `+18.02` | `+4.01` | `$23.86` | 38.9% |

### C. By Exit Reason & Barrier Dynamics (TP vs SL vs TIMEOUT)

| Exit Reason | DEV N (Share%) | DEV Net @14 | Burned 2026 N (Share%) | Burned Gross (bps) | Burned Net @14 | 2026 Avg Bars | 2026 Net PnL ($) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **TP** | 112 (30.4%) | `+335.75` | 21 (16.8%) | `+350.00` | `+335.75` | 65.2 | `$1713.19` |
| **SL** | 193 (52.3%) | `-163.89` | 72 (57.6%) | `-150.00` | `-163.89` | 58.8 | `$-2883.22` |
| **TIMEOUT** | 64 (17.3%) | `+57.23` | 32 (25.6%) | `+78.13` | `+64.08` | 192.0 | `$492.62` |

### D. By Holding Period Buckets

| Holding Period | DEV N | DEV Net @14 | Burned 2026 N | Burned Gross (bps) | Burned Net @14 | 2026 WR% |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `1-16_bars_le4h` | 49 | `-72.12` | 22 | `-36.36` | `-50.34` | 22.7% |
| `17-48_bars_4-12h` | 85 | `-11.06` | 25 | `-90.00` | `-103.94` | 12.0% |
| `49-96_bars_12-24h` | 98 | `+60.44` | 26 | `+23.08` | `+9.06` | 34.6% |
| `97-192_bars_24-48h` | 137 | `+59.76` | 52 | `+28.85` | `+14.83` | 48.1% |

### E. By Session (UTC Entry Hour)

| Session (UTC) | DEV N | DEV Net @14 | Burned 2026 N | Burned Gross (bps) | Burned Net @14 | 2026 WR% |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `00-06_ASIA` | 74 | `+49.94` | 31 | `+24.98` | `+10.96` | 38.7% |
| `06-12_EU` | 80 | `+37.32` | 25 | `-16.91` | `-30.90` | 36.0% |
| `12-18_US` | 136 | `+27.05` | 45 | `-22.55` | `-36.53` | 28.9% |
| `18-24_LATE_US` | 79 | `-9.18` | 24 | `-11.94` | `-25.93` | 33.3% |

### F. Cost Sensitivity Comparison

| Friction Tier | DEV Expectancy (bps) | DEV Win Rate | DEV Profit Factor | Burned 2026 Expectancy (bps) | Burned 2026 Win Rate | Burned 2026 Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **10.0 bps** | `+30.14` | 42.5% | 1.34 | `-17.60` | 33.6% | 0.82 |
| **14.0 bps** | `+26.14` | 42.0% | 1.29 | `-21.60` | 33.6% | 0.78 |
| **20.0 bps** | `+20.14` | 41.5% | 1.22 | `-27.60` | 33.6% | 0.73 |
| **30.0 bps** | `+10.14` | 41.5% | 1.10 | `-37.60` | 32.0% | 0.66 |

## 3. Epistemic Governance & Separation of Facts vs Inferences

- **Observed Evidence (Facts)**:
  1. BUY trades collapsed to `-41.06 bps` net in 2026 H1, generating 103.5% of total portfolio dollar drawdown.
  2. BTC accounted for 76.0% of total portfolio losses in 2026 H1.
  3. TP hit rate collapsed from 30.4% down to 16.8%, well below the 32.8% break-even barrier ratio.
  4. Premature stops (17–48 bars / 4–12h) suffered an extreme `-103.94 bps` net loss (12.0% win rate).
  5. US session (12–18 UTC) collapsed to `-36.53 bps` net (28.9% win rate).
  6. Friction of 14 bps per trade combined with 60.84x turnover added -17.50 bps of cost drag.

- **Hypotheses / Inferences (Unproven Causal Drivers)**:
  1. *Bear-rally entry hypothesis*: Naive Donchian 96 buys counter-trend bear market rallies at local peaks.
  2. *Macro whipsaw hypothesis*: US market open triggers fakeout volatility spikes that hit narrow 150 bps stops.
  3. *Regime decay hypothesis*: Volatility compression breakout requires persistent followthrough which degraded in 2026 H1.

- **Permanent Disposition**: Candidate `VOL_COMPRESSION_BREAKOUT_V1` is classified as `ECONOMIC_NO_GO`. 2026 H1 is permanently burned.