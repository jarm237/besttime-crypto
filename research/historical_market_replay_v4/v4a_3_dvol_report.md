# HMR-V4A-3M-r1 Deribit DVOL Magnitude Audit

## Contract

Provenance: `PASS_WITH_CAVEAT` / `H2_ASOF_RECONSTRUCTABLE`. Production evidence remains blocked; research inference is allowed.

Eligible assets: `BTC, ETH`. Control-only assets: `BNB`.

## Feature Verdicts

| Feature | Verdict |
| --- | --- |
| `dvol_level` | `REJECT_NON_TRANSPORTABLE` |
| `dvol_change_4h` | `REJECT_NON_TRANSPORTABLE` |
| `dvol_change_24h` | `REJECT_NON_TRANSPORTABLE` |
| `dvol_percentile_30d` | `REJECT_NON_TRANSPORTABLE` |

## Primary Period Spreads

| Feature | Period | Max abs excursion Q5-Q1 bps | Future range 72 Q5-Q1 bps | Large30 Q5-Q1 pp | Monotonicity |
| --- | --- | ---: | ---: | ---: | ---: |
| `dvol_level` | A | 6.34 | 9.49 | 0.00 | 0.60 |
| `dvol_level` | B | 33.21 | 50.34 | 0.00 | 0.70 |
| `dvol_level` | C | n/a | n/a | n/a | 1.00 |
| `dvol_change_4h` | A | 0.14 | 0.07 | 0.00 | 0.10 |
| `dvol_change_4h` | B | -1.13 | -3.03 | 0.00 | 0.00 |
| `dvol_change_4h` | C | 1.13 | 2.30 | 0.10 | -0.30 |
| `dvol_change_24h` | A | 0.92 | 1.27 | 0.00 | 0.00 |
| `dvol_change_24h` | B | -4.08 | -8.60 | 0.00 | -0.10 |
| `dvol_change_24h` | C | 0.28 | 2.32 | 0.04 | -0.40 |
| `dvol_percentile_30d` | A | -0.70 | -0.81 | 0.00 | -0.10 |
| `dvol_percentile_30d` | B | -11.89 | -19.22 | 0.00 | -0.50 |
| `dvol_percentile_30d` | C | 4.20 | 8.33 | 0.00 | 0.90 |
