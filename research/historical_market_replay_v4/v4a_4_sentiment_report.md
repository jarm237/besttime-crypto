# HMR-V4A-4-r1 Alternative.me Fear & Greed Sentiment Audit

## Canonical closeout

```text
HMR-V4A-4 — Alternative.me Sentiment

Source authenticity        PASS_WITH_CONSERVATIVE_LAG
Temporal policy            06:00 UTC availability
Directional information    FAIL
Regime information          FAIL
Transportability            FAIL

fear_greed_level            REJECT_NON_TRANSPORTABLE
fear_greed_delta_1d         REJECT_NON_TRANSPORTABLE
fear_greed_delta_7d         REJECT_NON_TRANSPORTABLE
fear_greed_percentile_90d   REJECT_NO_ECONOMIC_INFORMATION

Family state                CLOSED_FOR_V4A
Rescue transforms           BLOCKED
ML training                 BLOCKED
```

> [!NOTE]
> `06:00 UTC` is a **research-time conservative availability assumption**, not a historical publication fact.
> - `availability_policy` = `CONSERVATIVE_ASSUMPTION_06UTC`
> - `archived_publication_parity` = `NOT_PROVEN`
> - `production_evidence_eligible` = `false`

## Contract & Provenance

- **Source authenticity**: `PASS`
- **Historical parity**: `H2_DATE_LEVEL_ASOF`
- **Temporal validity gate**: `PASS` (6-hour conservative lag enforced)
- **Usable coverage**: `100.00%` (`PASS`)
- **Production evidence eligibility**: `ELIGIBLE_FOR_PRODUCTION = False`

Eligible assets: `BTC, ETH`. Control-only assets: `BNB`.

## Feature Verdicts

| Feature | Verdict |
| --- | --- |
| `fear_greed_level` | `REJECT_NON_TRANSPORTABLE` |
| `fear_greed_delta_1d` | `REJECT_NON_TRANSPORTABLE` |
| `fear_greed_delta_7d` | `REJECT_NON_TRANSPORTABLE` |
| `fear_greed_percentile_90d` | `REJECT_NO_ECONOMIC_INFORMATION` |

## Primary Period Spreads (Q5 - Q1)

| Feature | Period | Return 32 Spread (bps) | Return 72 Spread (bps) | Long 30/20 Spread (pp) | Short 30/20 Spread (pp) | Large Move 30 (pp) | Monotonicity |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `fear_greed_level` | A | -0.60 | -0.78 | 0.10 | 0.07 | 0.00 | -0.60 |
| `fear_greed_level` | B | -0.50 | -1.10 | 1.57 | -2.41 | 0.00 | -0.10 |
| `fear_greed_level` | C | 0.80 | 2.92 | -0.49 | -0.40 | 0.00 | 0.20 |
| `fear_greed_delta_1d` | A | -0.20 | -0.08 | 0.17 | 0.41 | 0.00 | 0.10 |
| `fear_greed_delta_1d` | B | -0.38 | -0.63 | 0.12 | 0.07 | 0.00 | -0.30 |
| `fear_greed_delta_1d` | C | -3.06 | -6.00 | 0.66 | -0.15 | 0.00 | -1.00 |
| `fear_greed_delta_7d` | A | 0.03 | 0.52 | 0.04 | -0.01 | 0.00 | 0.50 |
| `fear_greed_delta_7d` | B | -0.17 | -0.92 | 0.82 | -0.46 | 0.00 | -0.20 |
| `fear_greed_delta_7d` | C | 0.63 | 2.15 | 0.23 | -1.09 | 0.00 | 0.50 |
| `fear_greed_percentile_90d` | A | 0.08 | 0.43 | -0.34 | 0.05 | 0.00 | 0.00 |
| `fear_greed_percentile_90d` | B | n/a | n/a | n/a | n/a | n/a | -0.30 |
| `fear_greed_percentile_90d` | C | -1.76 | -6.27 | -0.13 | 0.38 | 0.00 | -0.60 |

## Period Effect Vectors and Sign Patterns

| Feature | Target | Period Spreads [A, B, C] | Sign Pattern | Transport Verdict |
| --- | --- | :---: | :---: | :---: |
| `fear_greed_delta_1d` | `long_30_20` | [+0.2, +0.1, +0.7] | `+++` | `TRANSPORTABLE` |
| `fear_greed_delta_1d` | `return_72` | [-0.1, -0.6, -6.0] | `---` | `TRANSPORTABLE` |
| `fear_greed_delta_1d` | `short_30_20` | [+0.4, +0.1, -0.1] | `++-` | `NON_TRANSPORTABLE` |
| `fear_greed_delta_7d` | `long_30_20` | [+0.0, +0.8, +0.2] | `+++` | `TRANSPORTABLE` |
| `fear_greed_delta_7d` | `return_72` | [+0.5, -0.9, +2.2] | `+-+` | `NON_TRANSPORTABLE` |
| `fear_greed_delta_7d` | `short_30_20` | [-0.0, -0.5, -1.1] | `---` | `TRANSPORTABLE` |
| `fear_greed_level` | `long_30_20` | [+0.1, +1.6, -0.5] | `++-` | `NON_TRANSPORTABLE` |
| `fear_greed_level` | `return_72` | [-0.8, -1.1, +2.9] | `--+` | `NON_TRANSPORTABLE` |
| `fear_greed_level` | `short_30_20` | [+0.1, -2.4, -0.4] | `+--` | `A->B/C INVERSION` |
