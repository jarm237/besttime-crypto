# P8 — Economic Effectiveness Evaluation Report

> [!WARNING]
> **P8 State: ACCUMULATING**
> - P8 Data Integrity: **PASS**
> - Population Reconciliation: **PASS**
> - Accounting Reconciliation: **PASS**
> - Primary Population: **CURRENT_CANARY**
> - Data Source: **LOCAL_WINDOWS_WORKSPACE**
> - Canonical Runtime Evidence: **NOT_PRESENT (ACCUMULATING locally)**
> - Current Closed Trades: **0**
> - Current Fills: **0**
> - Current Closure Rate: **0.00%**
> - Sample Maturity: **ACCUMULATING**
> - Economic Verdict: **ECONOMIC_VERDICT_NOT_AUTHORIZED_YET**
> - Model/Policy Change: **NOT_AUTHORIZED** / **NOT_AUTHORIZED**
> - Runtime Remediation: **NOT_REQUIRED**

---

## 1. Signal Funnel Analysis (Exploratory / Broader Historical Scope)

> [!NOTE]
> This funnel represents the broader/historical signal path across the database window (exploratory scope). Funnel rates (such as execution rate) should not be interpreted as the conversion rates of the current canary population.

| Funnel Stage | Count | Transition Rate |
| :--- | :---: | :---: |
| **Predictions** | 0 | — |
| **Final Decisions** | 0 | Prediction $\rightarrow$ Decision: 0.00% |
| **Actionable Decisions** | 0 | Actionable Rate: 0.00% |
| **Execution Attempts** | 0 | Execution Rate: 0.00% |
| **Fills** | 0 | Fill Rate: 0.00% |
| **Closed Trades** | 0 | Closure Rate (Canary): 0.00% |

---

## 2. Split Populations Performance Economics

Performance metrics aggregated across each population.

| Metric | Current Canary | Historical Backfill | Combined |
| :--- | :---: | :---: | :---: |
| **Trade Count (N)** | 0 | 0 | 0 |
| **Win Rate (WR)** | 0.00% | 0.00% | 0.00% |
| **Gross Expected Value (EV)** | 0.00 bps | 0.00 bps | 0.00 bps |
| **Net Expected Value (EV)** | 0.00 bps | 0.00 bps | 0.00 bps |
| **Profit Factor (PF)** | 0.00 | 0.00 | 0.00 |
| **Total Net PnL** | $0.00 | $0.00 | $0.00 |
| **Max Drawdown (bps)** | 0.00 bps | 0.00 bps | 0.00 bps |

---

## 3. Route Attribution (Combined Population)

Separates the performance of the Legacy routing (`BTC`, `ETH`, `BNB`) and the new MC5 Qualification routing (`6 other symbols`).

| Route | Trade Count | Win Rate | Gross EV | Net EV | Profit Factor | Net PnL | Max DD |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **LEGACY** | 0 | 0.0% | 0.00 bps | 0.00 bps | 0.00 | $0.00 | 0.00 bps |
| **MC5_QUALIFIED** | 0 | 0.0% | 0.00 bps | 0.00 bps | 0.00 | $0.00 | 0.00 bps |

---

## 4. Symbol Level Attribution (Combined Population)

Attribution metrics broken down per symbol across combined population.

| Symbol | Trades | Win Rate | Gross EV | Net EV | PF | Net PnL (USD) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **BNB** | 0 | — | — | — | — | $0.00 |
| **BTC** | 0 | — | — | — | — | $0.00 |
| **DOGE** | 0 | — | — | — | — | $0.00 |
| **ETH** | 0 | — | — | — | — | $0.00 |
| **IOTA** | 0 | — | — | — | — | $0.00 |
| **NEAR** | 0 | — | — | — | — | $0.00 |
| **SOL** | 0 | — | — | — | — | $0.00 |
| **TRX** | 0 | — | — | — | — | $0.00 |
| **ZEC** | 0 | — | — | — | — | $0.00 |

---

## 5. Model Score / Confidence vs Realized Outcome (Combined Population)

Buckets closed trades by model confidence score to examine the ranking capabilities of the model.

| Bucket (Quantile) | Trades | Mean Net Return | Median Net Return | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: |

---

## 6. Economic Sample Reconciliation (Audit)

Comprehensive trade-by-trade financial audit and population reconciliation.

| Trade ID | Symbol | Route | Decision ID | Execution ID | Entry Price | Exit Price | Gross Return | Fee Bps | Net Return | Gross PnL | Fees | Net PnL | Backfill | Partition |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |

---

## 7. Data Limitations

- **Slippage Accounting**: `NOT_AVAILABLE` (Slippage is not explicitly written in outcome links and is marked as not available for this run).
- **Other Transaction Costs**: `NOT_AVAILABLE`.

---

*Report Generated At (UTC): 2026-08-27T13:29:05.413007+00:00*
