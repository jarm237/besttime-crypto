# HMR-V1.3F-F4: Economic Label Redesign Probe (BUY Side)

Input: `research/historical_market_replay_v1/v1_3f/f0_candidates.parquet` — Total candidates: 45

Friction assumption: **15.0 bps** flat

| Horizon | n | Pos Ratio (Gross > 20bps) | AUC vs Score | Pos Ratio (Net > 0bps) | AUC vs Score | Mean Gross (bps) | Std Return (bps) | Spearman Corr |
|:--------|--:|--------------------------:|-------------:|-----------------------:|-------------:|-----------------:|-----------------:|--------------:|
| 32 bars | 45 | 28.9% | 0.589 | 31.1% | 0.606 | -15.77 | 48.62 | +0.1543 |
| 48 bars | 45 | 4.4% | 0.547 | 8.9% | 0.622 | -23.12 | 33.96 | +0.1881 |
| 96 bars | 45 | 11.1% | 0.500 | 15.6% | 0.414 | -25.70 | 49.55 | -0.0611 |
| 192 bars | 45 | 20.0% | 0.386 | 20.0% | 0.386 | -22.49 | 51.75 | -0.2028 |