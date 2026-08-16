# HMR-V4C-1A: Cross-Market Risk Regime Provenance Audit Report

## Governance Rationale & Decision Verdict

- **Verdict**: `AUTHORIZE_V4C_1B`
- **Provenance Status**: `PROVEN`

### Provenance Gates Status (C0 - C9)

- **C0_SOURCE_PROVENANCE**: `PASS`
- **C1_HISTORICAL_COVERAGE**: `PASS`
- **C2_TIMESTAMP_SESSION_SEMANTICS**: `PASS`
- **C3_REVISION_SEMANTICS**: `PASS`
- **C4_MARKET_HOURS_ALIGNMENT**: `PASS`
- **C5_PIT_AVAILABILITY**: `PASS`
- **C6_TIMEZONE_NORMALIZATION**: `PASS`
- **C7_MISSING_DAY_POLICY**: `PASS`
- **C8_DETERMINISTIC_RECONSTRUCTION**: `PASS`
- **C9_SUITABILITY**: `PASS`

## Revision and Market-Hours Alignment Semantics

1. **Revision Semantics (C3)**: REVISION_CLASS = MARKET_OBSERVED. No macro-vintage reconstruction is required. Historical-provider corrections remain possible and are controlled by raw snapshot/checksum provenance.
2. **Market-Hours Alignment (C4)**: Daily macro indices are recorded at US equity market close (16:00 America/New_York). Under available_at_policy = CONSERVATIVE_DAILY_RELEASE_LAG, we set availability to 17:00 America/New_York (converted to UTC, resolving dynamically to 21:00 UTC during EDT and 22:00 UTC during EST). This guarantees zero lookahead.
3. **Weekend Gap Handling (C7)**: Crypto markets trade 24/7 whereas macro indexes are closed. Friday's market close remains the latest known observation throughout Saturday and Sunday until Monday's open, which is PIT-valid and does not trigger missing-data anomalies.

## Historical Coverage & Availability Analysis

Yahoo Finance API endpoints were probed for 2023 and 2024:

| Symbol | Ticker | Request Status | Candle Count | Coverage Status |
| :--- | :--- | :---: | :---: | :--- |
| `VIX` | `^VIX` | `200` | `521` | **AVAILABLE** |
| `SPX` | `^SPX` | `200` | `502` | **AVAILABLE** |
| `DXY` | `DX-Y.NYB` | `200` | `607` | **AVAILABLE** |
| `US10Y` | `^TNX` | `200` | `502` | **AVAILABLE** |

## Conclusion & Next Steps

Since all gates **C0-C9** passed successfully, this cross-market risk dataset is promoted to the information audit stage:
**`AUTHORIZE_V4C-1B`**.
