# HMR-V5-C0: Economic Learning Contract Freeze

This contract locks the model objective parameters, candidate entry definitions, exit architecture, cost floors, and execution policies for the machine learning research phase (`V5-C`).

---

## 1. Frozen Target Definition

Model classification targets will be computed directly from exit architecture **E4**:

- **Target ($Y$)**: `TP_BEFORE_SL`
  - $Y = 1$: TP (+50 bps) reached before SL (-30 bps).
  - $Y = 0$: SL (-30 bps) reached before TP (+50 bps).
  - Same-bar collision: Conservatively marked as SL ($Y = 0$).
- **Continuous Targets**:
  - `realized_gross_bps`
  - `realized_maker_net_bps`
  - `realized_taker_net_bps`

---

## 2. Frozen Execution & Cost Environment

- **Execution Policy**: `P4` (Production Capacity)
  - Max 2 concurrent positions per asset.
  - Max 3 concurrent positions globally.
  - Cooldown of 4 bars (1 hour) post-exit.
  - Side locked per asset (no opposite sides).
- **Cost Floors**:
  - Maker Cost Floor: **`7.0 bps`** (`MAKER_REALISTIC`)
  - Taker Cost Floor: **`15.0 bps`** (`TAKER_REALISTIC`)

---

## 3. Canonical Benchmark: NO-ML P4

All machine learning models trained in future steps must be evaluated against this deterministic benchmark:

| Metric (BTC) | Frozen Benchmark Value |
| :--- | :--- |
| **Gross EV** | **`+30.59 bps`** |
| **Net Maker EV** | **`+23.59 bps`** |
| **Net Taker EV** | **`+15.59 bps`** |
| **Implied TP Probability** | **`~75.7%`** |
| **Executed Trades** | **`8,373`** |
