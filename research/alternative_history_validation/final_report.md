# Alternative Historical Data Validation

This artifact is research-only and non-evidence until probes prove PIT correctness.

Boundary: READ_ONLY, NON_EVIDENCE, NO_ACTIVE_CANARY_MUTATION, NO_RUNTIME_CONTROL_ACTION, NO_MODEL_RETRAIN, NO_POLICY_CHANGE

| Source | 7d | 30d | 90d | 180d | 365d | Earliest usable | PIT | Parity | Fallback | Fidelity | Replay decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| alternative_me | AVAILABLE | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | UNKNOWN | NOT_PROVEN | PARTIAL | VERIFIED | H1_HISTORICAL | PRODUCTION_FALLBACK |
| fred | PROBE_BLOCKED_ENVIRONMENT | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | UNKNOWN | UNKNOWN | UNKNOWN | VERIFIED | UNCLASSIFIED | PRODUCTION_FALLBACK |
| binance_funding | AVAILABLE | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | UNKNOWN | NOT_PROVEN | PARTIAL_2_OF_3 | VERIFIED | H1_HISTORICAL | PRODUCTION_FALLBACK |
| binance_open_interest | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | UNKNOWN | NOT_EVALUATED | NOT_EVALUATED | NOT_VERIFIED | UNCLASSIFIED | PENDING_VALIDATION |
| binance_orderbook | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | UNKNOWN | NOT_EVALUATED | NOT_EVALUATED | NOT_VERIFIED | UNCLASSIFIED | PENDING_VALIDATION |
| defillama_stablecoin | AVAILABLE | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | UNKNOWN | NOT_PROVEN | FAIL_0_OF_6 | VERIFIED | H1_HISTORICAL | PRODUCTION_FALLBACK |
| defillama_tvl | AVAILABLE | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | UNKNOWN | NOT_PROVEN | FAIL_0_OF_9 | VERIFIED | H1_HISTORICAL | PRODUCTION_FALLBACK |
| deribit_dvol | AVAILABLE | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | UNKNOWN | RECONSTRUCTABLE_WITH_CLOSED_CANDLE_ONLY | ALIGNMENT_CONTRACT_DEFINED | VERIFIED | H2_AS_OF_RECONSTRUCTABLE | USE_RECONSTRUCTED_CLOSED_OBSERVATION |
| deribit_iv_skew | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | UNKNOWN | NOT_EVALUATED | NOT_EVALUATED | NOT_VERIFIED | UNCLASSIFIED | PENDING_VALIDATION |
| etf | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | UNKNOWN | NOT_EVALUATED | NOT_EVALUATED | NOT_VERIFIED | UNCLASSIFIED | PENDING_VALIDATION |
| google_trends | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | UNKNOWN | NOT_EVALUATED | NOT_EVALUATED | NOT_VERIFIED | UNCLASSIFIED | PENDING_VALIDATION |
| reddit | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | NOT_PROBED | UNKNOWN | NOT_EVALUATED | NOT_EVALUATED | NOT_VERIFIED | UNCLASSIFIED | PENDING_VALIDATION |

## Next Gates

0. Freeze production contract inventory: source, endpoint/provider, raw fields, timestamp field, normalizer, derived feature, cache/TTL, fallback.
1. Run historical availability and retention probes per timestamp and archive raw responses with hashes.
2. Check `available_at <= replay_clock` for every record.
3. Feed historical payloads through production normalization and compare schema/units/timezone.
4. Compare against existing raw snapshots before promoting any source to H3/H4.
5. Repeat queries to prove deterministic behavior before final replay eligibility.

## Wave 1 Closeout

Wave 1 is frozen. Do not continue provider investigation on the critical path. Move to Historical Market Replay V1 with two profiles:

- `STRICT_V1`: PIT-safe data plus production fallback.
- `RESEARCH_V1`: includes historical H1/H2 data with `NON_PIT_VERIFIED` where applicable.

Replay must never use high/low/close from a candle containing `T` before that candle is complete.
