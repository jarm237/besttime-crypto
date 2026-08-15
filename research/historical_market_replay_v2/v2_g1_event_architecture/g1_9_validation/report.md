# HMR-V2-G1.9: Architecture Validation

Period: **2025-04-01** → **2025-06-30**

Frozen manifest SHA256: `f67674cce979d538...`

## 1. Canonical Economic Matrix

| Metric | G1-A Raw Event | G1-B Compression | G1-D Both |
|:-------|:--------------:|:----------------:|:---------:|
| n | 12361 | 2014 | 1306 |
| Mean @72 (bps) | -22.11 | -2.21 | -1.50 |
| Median @72 (bps) | -21.59 | -2.21 | -1.73 |
| Gross >30 rate | 8.6% | 18.8% | 19.6% |
| Gross >30 count | 1064 | 379 | 256 |
| Gross >40 rate | 5.0% | 11.9% | 13.0% |
| Gross >40 count | 613 | 239 | 170 |
| Net+ rate | 16.8% | 31.6% | 32.1% |
| Mean @8 (bps) | -21.73 | -1.80 | -2.49 |

## 2. Per-Symbol Gross>30 Rate

| Symbol | G1-A | G1-B | G1-D |
|:-------|:----:|:----:|:----:|
| BNB | 8.0% | 18.4% | 19.2% |
| BTC | 7.6% | 17.1% | 19.5% |
| ETH | 10.2% | 20.8% | 20.1% |

## 3. Per-Side Gross>30 Rate

| Side | G1-A | G1-B | G1-D |
|:-----|:----:|:----:|:----:|
| BUY | 9.3% | 19.4% | 21.1% |
| SELL | 7.9% | 18.3% | 18.2% |

## 4. Overlap Audit (G1-D ⊂ G1-B)

| Segment | n | Mean @72 | Gross>30 | Gross>40 |
|:--------|--:|:--------:|:--------:|:--------:|
| G1-B total | 2014 | -2.21 | 18.8% | 11.9% |
| G1-B only (excl D) | 708 | -3.50 | 17.4% | 9.8% |
| G1-D | 1306 | -1.50 | 19.6% | 13.0% |

> **Overlap verdict**: `ROOM_INCREMENTAL_VALUE = MARGINAL (B-only ≈ D)`


## 5. Gate Verdicts

* **G1-B Compression**: `PASS_PREFERRED` (Gross>30=18.8%, Mean=-2.21 bps, n=2014)
* **G1-D Both**: `PASS_PREFERRED` (Gross>30=19.6%, Mean=-1.50 bps, n=1306)
