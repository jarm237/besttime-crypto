# HMR-V4B-5A: Genuine Options Historical Provenance Audit Report

## Governance Rationale & Decision Verdict

- **Verdict**: `REJECT_INSUFFICIENT_CHAIN_COVERAGE`
- **Provenance Status**: `REJECTED`

### Provenance Gates Status (O0 - O10)

- **O0_SOURCE_PROVENANCE**: `PASS`
- **O1_HISTORICAL_AVAILABILITY**: `FAIL`
- **O2_COVERAGE_PERIOD_A_B_C**: `FAIL`
- **O3_INSTRUMENT_CONTRACT_SEMANTICS**: `PASS`
- **O4_QUOTE_MARK_TIMESTAMP_SEMANTICS**: `FAIL`
- **O5_STRIKE_EXPIRY_NORMALIZATION**: `FAIL`
- **O6_IV_GREEKS_PROVENANCE**: `PASS`
- **O7_PIT_SAFE_CHAIN_RECONSTRUCTION**: `FAIL`
- **O8_CROSS_SECTIONAL_COMPLETENESS**: `FAIL`
- **O9_DETERMINISTIC_CANONICALIZATION**: `PASS`
- **O10_SUITABILITY_FOR_FEATURE_AUDIT**: `FAIL`

## Probing Analysis & Findings

1. **Binance Vision daily directories**: Probed `BTCBVOLUSDT` daily 15m volatility klines at `https://data.binance.vision`. The request returned **404 Not Found**, confirming daily volatility index archives are not available.
2. **Deribit REST API**: Probed expired instruments metadata and book summary. The active summary endpoint returned `200` with `818` options contracts, verifying that the live API is functional. However, the REST API does not archive complete historical options chain snapshots (bid/ask/mark price/IV/greeks across strike ranges) for 2023-2024.
3. **Public Data Paywall**: Complete historical options chain snapshots for Deribit are highly commercialized and only accessible via paid API providers (such as Tardis.dev, Amberdata, or CryptoStruct). They are unavailable in the free public domain.

## Coverage Gaps

Since no historical daily chain snapshots could be retrieved, coverage across expiry and moneyness buckets is **0.0%**:

- Expiry buckets (0-7d, 8-30d, 31-90d, >90d): **0.0% coverage**
- Moneyness buckets (deep put, put wing, ATM, call wing, deep call): **0.0% coverage**

## Conclusion & Next Steps

Due to the failure of O1 (Historical availability), O2 (Coverage Period A/B/C), O4 (Timestamp verification), O5 (Chain normalization), O7 (PIT-safe reconstruction), O8 (Cross-sectional completeness), and O10 (Suitability), the candidate is rejected.
Model training and options feature audits are **BLOCKED**.
According to V4B acquisition governance, since the final microstructure candidate has failed, the research pipeline should pivot to **exogenous or cross-market channels** (e.g. stablecoin supply/flows, event state, macro indicators).
