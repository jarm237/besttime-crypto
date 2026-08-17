# HMR-V5-B1: Path-Aware Exit Capture Audit Report

> **Timestamp**: `2026-08-16T17:14:24.688874+00:00` | **Governance Cost Contract**: `HMR-V5-B0`

## 1. Governance Audit Verdict

- **Audit Verdict**: **`PROMOTE_EXIT_ARCHITECTURE`**
- **Promotion Status**: **`PROMOTED`**
- **Promoted Exit**: **`E4 — TP +50 bps / SL -30 bps`**
- **ML Training**: **`BLOCKED`**

**Verdict Rationale**: Exit family E4 is promoted as the optimal exit architecture baseline based on HMR-V5-B1-r1 validation verification.

---

## 2. Frozen Cost Reference

| Scenario | Cost Floor (bps) | Description |
| :--- | :---: | :--- |
| `RESEARCH_IDEALIZED` | 2.5 | VIP tier trading with zero execution slippage and extremely narrow spread, matching the historical V5-A1 baseline assumptions. |
| `MAKER_REALISTIC` | 7.0 | Realistic passive order placement using standard maker fee tier (2.0 bps), accounting for toxic flow adverse selection and execution deviation. |
| `TAKER_REALISTIC` | 15.0 | Aggressive market order crossing standard taker fee tier (5.0 bps), matching typical Binance retail taker conditions with expected orderbook slippage. |

---

## 3. Exit Capture Metrics Summary (BTC)

### BTC BUY Side Exits

| Family | Description | Gross EV (bps) | Net EV (Idealized) | Net EV (Maker) | Net EV (Taker) | Capture Ratio | Stop Hit % | Target Hit % | Timeout % | Avg Hold (bars) | Sharpe | Max DD % |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `E0` | Fixed Horizon (24h) | 19.65 | 17.15 | 12.65 | 4.65 | 1.75 | 0.0% | 0.0% | 100.0% | 96.0 | 8.3503 | 17.85% |
| `E1` | Baseline SL/TP (30/20 bps) | 30.00 | 27.50 | 23.00 | 15.00 | 11.16 | 0.0% | 100.0% | 0.0% | 1.5 | 0.0000 | 0.00% |
| `E2` | ATR SL/TP (2.0/1.2 ATR) | 21.24 | 18.74 | 14.24 | 6.24 | 2.10 | 39.1% | 45.1% | 15.8% | 38.4 | 4.7649 | 22.33% |
| `E3` | Trailing Stop (20 bps) | 25.58 | 23.08 | 18.58 | 10.58 | 13.14 | 100.0% | 0.0% | 0.0% | 2.3 | 19.3135 | 0.47% |
| `E4` | SL/TP Variant (50/30 bps) | 29.97 | 27.47 | 22.97 | 14.97 | 6.57 | 25.0% | 75.0% | 0.0% | 4.2 | 12.2272 | 3.36% |

### BTC SELL Side Exits

| Family | Description | Gross EV (bps) | Net EV (Idealized) | Net EV (Maker) | Net EV (Taker) | Capture Ratio | Stop Hit % | Target Hit % | Timeout % | Avg Hold (bars) | Sharpe | Max DD % |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `E0` | Fixed Horizon (24h) | 17.99 | 15.49 | 10.99 | 2.99 | 1.73 | 0.0% | 0.0% | 100.0% | 96.0 | 7.6466 | 21.84% |
| `E1` | Baseline SL/TP (30/20 bps) | 30.00 | 27.50 | 23.00 | 15.00 | 10.83 | 0.0% | 100.0% | 0.0% | 1.5 | 0.0000 | 0.00% |
| `E2` | ATR SL/TP (2.0/1.2 ATR) | 20.71 | 18.21 | 13.71 | 5.71 | 2.09 | 39.2% | 44.9% | 15.9% | 38.5 | 4.6664 | 21.54% |
| `E3` | Trailing Stop (20 bps) | 25.62 | 23.12 | 18.62 | 10.62 | 13.46 | 100.0% | 0.0% | 0.0% | 2.3 | 19.4197 | 0.44% |
| `E4` | SL/TP Variant (50/30 bps) | 29.81 | 27.31 | 22.81 | 14.81 | 6.61 | 25.2% | 74.8% | 0.0% | 4.2 | 12.1338 | 3.35% |

---

## 4. Multi-Asset Performance Summary (E2 ATR SL/TP)

| Asset | Side | Gross EV (bps) | Net EV (Maker) | Capture Ratio | Stop Hit % | Target Hit % | Timeout % | Sharpe | Max DD % |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `BTC` | `BUY` | 21.24 | 14.24 | 2.10 | 39.1% | 45.1% | 15.8% | 4.7649 | 22.33% |
| `BTC` | `SELL` | 20.71 | 13.71 | 2.09 | 39.2% | 44.9% | 15.9% | 4.6664 | 21.54% |
| `ETH` | `BUY` | 34.98 | 27.98 | 2.12 | 37.0% | 45.0% | 18.0% | 5.1145 | 36.78% |
| `ETH` | `SELL` | 30.72 | 23.72 | 2.07 | 38.8% | 42.9% | 18.3% | 4.5127 | 43.42% |
| `BNB` | `BUY` | 24.50 | 17.50 | 2.05 | 40.1% | 44.0% | 15.9% | 4.5023 | 37.24% |
| `BNB` | `SELL` | 25.36 | 18.36 | 2.09 | 38.8% | 44.7% | 16.6% | 4.7100 | 35.09% |
