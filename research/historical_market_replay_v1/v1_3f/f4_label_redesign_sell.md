# HMR-V1.3F-F4: Economic Label Redesign Probe (SELL Side)

Input: `research/historical_market_replay_v1/v1_3f/f0_candidates.parquet` — Total candidates: 1130

Friction assumption: **15.0 bps** flat

| Horizon | n | Pos Ratio (Gross > 20bps) | AUC vs Score | Pos Ratio (Net > 0bps) | AUC vs Score | Mean Gross (bps) | Std Return (bps) | Spearman Corr |
|:--------|--:|--------------------------:|-------------:|-----------------------:|-------------:|-----------------:|-----------------:|--------------:|
| 32 bars | 1130 | 10.4% | 0.725 | 14.1% | 0.722 | -24.38 | 38.36 | +0.4398 |
| 48 bars | 1130 | 12.2% | 0.694 | 15.6% | 0.682 | -23.06 | 39.56 | +0.3882 |
| 96 bars | 1130 | 14.9% | 0.680 | 18.5% | 0.684 | -22.43 | 41.32 | +0.3773 |
| 192 bars | 1130 | 17.5% | 0.653 | 20.1% | 0.649 | -23.68 | 47.32 | +0.3272 |