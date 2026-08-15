# HMR-V4A-2 Deribit IV Skew Audit Report

## Summary table

| Feature | Period A Spread (bps) | Period B Spread (bps) | Period C Spread (bps) | Retention Ratio | Verdict |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `iv_skew_level` | 0.31 | 1.10 | 0.25 | UNDEFINED_LOW_BASE_EFFECT | **REJECT_AS_CROSS_ASSET_CONFOUNDING** |
| `iv_skew_level_normalized` | 0.87 | 1.37 | 1.34 | UNDEFINED_LOW_BASE_EFFECT | **REJECT** |
| `iv_skew_change_4h` | 0.30 | 0.89 | 1.31 | UNDEFINED_LOW_BASE_EFFECT | **REJECT** |
| `iv_skew_change_24h` | 0.51 | -0.78 | 1.55 | UNDEFINED_LOW_BASE_EFFECT | **REJECT** |
| `iv_skew_percentile_30d` | 0.87 | 1.37 | 1.34 | UNDEFINED_LOW_BASE_EFFECT | **REJECT** |