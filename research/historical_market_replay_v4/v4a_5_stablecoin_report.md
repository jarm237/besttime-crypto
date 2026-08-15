# HMR-V4A-5-r1 DefiLlama Stablecoin supply / liquidity Audit Report

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

| Feature | Calendar Correlation | Verdict |
| --- | :---: | --- |
| `stablecoin_supply_level` | 0.74 | `REJECT_SUPPORT_COLLAPSE` |
| `stablecoin_supply_change_1d` | 0.32 | `REJECT_NON_TRANSPORTABLE` |
| `stablecoin_supply_change_7d` | 0.59 | `REJECT_NON_TRANSPORTABLE` |
| `stablecoin_supply_change_30d` | 0.78 | `REJECT_NO_ECONOMIC_INFORMATION` |
| `stablecoin_supply_zscore_90d` | 0.74 | `REJECT_NO_ECONOMIC_INFORMATION` |

## Primary Medium-Horizon Spreads (Q5 - Q1)

| Feature | Period | Return 48h (bps) | Return 72h (bps) | Return 7d (bps) | Large 50_192 (pp) | Large 100_672 (pp) | Monotonicity |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `stablecoin_supply_level` | A | -2.79 | -4.49 | -9.36 | 0.00 | -2.40 | -0.30 |
| `stablecoin_supply_level` | B | n/a | n/a | n/a | n/a | n/a | 0.71 |
| `stablecoin_supply_level` | C | n/a | n/a | n/a | n/a | n/a | -0.71 |
| `stablecoin_supply_change_1d` | A | -0.11 | 1.00 | -3.62 | 0.00 | -0.60 | 0.60 |
| `stablecoin_supply_change_1d` | B | 2.48 | 4.20 | 11.65 | 0.00 | -0.62 | 0.40 |
| `stablecoin_supply_change_1d` | C | 2.36 | -2.90 | 3.25 | 0.00 | 0.81 | 0.20 |
| `stablecoin_supply_change_7d` | A | -1.75 | -2.87 | -4.20 | 0.00 | -0.52 | -0.30 |
| `stablecoin_supply_change_7d` | B | 1.86 | -7.61 | -1.44 | 0.00 | 3.47 | -0.80 |
| `stablecoin_supply_change_7d` | C | 5.28 | 10.54 | 19.90 | 0.00 | 1.05 | 0.90 |
| `stablecoin_supply_change_30d` | A | -3.12 | -4.83 | -13.60 | 0.00 | -2.14 | -0.40 |
| `stablecoin_supply_change_30d` | B | n/a | n/a | n/a | n/a | n/a | 0.67 |
| `stablecoin_supply_change_30d` | C | n/a | n/a | n/a | n/a | n/a | -0.56 |
| `stablecoin_supply_zscore_90d` | A | -7.28 | -10.22 | -23.04 | 0.00 | -1.51 | -0.50 |
| `stablecoin_supply_zscore_90d` | B | n/a | n/a | n/a | n/a | n/a | 0.15 |
| `stablecoin_supply_zscore_90d` | C | n/a | n/a | n/a | n/a | n/a | 0.15 |

## Period Effect Vectors and Sign Patterns

| Feature | Target | Period Spreads [A, B, C] | Sign Pattern | Transport Verdict |
| --- | --- | :---: | :---: | :---: |
| `stablecoin_supply_change_1d` | `return_48h` | [-0.1, +2.5, +2.4] | `-++` | `A->B/C INVERSION` |
| `stablecoin_supply_change_1d` | `return_72h` | [+1.0, +4.2, -2.9] | `++-` | `NON_TRANSPORTABLE` |
| `stablecoin_supply_change_1d` | `return_7d` | [-3.6, +11.6, +3.2] | `-++` | `A->B/C INVERSION` |
| `stablecoin_supply_change_7d` | `return_48h` | [-1.8, +1.9, +5.3] | `-++` | `A->B/C INVERSION` |
| `stablecoin_supply_change_7d` | `return_72h` | [-2.9, -7.6, +10.5] | `--+` | `NON_TRANSPORTABLE` |
| `stablecoin_supply_change_7d` | `return_7d` | [-4.2, -1.4, +19.9] | `--+` | `NON_TRANSPORTABLE` |
