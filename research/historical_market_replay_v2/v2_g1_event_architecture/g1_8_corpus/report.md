# HMR-V2-G1.8: Architecture Corpus Expansion

Period: **2023-01-01** → **2024-12-31**

Frozen manifest SHA256: `f67674cce979d538...`

## 1. Canonical Economic Matrix

| Metric | G1-A Raw Event | G1-B Compression | G1-D Both |
|:-------|:--------------:|:----------------:|:---------:|
| n | 98016 | 16183 | 10828 |
| Mean @72 (bps) | -22.42 | -1.26 | -0.74 |
| Median @72 (bps) | -21.32 | -1.05 | -0.76 |
| Gross >30 rate | 8.6% | 18.3% | 18.9% |
| Gross >30 count | 8407 | 2962 | 2051 |
| Gross >40 rate | 5.0% | 11.3% | 11.9% |
| Gross >40 count | 4941 | 1834 | 1286 |
| Net+ rate | 16.5% | 31.5% | 31.8% |
| Mean @8 (bps) | -22.37 | -1.28 | -0.55 |

## 2. Per-Symbol Gross>30 Rate

| Symbol | G1-A | G1-B | G1-D |
|:-------|:----:|:----:|:----:|
| BNB | 8.6% | 18.1% | 18.5% |
| BTC | 6.4% | 13.7% | 14.3% |
| ETH | 10.7% | 22.5% | 23.4% |

## 3. Per-Side Gross>30 Rate

| Side | G1-A | G1-B | G1-D |
|:-----|:----:|:----:|:----:|
| BUY | 8.8% | 18.7% | 19.4% |
| SELL | 8.4% | 17.9% | 18.4% |

## 4. Overlap Audit (G1-D ⊂ G1-B)

| Segment | n | Mean @72 | Gross>30 | Gross>40 |
|:--------|--:|:--------:|:--------:|:--------:|
| G1-B total | 16183 | -1.26 | 18.3% | 11.3% |
| G1-B only (excl D) | 5355 | -2.30 | 17.0% | 10.2% |
| G1-D | 10828 | -0.74 | 18.9% | 11.9% |

> **Overlap verdict**: `ROOM_INCREMENTAL_VALUE = MARGINAL (B-only ≈ D)`


## 5. Gate Verdicts

* **G1-B Compression**: `PASS_PREFERRED` (Gross>30 positives=2962, Gross>40 positives=1834)
* **G1-D Both**: `PASS_PREFERRED` (Gross>30 positives=2051, Gross>40 positives=1286)
