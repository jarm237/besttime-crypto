# HMR-V4C-3A: ETF / Institutional Flow Provenance Audit Report

## Governance Rationale & Decision Verdict

- **Verdict**: `AUTHORIZED_V4C_3B`
- **Provenance Status**: `AUTHORIZED_V4C_3B`

### Audit Gates Status

| Gate Code | Description | Status |
| :--- | :--- | :---: |
| `E0_SOURCE_PROVENANCE` | E0 Source Provenance | **PASS** |
| `E1_HISTORICAL_COVERAGE` | E1 Historical Coverage | **PASS** |
| `E2_FUND_ISSUER_SEMANTICS` | E2 Fund Issuer Semantics | **PASS** |
| `E3_TRADE_DATE_SEMANTICS` | E3 Trade Date Semantics | **PASS** |
| `E4_PUBLICATION_TIME_SEMANTICS` | E4 Publication Time Semantics | **WARNING / CONDITIONAL** |
| `E5_REVISION_CORRECTION_POLICY` | E5 Revision Correction Policy | **WARNING / CONDITIONAL** |
| `E6_WEEKEND_HOLIDAY_HANDLING` | E6 Weekend Holiday Handling | **PASS** |
| `E7_PIT_AVAILABILITY` | E7 Pit Availability | **PASS** |
| `E8_MISSING_FUND_HANDLING` | E8 Missing Fund Handling | **PASS** |
| `E9_AGGREGATE_FLOW_RECONSTRUCTION` | E9 Aggregate Flow Reconstruction | **PASS** |
| `E10_DETERMINISM` | E10 Determinism | **PASS** |
| `E11_SUITABILITY` | E11 Suitability | **PASS** |

## Hard Provenance Gates & Mitigations

### 1. Publication-Time Semantics (E4 & E7)
Historical Farside records lack a structured publication timestamp column, resulting in a classification of **`DATE_ONLY_UNKNOWN_LATENCY`**. To mitigate lookahead risk and ensure Point-In-Time (PIT) safety, we apply a conservative daily release lag policy:

> `available_at = trade_date + 1 day at 12:00 UTC`

This lag guarantees that all issuers' NAV and net flow calculations are finalized, audited, and disseminated before the signal is eligible for strategy-level replay.

### 2. Revision & Correction Policies (E5)
Since the data provider does not expose historical vintage correction logs, revision semantics are classified as **`REVISION_CLASS = UNKNOWN`**. Any retrospective restatements present a structural lookahead risk. The conservative 1-day release lag policy acts as the primary governance defense against backfill adjustments.

### 3. Fund-Level Preservation & GBTC Confounder (E2 & E9)
Rather than using pre-aggregated total flows directly, the audit preserves individual fund histories (IBIT, FBTC, BITB, ARKB, BTCO, EZBC, BRRR, HODL, BTCW, MSBT, GBTC). This allows us to calculate:
- `total_net_flow_usd`
- `ex_gbtc_net_flow_usd` (to account for GBTC outflows being structural/legacy arbitrage redemptions rather than new institutional demand).

## Pre-Registered Hypotheses for V4C-3B

### Directional Expectation (H5-D)
- **H-ETF-D1**: Positive net ETF flows $\implies$ positive future BTC return expectation.
- **H-ETF-D2 (Persistence)**: Multi-day persistent inflows $\implies$ stronger positive return expectation.

### Volatility Expectation (H5-V)
- Monotonic volatility separation across flow quintiles.

### Risk State Expectation (H5-R)
- **H-ETF-R1**: Large ETF outflow regime (Q1) $\implies$ elevated downside / MAE risk (triggers regime long veto).

## Intended Target Horizons & Economic Floors

ETF flows represent institutional cycles and are slower than intraday trades. We evaluate longer horizons with matching transaction floors:
- **$24\text{h}$ Horizon**: Floor $= 30\text{ bps}$
- **$72\text{h}$ Horizon**: Floor $= 60\text{ bps}$
- **$7\text{d}$ Horizon**: Floor $= 100\text{ bps}$

## Conclusion

Stage `V4C-3` is authorized to proceed to information audit **`AUTHORIZED_V4C_3B`** with **BTC** as the primary target asset. ETH/BNB will be used strictly for cross-asset spillover checks.
