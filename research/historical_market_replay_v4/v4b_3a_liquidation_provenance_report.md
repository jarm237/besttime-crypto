# HMR-V4B-3A: Binance Real Liquidations Provenance Audit Report

## Governance Rationale & Decision Verdict

- **Verdict**: `REJECT_INCOMPLETE_LIQUIDATION_OBSERVABILITY`
- **Provenance Status**: `REJECTED`

### Gates Status (L0 - L7)

- **L0_SOURCE_PROVENANCE**: `PASS`
- **L1_HISTORICAL_AVAILABILITY**: `FAIL`
- **L2_COVERAGE**: `FAIL`
- **L3_SCHEMA_SEMANTICS**: `PASS`
- **L4_COMPLETENESS_CENSORING**: `FAIL`
- **L5_PIT_VALIDITY**: `PASS`
- **L6_DETERMINISM**: `PASS`
- **L7_SUITABILITY**: `FAIL`

## Historical Coverage & Availability Analysis

Binance's public liquidation snapshots were probed for sample dates in 2023 and 2024:

| Symbol | Date | Request Status | Coverage Status |
| :--- | :--- | :---: | :--- |
| `BTCUSDT` | 2023-06-01 | `404` | **MISSING / 404** |
| `BTCUSDT` | 2023-12-01 | `404` | **MISSING / 404** |
| `BTCUSDT` | 2024-03-31 | `404` | **MISSING / 404** |
| `BTCUSDT` | 2024-04-01 | `404` | **MISSING / 404** |
| `BTCUSDT` | 2024-06-01 | `404` | **MISSING / 404** |
| `BTCUSDT` | 2024-12-31 | `404` | **MISSING / 404** |
| `ETHUSDT` | 2023-06-01 | `404` | **MISSING / 404** |
| `ETHUSDT` | 2023-12-01 | `404` | **MISSING / 404** |
| `ETHUSDT` | 2024-03-31 | `404` | **MISSING / 404** |
| `ETHUSDT` | 2024-04-01 | `404` | **MISSING / 404** |
| `ETHUSDT` | 2024-06-01 | `404` | **MISSING / 404** |
| `ETHUSDT` | 2024-12-31 | `404` | **MISSING / 404** |
| `BNBUSDT` | 2023-06-01 | `404` | **MISSING / 404** |
| `BNBUSDT` | 2023-12-01 | `404` | **MISSING / 404** |
| `BNBUSDT` | 2024-03-31 | `404` | **MISSING / 404** |
| `BNBUSDT` | 2024-04-01 | `404` | **MISSING / 404** |
| `BNBUSDT` | 2024-06-01 | `404` | **MISSING / 404** |
| `BNBUSDT` | 2024-12-31 | `404` | **MISSING / 404** |

## Critical Censoring and PIT Observability Limitations

1. **Snapshot Availability Gaps**: Public daily liquidation snapshots are completely missing after **2024-03-31**, leaving the frozen Period B and C validation windows completely unobservable.
2. **WebSocket Client Throttling**: The official Binance Futures WebSocket client stream only pushes the **latest single liquidation order every 1000ms per symbol**. Any other liquidation orders occurring within that 1-second window are discarded, causing severe, unquantifiable censoring of total liquidation volume/intensity.
3. **forceOrders Endpoint Restrictions**: The REST endpoint `/fapi/v1/forceOrders` returns `401 Unauthorized (API-key format invalid)` without credentials and is subject to severe geographic restrictions and rate limits. It does not provide historical archives.

## Conclusion & Next Steps

Due to the failure of L1 (Historical Availability), L2 (Coverage), L4 (Completeness / Censoring), and L7 (Suitability) gates, this information source is **rejected for predictive use**.
Model training and feature audits remain strictly **BLOCKED**.
