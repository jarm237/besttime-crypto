# HMR-V4A-6-r1 DeFi TVL liquidity Audit Report

## Contract & Provenance

- **Source authenticity**: `PASS_WITH_CONSERVATIVE_LAG`
- **Historical parity**: `H2_ASOF_RECONSTRUCTABLE`
- **Temporal validity gate**: `PASS` (12-hour conservative lag enforced)
- **Usable coverage**: `100.00%` (`PASS`)
- **Production evidence eligibility**: `ELIGIBLE_FOR_PRODUCTION = False`
- **Availability policy**: `CONSERVATIVE_ASSUMPTION_12UTC`
- **Archived publication parity**: `NOT_PROVEN`

Eligible assets: `BTC, ETH, BNB`.

## Feature Verdicts

| Feature | Calendar Correlation | Price Correlation | Price conditioning retention | Verdict |
| --- | :---: | :---: | :---: | --- |
| `defi_tvl_level` | 0.78 | -0.03 | 0.95 | `REJECT_SUPPORT_COLLAPSE` |
| `defi_tvl_change_1d` | 0.04 | -0.01 | 1.01 | `REJECT_NON_TRANSPORTABLE` |
| `defi_tvl_change_7d` | 0.10 | -0.01 | 0.88 | `REJECT_NON_TRANSPORTABLE` |
| `defi_tvl_change_30d` | 0.19 | -0.00 | 1.00 | `REJECT_NON_TRANSPORTABLE` |
| `defi_tvl_zscore_90d` | 0.19 | 0.05 | 0.79 | `REJECT_NO_ECONOMIC_INFORMATION` |

## Primary Medium-Horizon Spreads (Q5 - Q1)

| Feature | Period | Return 48h (bps) | Return 72h (bps) | Return 7d (bps) | Large 50_192 (pp) | Large 100_672 (pp) | Monotonicity |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `defi_tvl_level` | A | -3.29 | -4.81 | -10.98 | 0.00 | -2.77 | -0.90 |
| `defi_tvl_level` | B | n/a | n/a | n/a | n/a | n/a | 0.22 |
| `defi_tvl_level` | C | n/a | n/a | n/a | n/a | n/a | -0.78 |
| `defi_tvl_change_1d` | A | -0.46 | -0.57 | 0.67 | 0.00 | 0.30 | -0.20 |
| `defi_tvl_change_1d` | B | -4.84 | -6.62 | -1.27 | 0.00 | 1.76 | -0.20 |
| `defi_tvl_change_1d` | C | 0.40 | -0.47 | 13.00 | 0.00 | 4.79 | 0.20 |
| `defi_tvl_change_7d` | A | -0.83 | -0.11 | 8.33 | 0.00 | 0.31 | -0.10 |
| `defi_tvl_change_7d` | B | 5.91 | 6.76 | -5.97 | 0.00 | 5.40 | 0.00 |
| `defi_tvl_change_7d` | C | 7.41 | 10.77 | 22.73 | 0.00 | 9.05 | 0.80 |
| `defi_tvl_change_30d` | A | -5.24 | -7.54 | -13.40 | 0.00 | -0.44 | -0.70 |
| `defi_tvl_change_30d` | B | 16.04 | 17.83 | 1.98 | 0.00 | 11.12 | 0.30 |
| `defi_tvl_change_30d` | C | 21.81 | 32.66 | 68.82 | 0.00 | -3.20 | 0.90 |
| `defi_tvl_zscore_90d` | A | -2.94 | -2.60 | -5.48 | 0.00 | -1.63 | -0.60 |
| `defi_tvl_zscore_90d` | B | n/a | n/a | n/a | n/a | n/a | -0.36 |
| `defi_tvl_zscore_90d` | C | n/a | n/a | n/a | n/a | n/a | 0.30 |

## Period Effect Vectors and Sign Patterns

| Feature | Target | Period Spreads [A, B, C] | Sign Pattern | Transport Verdict |
| --- | --- | :---: | :---: | :---: |
| `defi_tvl_change_1d` | `return_48h` | [-0.5, -4.8, +0.4] | `--+` | `NON_TRANSPORTABLE` |
| `defi_tvl_change_1d` | `return_72h` | [-0.6, -6.6, -0.5] | `---` | `TRANSPORTABLE` |
| `defi_tvl_change_1d` | `return_7d` | [+0.7, -1.3, +13.0] | `+-+` | `NON_TRANSPORTABLE` |
| `defi_tvl_change_30d` | `return_48h` | [-5.2, +16.0, +21.8] | `-++` | `A->B/C INVERSION` |
| `defi_tvl_change_30d` | `return_72h` | [-7.5, +17.8, +32.7] | `-++` | `A->B/C INVERSION` |
| `defi_tvl_change_30d` | `return_7d` | [-13.4, +2.0, +68.8] | `-++` | `A->B/C INVERSION` |
| `defi_tvl_change_7d` | `return_48h` | [-0.8, +5.9, +7.4] | `-++` | `A->B/C INVERSION` |
| `defi_tvl_change_7d` | `return_72h` | [-0.1, +6.8, +10.8] | `-++` | `A->B/C INVERSION` |
| `defi_tvl_change_7d` | `return_7d` | [+8.3, -6.0, +22.7] | `+-+` | `NON_TRANSPORTABLE` |
