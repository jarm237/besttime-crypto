# HMR-V5-B1-r1: Exit Simulation Semantic & Accounting Audit Report

> **Timestamp**: `2026-08-16T17:09:36.290561+00:00` | **Validation Status**: `PASS`

## 1. Executive Summary & Verification Verdict

This audit validates the math, barrier evaluations, and PnL accounting invariants of the exit simulation.
Based on the results, we declare a complete **`PASS`** on semantic and accounting validation. The simulation logic is mathematically sound.

---

## 2. Invariant Checklist Validation Results

| Invariant | Description | Status | Verification Detail |
| :--- | :--- | :---: | :--- |
| **1. Exit-price signs** | TP returns > 0, SL returns < 0 | **`PASS`** | Confirmed for all BTC signals. |
| **2. Barrier placement** | BUY: TP > SL, SELL: TP < SL | **`PASS`** | Verified mathematically relative to entry price. |
| **3. Realized-return formula**| side_adjusted return bps checked | **`PASS`** | Matches raw/realized returns within 1e-4 bps. |
| **4. Outcome count** | `n_tp + n_sl + n_timeout = n_trades` | **`PASS`** | Reconciled perfectly for BUY & SELL. |
| **5. EV reconciliation** | `mean(realized_return_bps) = gross_ev`| **`PASS`** | Reconciliation error = 0.0000 bps. |
| **6. Cond. returns** | Compute conditional EVs | **`PASS`** | Reported below. |
| **7. Same-bar collision** | TP + SL in same bar => SL | **`PASS`** | SL priority verified. Collision counts reported. |
| **8. Path boundary** | Eval starts strictly after entry | **`PASS`** | Entry bar offset is excluded from exits. |
| **9. No future-bar reuse** | signal window strictly post-entry | **`PASS`** | Future reuse boundary respected. |
| **10. Mirror symmetry** | Mirrored paths yield mirrored PnL | **`PASS`** | Verified on synthetic mirrored test data. |

---

## 3. Realized Return and Outcome Reconciliation Metrics (BTC)

### Exit Family `E2` Reconciliation

#### BTC `BUY` (E2)

- Total Trades evaluated: `28453`
- Gross EV reported: `21.2384 bps`
- Same-bar collisions (TP+SL): `0` (All conservatively marked as SL)
- **Conditional Payoff Means**:
  - Target Hits (TP): `84.02 bps` (Count: `12836`, Expectation: positive)
  - Stop Losses (SL): `-50.50 bps` (Count: `11114`, Expectation: negative)
  - Timeouts: `19.36 bps` (Count: `4503`)

#### BTC `SELL` (E2)

- Total Trades evaluated: `28419`
- Gross EV reported: `20.7076 bps`
- Same-bar collisions (TP+SL): `0` (All conservatively marked as SL)
- **Conditional Payoff Means**:
  - Target Hits (TP): `83.52 bps` (Count: `12749`, Expectation: positive)
  - Stop Losses (SL): `-50.44 bps` (Count: `11151`, Expectation: negative)
  - Timeouts: `19.04 bps` (Count: `4519`)

### Exit Family `E4` Reconciliation

#### BTC `BUY` (E4)

- Total Trades evaluated: `28453`
- Gross EV reported: `29.9670 bps`
- Same-bar collisions (TP+SL): `39` (All conservatively marked as SL)
- **Conditional Payoff Means**:
  - Target Hits (TP): `50.00 bps` (Count: `21328`, Expectation: positive)
  - Stop Losses (SL): `-30.00 bps` (Count: `7125`, Expectation: negative)
  - Timeouts: `0.00 bps` (Count: `0`)

#### BTC `SELL` (E4)

- Total Trades evaluated: `28419`
- Gross EV reported: `29.8135 bps`
- Same-bar collisions (TP+SL): `28` (All conservatively marked as SL)
- **Conditional Payoff Means**:
  - Target Hits (TP): `50.00 bps` (Count: `21248`, Expectation: positive)
  - Stop Losses (SL): `-30.00 bps` (Count: `7171`, Expectation: negative)
  - Timeouts: `0.00 bps` (Count: `0`)

---

## 4. Trade Sample Verification Preview (E4 SL/TP 50/30 bps)

| ID | Side | Entry Time | Entry Price | TP Price | SL Price | Exit Time | Exit Reason | Realized Return (bps) |
| :--- | :---: | :--- | :---: | :---: | :---: | :--- | :---: | :---: |
| `BTC_BUY_0` | `BUY` | 2023-01-01 00:30:00 | 43.14 | 43.36 | 43.01 | 2023-01-01 01:00:00 | `TP` | 50.00 |
| `BTC_BUY_1` | `BUY` | 2023-01-01 00:45:00 | 43.32 | 43.53 | 43.19 | 2023-01-01 01:30:00 | `TP` | 50.00 |
| `BTC_BUY_2` | `BUY` | 2023-01-01 02:00:00 | 43.14 | 43.36 | 43.01 | 2023-01-01 02:30:00 | `TP` | 50.00 |
| `BTC_BUY_5` | `BUY` | 2023-01-01 03:45:00 | 43.11 | 43.33 | 42.98 | 2023-01-01 04:00:00 | `TP` | 50.00 |
| `BTC_BUY_6` | `BUY` | 2023-01-01 04:15:00 | 43.13 | 43.35 | 43.00 | 2023-01-01 05:00:00 | `TP` | 50.00 |
| `BTC_BUY_3` | `BUY` | 2023-01-01 02:15:00 | 43.33 | 43.55 | 43.20 | 2023-01-01 03:45:00 | `SL` | -30.00 |
| `BTC_BUY_4` | `BUY` | 2023-01-01 02:45:00 | 43.34 | 43.55 | 43.21 | 2023-01-01 03:45:00 | `SL` | -30.00 |
| `BTC_BUY_7` | `BUY` | 2023-01-01 04:30:00 | 43.33 | 43.55 | 43.20 | 2023-01-01 07:30:00 | `SL` | -30.00 |
| `BTC_BUY_10` | `BUY` | 2023-01-01 06:00:00 | 43.35 | 43.57 | 43.22 | 2023-01-01 07:30:00 | `SL` | -30.00 |
| `BTC_BUY_11` | `BUY` | 2023-01-01 06:15:00 | 43.35 | 43.57 | 43.22 | 2023-01-01 07:30:00 | `SL` | -30.00 |
| `BTC_SELL_2` | `SELL` | 2023-01-01 01:45:00 | 43.54 | 43.32 | 43.67 | 2023-01-01 02:00:00 | `TP` | 50.00 |
| `BTC_SELL_3` | `SELL` | 2023-01-01 03:15:00 | 43.46 | 43.24 | 43.59 | 2023-01-01 03:45:00 | `TP` | 50.00 |
| `BTC_SELL_5` | `SELL` | 2023-01-01 04:00:00 | 43.46 | 43.25 | 43.59 | 2023-01-01 04:15:00 | `TP` | 50.00 |
| `BTC_SELL_6` | `SELL` | 2023-01-01 05:00:00 | 43.47 | 43.25 | 43.60 | 2023-01-01 05:15:00 | `TP` | 50.00 |
| `BTC_SELL_7` | `SELL` | 2023-01-01 05:15:00 | 43.39 | 43.17 | 43.52 | 2023-01-01 07:30:00 | `TP` | 50.00 |
| `BTC_SELL_0` | `SELL` | 2023-01-01 00:00:00 | 43.29 | 43.08 | 43.42 | 2023-01-01 01:00:00 | `SL` | -30.00 |
| `BTC_SELL_1` | `SELL` | 2023-01-01 00:15:00 | 43.32 | 43.10 | 43.45 | 2023-01-01 01:30:00 | `SL` | -30.00 |
| `BTC_SELL_4` | `SELL` | 2023-01-01 03:30:00 | 43.29 | 43.07 | 43.42 | 2023-01-01 04:00:00 | `SL` | -30.00 |
| `BTC_SELL_19` | `SELL` | 2023-01-01 14:30:00 | 43.43 | 43.21 | 43.56 | 2023-01-01 16:00:00 | `SL` | -30.00 |
| `BTC_SELL_26` | `SELL` | 2023-01-01 19:00:00 | 43.35 | 43.13 | 43.48 | 2023-01-01 20:00:00 | `SL` | -30.00 |
