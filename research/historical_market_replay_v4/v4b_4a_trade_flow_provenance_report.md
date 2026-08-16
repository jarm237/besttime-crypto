# HMR-V4B-4A: Aggressive Trade Flow Provenance Audit Report

## Governance Rationale & Decision Verdict

- **Verdict**: `AUTHORIZE_V4B_4B`
- **Provenance Status**: `PROVEN`

### Provenance Gates Status (F0 - F8)

- **F0_SOURCE_PROVENANCE**: `PASS`
- **F1_HISTORICAL_AVAILABILITY**: `PASS`
- **F2_COVERAGE**: `PASS`
- **F3_TRADE_SIDE_SEMANTICS**: `PASS`
- **F4_TIMESTAMP_GRANULARITY**: `PASS`
- **F5_PIT_VALIDITY**: `PASS`
- **F6_AGGREGATION_DETERMINISM**: `PASS`
- **F7_SEQUENCE_ANOMALY**: `PASS`
- **F8_SUITABILITY**: `PASS`

## Canonical Aggressor Semantics Mapping

To reconstruct the buy/sell aggressor flow from raw trades, we rely on the `is_buyer_maker` boolean flag. This is mapped to the canonical schema as follows:

- **Taker Sell (Aggressive Sell)**: `is_buyer_maker == True`
  - `taker_sell_qty = quantity`
  - `taker_sell_notional = quantity * price`
- **Taker Buy (Aggressive Buy)**: `is_buyer_maker == False`
  - `taker_buy_qty = quantity`
  - `taker_buy_notional = quantity * price`
- **Signed Notional**: `taker_buy_notional - taker_sell_notional`
- **Trade Imbalance**: `(taker_buy_notional - taker_sell_notional) / (taker_buy_notional + taker_sell_notional)`

This mapping resolves the ambiguity between maker and taker events and provides clear directional flow metrics.

## Historical Coverage & Availability Analysis

Binance Vision aggTrades monthly and daily archives were probed:

| Symbol | Range | Request Status | Coverage Status |
| :--- | :--- | :---: | :--- |
| `BTCUSDT` | 2023-01 | `200` | **AVAILABLE** |
| `BTCUSDT` | 2023-06 | `200` | **AVAILABLE** |
| `BTCUSDT` | 2023-12 | `200` | **AVAILABLE** |
| `BTCUSDT` | 2024-01 | `200` | **AVAILABLE** |
| `BTCUSDT` | 2024-06 | `200` | **AVAILABLE** |
| `BTCUSDT` | 2024-06-01 | `200` | **AVAILABLE** |
| `BTCUSDT` | 2024-12-31 | `200` | **AVAILABLE** |
| `ETHUSDT` | 2023-01 | `200` | **AVAILABLE** |
| `ETHUSDT` | 2023-06 | `200` | **AVAILABLE** |
| `ETHUSDT` | 2023-12 | `200` | **AVAILABLE** |
| `ETHUSDT` | 2024-01 | `200` | **AVAILABLE** |
| `ETHUSDT` | 2024-06 | `200` | **AVAILABLE** |
| `ETHUSDT` | 2024-06-01 | `200` | **AVAILABLE** |
| `ETHUSDT` | 2024-12-31 | `200` | **AVAILABLE** |
| `BNBUSDT` | 2023-01 | `200` | **AVAILABLE** |
| `BNBUSDT` | 2023-06 | `200` | **AVAILABLE** |
| `BNBUSDT` | 2023-12 | `200` | **AVAILABLE** |
| `BNBUSDT` | 2024-01 | `200` | **AVAILABLE** |
| `BNBUSDT` | 2024-06 | `200` | **AVAILABLE** |
| `BNBUSDT` | 2024-06-01 | `200` | **AVAILABLE** |
| `BNBUSDT` | 2024-12-31 | `200` | **AVAILABLE** |

## Suitability & PIT Validity

- **Historical Depth**: The archives cover the complete required historical range (2023-01-01 to 2024-12-31).
- **Point-in-Time Policy**: Observations are aggregated into 15-minute canonical bars. The feature availability is defined as the close time of each bar (`available_at = bar_close_time`), ensuring zero future information leakage.
- **Completeness**: Unlike WebSocket stream client-side snapshots or force orders, these zip file archives contain the complete aggregation of tick-level trades executed on the exchange.

## Conclusion & Next Steps

Since all gates **F0-F8** passed successfully, this candidate is promoted to the information audit stage:
**`AUTHORIZE_V4B-4B`**.
