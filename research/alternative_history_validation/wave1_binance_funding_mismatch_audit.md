# AHDV-W1.1 Binance Funding Mismatch Audit

Scope: audit the single `binance_funding` mismatch from Wave 1 before increasing sample size.

## Mismatch Timestamp

| Field | Value |
| --- | --- |
| requested_as_of | `2026-07-04T09:05:55.641329+00:00` |
| snapshot_path | `data/raw_alternative/alternative_2026-07-04T09_05_55.641329+00_00.json` |
| snapshot_collected_at | `2026-07-04T09:05:55.641329+00:00` |
| snapshot_status | `success` |
| snapshot_funding_rate | `-0.00256226` |
| historical_selected_fundingTime | `2026-07-04T08:00:00+00:00` |
| historical_selected_funding_rate | `0.00010000` |
| previous_fundingTime | `2026-07-04T00:00:00+00:00` |
| previous_funding_rate | `0.00010000` |
| next_fundingTime in response | `None` |

## Side-By-Side

| Layer | Snapshot | Historical |
| --- | ---: | ---: |
| raw funding field | `-0.00256226` | `0.00010000` |
| normalized `funding_rate` | `-0.00256226` | `0.0001` |
| source time | collector timestamp | `fundingTime=2026-07-04T08:00:00+00:00` |

## Mismatch Type Assessment

| Candidate | Current assessment |
| --- | --- |
| A. wrong temporal selection | Not proven. Previous and selected historical rows are both `0.00010000`; no next row existed in the bounded response. |
| B. snapshot captured before/after funding publication | Possible but unlikely to explain the negative value unless the live endpoint returned a mark/estimate-like value rather than settled funding. |
| C. production collector uses latest while historical probe uses exact interval | Confirmed semantic difference: production uses `fundingRate?limit=1` at collection time; probe uses bounded historical interval and selects `fundingTime <= T`. This does not fully explain the sign/value mismatch. |
| D. numeric precision only | No. Difference is sign and magnitude. |
| E. different symbol/contract semantics | Not indicated; both use `BTCUSDT` USD-M futures endpoint. |
| F. genuine provider historical mutation | Possible. Needs live snapshot raw payload from that exact collection to prove. Current archived aggregate does not include the raw Binance response. |

## Decision

Keep `binance_funding` as `UNCLASSIFIED`.

Do not expand probes yet. Next action is to determine whether production raw archive includes the exact Binance HTTP payload for `2026-07-04T09:05:55Z`; if not, this timestamp cannot promote to H3/H4 and should be marked parity ambiguous.

