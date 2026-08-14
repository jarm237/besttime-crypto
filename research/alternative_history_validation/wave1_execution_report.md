# AHDV Wave 1 Execution Report

Generated after G0 snapshot discovery, using archived snapshots as ground truth before bulk probing.

## Snapshot Ground Truth

- Snapshot root: `data/raw_alternative`
- Parseable snapshots: `2369`
- Range: `2026-07-03T06:24:49.073880+00:00` to `2026-07-27T07:55:46.078297+00:00`
- Selected probe timestamps:
  - `2026-07-04T09:05:55.641329+00:00`
  - `2026-07-14T18:41:27.795808+00:00`
  - `2026-07-26T02:19:22.629347+00:00`

## Six-Question Summary

| Source | Available | Source timestamp | available_at known | Future info | Normalizer | Deterministic | Snapshot parity | Stop |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| alternative_me | 3/3 | provider daily timestamp | 0/3 | 0/3 detected | 3/3 PASS | 3/3 payload | 6/9 fields | YES |
| fred | 0/3 | none | 0/3 | not evaluated | 0/3 | 3/3 payload | not run | YES |
| binance_funding | 3/3 | fundingTime | 3/3 | 0/3 detected | 3/3 PASS | 3/3 payload | 2/3 fields | NO |
| defillama_stablecoin | 3/3 | chart date | 0/3 | 0/3 detected | 3/3 PASS | 3/3 payload | 0/6 fields | YES |
| defillama_tvl | 3/3 | chart date | 0/3 | 0/3 detected | 3/3 PASS | 3/3 payload | 0/9 fields | YES |
| deribit_dvol | 3/3 | DVOL row timestamp | 3/3 | 0/3 detected | 3/3 PASS | 3/3 payload | 2/9 fields | NO |

## Initial Decisions

- `binance_funding` and `deribit_dvol` are the only Wave 1 sources that passed basic availability, known timestamp, normalizer, and payload determinism gates.
- Neither is promoted to H3/H4 yet because snapshot parity is not exact.
- `alternative_me` has historical records and normalizes, but exact `available_at` / publication timing is not proven.
- `defillama_stablecoin` and `defillama_tvl` have historical rows, but current API history does not prove vintage/PIT correctness and did not match archived production snapshots.
- `fred` did not run because `FRED_API_KEY` was unavailable to the probe environment.

## Stop-Rule Application

Sources failing availability or `available_at` proof stop before deep parity work:

- `fred`
- `alternative_me`
- `defillama_stablecoin`
- `defillama_tvl`

Sources that continue need focused contract audit rather than framework changes:

- `binance_funding`: investigate the first snapshot mismatch.
- `deribit_dvol`: define acceptable DVOL tolerance or identify collection-time alignment drift.

## Follow-Up Artifacts

- `wave1_binance_funding_mismatch_audit.md`
- `wave1_deribit_dvol_alignment_contract.md`
- `wave1_fallback_verification.md`
- `wave1_fred_probe_environment.md`
