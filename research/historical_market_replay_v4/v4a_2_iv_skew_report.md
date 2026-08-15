# HMR-V4A-2-R Reconstructed IV Skew Proxy Audit Report

## Canonical closeout


- `V4A-2-R`: `ENDOGENOUS_RECONSTRUCTED_PROXY`, `REJECTED_FINAL`, directional alpha `NONE`, independent information `NOT_DEMONSTRATED`.
- `V4A-2-G`: `GENUINE_OPTIONS_MARKET_DATA`, `UNTESTED`; reopen only with an authentic historical option-chain/skew archive.
- Do not reopen `V4A-2-R` with another proxy transform.

The tested series was reconstructed from past return and rolling volatility, so no independent information after conditioning is structurally expected.

## Summary table

| Feature | Period A Spread (bps) | Period B Spread (bps) | Period C Spread (bps) | Retention Ratio | Verdict |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `iv_skew_level` | 0.31 | 1.10 | 0.25 | UNDEFINED_LOW_BASE_EFFECT | **REJECT_AS_CROSS_ASSET_CONFOUNDING** |
| `iv_skew_level_normalized` | 0.87 | 1.37 | 1.34 | UNDEFINED_LOW_BASE_EFFECT | **REJECT** |
| `iv_skew_change_4h` | 0.30 | 0.89 | 1.31 | UNDEFINED_LOW_BASE_EFFECT | **REJECT** |
| `iv_skew_change_24h` | 0.51 | -0.78 | 1.55 | UNDEFINED_LOW_BASE_EFFECT | **REJECT** |
| `iv_skew_percentile_30d` | 0.87 | 1.37 | 1.34 | UNDEFINED_LOW_BASE_EFFECT | **REJECT** |