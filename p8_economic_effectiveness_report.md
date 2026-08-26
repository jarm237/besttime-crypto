# P8 — Economic Effectiveness Evaluation Report

> [!WARNING]
> **P8 State: ACCUMULATING**
> - P8 Data Integrity: **PASS**
> - Population Reconciliation: **PASS**
> - Accounting Reconciliation: **PASS**
> - Primary Population: **CURRENT_CANARY**
> - Current Closed Trades: **2**
> - Current Fills: **3**
> - Current Closure Rate: **66.67%**
> - Sample Maturity: **PRELIMINARY**
> - Economic Verdict: **ECONOMIC_VERDICT_NOT_AUTHORIZED_YET**
> - Model/Policy Change: **NOT_AUTHORIZED** / **NOT_AUTHORIZED**
> - Runtime Remediation: **NOT_REQUIRED**

---

## 1. Signal Funnel Analysis (Exploratory / Broader Historical Scope)

> [!NOTE]
> This funnel represents the broader/historical signal path across the database window (exploratory scope). Funnel rates (such as execution rate) should not be interpreted as the conversion rates of the current canary population.

| Funnel Stage | Count | Transition Rate |
| :--- | :---: | :---: |
| **Predictions** | 8078 | — |
| **Final Decisions** | 4315 | Prediction $\rightarrow$ Decision: 53.42% |
| **Actionable Decisions** | 160 | Actionable Rate: 3.71% |
| **Execution Attempts** | 3 | Execution Rate: 1.88% |
| **Fills** | 3 | Fill Rate: 100.00% |
| **Closed Trades** | 2 | Closure Rate (Canary): 66.67% |

---

## 2. Split Populations Performance Economics

Performance metrics aggregated across each population.

| Metric | Current Canary | Historical Backfill | Combined |
| :--- | :---: | :---: | :---: |
| **Trade Count (N)** | 2 | 14 | 16 |
| **Win Rate (WR)** | 0.00% | 35.71% | 31.25% |
| **Gross Expected Value (EV)** | -27.28 bps | -60.32 bps | -56.19 bps |
| **Net Expected Value (EV)** | -47.28 bps | -60.32 bps | -58.69 bps |
| **Profit Factor (PF)** | 0.00 | 0.30 | 0.28 |
| **Total Net PnL** | $-0.71 | $-5.43 | $-6.14 |
| **Max Drawdown (bps)** | 94.56 bps | 866.66 bps | 961.22 bps |

---

## 3. Route Attribution (Combined Population)

Separates the performance of the Legacy routing (`BTC`, `ETH`, `BNB`) and the new MC5 Qualification routing (`6 other symbols`).

| Route | Trade Count | Win Rate | Gross EV | Net EV | Profit Factor | Net PnL | Max DD |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **LEGACY** | 9 | 44.4% | -4.19 bps | -8.64 bps | 0.78 | $-0.55 | 357.01 bps |
| **MC5_QUALIFIED** | 7 | 14.3% | -123.05 bps | -123.05 bps | 0.09 | $-5.59 | 861.35 bps |

---

## 4. Symbol Level Attribution (Combined Population)

Attribution metrics broken down per symbol across combined population.

| Symbol | Trades | Win Rate | Gross EV | Net EV | PF | Net PnL (USD) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **BNB** | 2 | 50.0% | 0.58 bps | -9.43 bps | 0.60 | $-0.15 |
| **BTC** | 1 | 100.0% | 68.87 bps | 68.87 bps | 999.00 | $0.52 |
| **DOGE** | 2 | 0.0% | -143.19 bps | -143.19 bps | 0.00 | $-2.15 |
| **ETH** | 6 | 33.3% | -17.96 bps | -21.29 bps | 0.59 | $-0.92 |
| **IOTA** | 0 | — | — | — | — | $0.00 |
| **NEAR** | 2 | 0.0% | -109.97 bps | -109.97 bps | 0.00 | $-0.77 |
| **SOL** | 1 | 100.0% | 83.13 bps | 83.13 bps | 999.00 | $0.62 |
| **TRX** | 0 | — | — | — | — | $0.00 |
| **ZEC** | 2 | 0.0% | -219.08 bps | -219.08 bps | 0.00 | $-3.29 |

---

## 5. Model Score / Confidence vs Realized Outcome (Combined Population)

Buckets closed trades by model confidence score to examine the ranking capabilities of the model.

| Bucket (Quantile) | Trades | Mean Net Return | Median Net Return | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Q1** | 3 | -140.27 bps | -163.66 bps | 0.0% | 0.00 |
| **Q2** | 3 | -127.06 bps | -131.99 bps | 0.0% | 0.00 |
| **Q3** | 3 | -134.99 bps | -86.34 bps | 0.0% | 0.00 |
| **Q4** | 3 | 83.54 bps | 68.87 bps | 100.0% | 999.00 |
| **Q5** | 4 | 4.31 bps | -9.21 bps | 50.0% | 1.18 |

---

## 6. Economic Sample Reconciliation (Audit)

Comprehensive trade-by-trade financial audit and population reconciliation.

| Trade ID | Symbol | Route | Decision ID | Execution ID | Entry Price | Exit Price | Gross Return | Fee Bps | Net Return | Gross PnL | Fees | Net PnL | Backfill | Partition |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `9b1cfb99` | **ETH** | LEGACY | `259e5a5b` | `NOT_AVAI` | 1574.44 | 1576.59 | 13.66 | NOT_AVAILABLE | 13.66 | $0.14 | NOT_AVAILABLE | $0.14 | True | `historical-backfill-2026q1` |
| `66e950a1` | **NEAR** | MC5_QUALIFIED | `0385f4ae` | `NOT_AVAI` | 1.93 | 1.91 | -83.44 | NOT_AVAILABLE | -83.44 | $-0.63 | NOT_AVAILABLE | $-0.63 | True | `historical-backfill-2026q1` |
| `018e4131` | **BTC** | LEGACY | `cce7b0c0` | `NOT_AVAI` | 64206.79 | 63764.57 | 68.87 | NOT_AVAILABLE | 68.87 | $0.52 | NOT_AVAILABLE | $0.52 | True | `historical-backfill-2026q1` |
| `eba7e7b5` | **DOGE** | MC5_QUALIFIED | `4d512d40` | `NOT_AVAI` | 0.07 | 0.07 | -173.70 | NOT_AVAILABLE | -173.70 | $-1.30 | NOT_AVAILABLE | $-1.30 | True | `historical-backfill-2026q1` |
| `d4aeee33` | **ETH** | LEGACY | `fb79dad5` | `NOT_AVAI` | 1806.86 | 1776.49 | 168.08 | NOT_AVAILABLE | 168.08 | $1.26 | NOT_AVAILABLE | $1.26 | True | `historical-backfill-2026q1` |
| `7768e65f` | **BNB** | LEGACY | `8d2c7fae` | `NOT_AVAI` | 568.54 | 566.91 | 28.65 | NOT_AVAILABLE | 28.65 | $0.21 | NOT_AVAILABLE | $0.21 | True | `historical-backfill-2026q1` |
| `54615e4c` | **ZEC** | MC5_QUALIFIED | `2adda402` | `NOT_AVAI` | 558.35 | 567.49 | -163.66 | NOT_AVAILABLE | -163.66 | $-1.23 | NOT_AVAILABLE | $-1.23 | True | `historical-backfill-2026q1` |
| `1966b216` | **SOL** | MC5_QUALIFIED | `4e83b67e` | `NOT_AVAI` | 77.72 | 78.37 | 83.13 | NOT_AVAILABLE | 83.13 | $0.62 | NOT_AVAILABLE | $0.62 | True | `historical-backfill-2026q1` |
| `2fb8e0c7` | **DOGE** | MC5_QUALIFIED | `67ac5817` | `NOT_AVAI` | 0.07 | 0.07 | -112.69 | NOT_AVAILABLE | -112.69 | $-0.85 | NOT_AVAILABLE | $-0.85 | True | `historical-backfill-2026q1` |
| `dc1306b4` | **ZEC** | MC5_QUALIFIED | `6c5b5ce6` | `NOT_AVAI` | 553.65 | 538.45 | -274.50 | NOT_AVAILABLE | -274.50 | $-2.06 | NOT_AVAILABLE | $-2.06 | True | `historical-backfill-2026q1` |
| `6a797da8` | **ETH** | LEGACY | `c7213559` | `NOT_AVAI` | 1873.97 | 1849.24 | -131.99 | NOT_AVAILABLE | -131.99 | $-0.99 | NOT_AVAILABLE | $-0.99 | True | `historical-backfill-2026q1` |
| `2540e418` | **NEAR** | MC5_QUALIFIED | `88202a3b` | `NOT_AVAI` | 1.91 | 1.94 | -136.49 | NOT_AVAILABLE | -136.49 | $-0.14 | NOT_AVAILABLE | $-0.14 | True | `historical-backfill-2026q1` |
| `866e297b` | **ETH** | LEGACY | `39aeff06` | `NOT_AVAI` | 1936.99 | 1945.54 | -44.12 | NOT_AVAILABLE | -44.12 | $-0.33 | NOT_AVAILABLE | $-0.33 | True | `historical-backfill-2026q1` |
| `d5a929d8` | **ETH** | LEGACY | `20b53f81` | `NOT_AVAI` | 1929.26 | 1912.60 | -86.34 | NOT_AVAILABLE | -86.34 | $-0.65 | NOT_AVAILABLE | $-0.65 | True | `historical-backfill-2026q1` |
| `49d14c88` | **BNB** | LEGACY | `ab096d96` | `sig-6839` | 604.30 | 607.17 | -27.50 | 20.00 | -47.50 | $-0.21 | $0.15 | $-0.36 | False | `local-production` |
| `7d503019` | **ETH** | LEGACY | `c1aa0987` | `sig-f38f` | 1903.11 | 1894.15 | -27.06 | 20.00 | -47.06 | $-0.20 | $0.15 | $-0.35 | False | `local-production` |

---

## 7. Data Limitations

- **Slippage Accounting**: `NOT_AVAILABLE` (Slippage is not explicitly written in outcome links and is marked as not available for this run).
- **Other Transaction Costs**: `NOT_AVAILABLE`.

---

*Report Generated At (UTC): 2026-08-26T03:25:56.924861+00:00*
