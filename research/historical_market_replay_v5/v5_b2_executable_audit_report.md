# HMR-V5-B2: Executable Trade Stream Audit Report

> **Timestamp**: `2026-08-16T17:15:05.579848+00:00` | **Exit Basis**: `E4`

## 1. Governance Audit Verdict & Gate Results

- **Audit Verdict**: **`PROMOTE_EXECUTABLE_BASELINE`**

**Verdict Rationale**: E4 exit survives serialization constraints with robust Net EV under both Maker and Taker costs.

### Governance Gates Evaluation Status

| Gate | Description | Status |
| :--- | :--- | :---: |
| `B2-G0` | Gate Criteria | **`PASS`** |
| `B2-G1` | Gate Criteria | **`PASS`** |
| `B2-G2` | Gate Criteria | **`PASS`** |
| `B2-G3` | Gate Criteria | **`PASS (Non-required)`** |
| `B2-G4` | Gate Criteria | **`PASS`** |
| `B2-G5` | Gate Criteria | **`PASS`** |
| `B2-G6` | Gate Criteria | **`PASS`** |
| `B2-G7` | Gate Criteria | **`PASS`** |
| `B2-G8` | Gate Criteria | **`PASS`** |

---

## 2. Policy-Wise Metric Comparison (BTC)

| Policy | Executed | Overlaps | Conflicts | Gross EV (bps) | Net EV (Maker) | Net EV (Taker) | Edge Retention | Sharpe | Max DD % | Ann. Net PnL |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `P0` | 56872 | 0 | 0 | 29.89 | 22.89 | 14.89 | 2289.0% | 104.60 | 0.00% | 63139.27% |
| `P1` | 12986 | 43886 | 0 | 30.10 | 23.10 | 15.10 | 100.9% | 41.44 | 0.09% | 346.41% |
| `P2` | 12986 | 43886 | 0 | 30.10 | 23.10 | 15.10 | 100.9% | 41.44 | 0.09% | 346.41% |
| `P3` | 31258 | 0 | 25614 | 28.64 | 21.64 | 13.64 | 94.5% | 54.84 | 0.03% | 2789.97% |
| `P4` | 8373 | 48499 | 0 | 30.59 | 23.59 | 15.59 | 103.1% | 39.59 | 0.25% | 168.09% |

---

## 3. Multi-Asset Portfolio Replay (P4 Production Capacity)

| Asset | Executed | Gross EV (bps) | Net EV (Maker) | Sharpe | Max DD % | Ann. Net PnL | Exposure % | Avg Hold (bars) | Concurrency Peak |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `BTC` | 8373 | 30.59 | 23.59 | 39.59 | 0.25% | 168.09% | 49.4% | 4.1 | 1 |
| `ETH` | 11831 | 40.38 | 33.38 | 89.91 | 0.00% | 616.29% | 28.1% | 1.7 | 1 |
| `BNB` | 10369 | 35.43 | 28.43 | 58.10 | 0.00% | 335.20% | 37.4% | 2.5 | 1 |
| `COMBINED` | 30573 | 36.02 | 29.02 | 103.92 | 0.00% | 8115.32% | 100.0% | 2.6 | 3 |
