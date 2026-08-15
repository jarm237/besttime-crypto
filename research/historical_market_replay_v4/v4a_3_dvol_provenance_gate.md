# HMR-V4A-3P Deribit DVOL Provenance Gate

## Stage 0 decision

`deribit_dvol` is classified as `EXTERNAL_DERIBIT_OBSERVATION` under current artifacts: Deribit publishes DVOL OHLC rows, and the replay evidence is `H2_AS_OF_RECONSTRUCTABLE`, not H3/H4 archived PIT parity.

Decision: `PROCEED_WITH_RECONSTRUCTION_CAVEAT`.

Independent-info eligibility: `YES_FOR_RESEARCH`.

Production evidence: `BLOCKED`.

## Inspection answers

| Question | Answer |
| --- | --- |
| Deribit-published value at timestamp? | Yes for DVOL rows consumed from `get_volatility_index_data`. |
| Reconstructed from BTC realized vol / price? | No evidence in current artifacts. |
| `source_timestamp` | DVOL row timestamp: `result.data[-1][0]`. |
| `available_at` | Closed DVOL row timestamp, pending H3/H4 archive parity proof. |
| Future interpolation? | No evidence. |
| Future-known backfill? | No evidence. |
| Per-asset synthetic mapping? | No current mapping proven; production collector fetches BTC DVOL/options_iv. |

## V4A-3 target

The audit question is volatility expansion probability/magnitude and timing, not UP/DOWN direction.

Frozen feature set: `dvol_level`, `dvol_change_4h`, `dvol_change_24h`, `dvol_percentile_30d`.
