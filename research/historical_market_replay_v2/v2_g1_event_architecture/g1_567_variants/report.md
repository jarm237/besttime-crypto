# HMR-V2-G1.5/6/7: Architecture Variants — Coverage & Economic Evaluation

## G1.5 — Frozen Threshold Declarations

```
COMPRESSION GATE
  break_distance_atr  <= 0.25
  candle_body_atr     <= 0.15

OPPORTUNITY GATE
  room_to_structure_atr >= 1.0
```

| Variant | Rules |
|:--------|:------|
| `G1A_EVENT_ONLY` | Fresh SMA50 crossing. No filters. Control. |
| `G1B_COMPRESSION` | break_distance_atr <= 0.25 AND candle_body_atr <= 0.15. |
| `G1C_OPPORTUNITY` | room_to_structure_atr >= 1.0. |
| `G1D_COMPRESSION_OPPORT` | break_distance_atr <= 0.25 AND candle_body_atr <= 0.15 AND room_to_structure_atr >= 1.0. |

## G1.6 — Coverage Audit

Total G1-A events (raw crossing pool): **1117**

| Variant | n | Survival | Coverage OK | Warnings |
|:--------|--:|:--------:|:-----------:|:---------|
| `G1A_EVENT_ONLY` | 1117 | 100.0% | ✓ | — |
| `G1B_COMPRESSION` | 159 | 14.2% | ✓ | — |
| `G1C_OPPORTUNITY` | 389 | 34.8% | ✓ | — |
| `G1D_COMPRESSION_OPPORT` | 129 | 11.6% | ✓ | — |

## G1.7 — Target-Aligned Economic Evaluation (72-bar + 8-bar)

| Metric | G1-A Event | G1-B Compression | G1-C Opportunity | G1-D Both |
|:-------|:----------:|:----------------:|:----------------:|:---------:|
| n | 1117 | 159 | 389 | 129 |
| Mean @72 (bps) | -21.83 | +0.45 | -4.72 | +2.06 |
| Median @72 (bps) | -18.91 | +1.46 | -5.51 | +1.67 |
| Gross >30 rate | 9.0% | 22.0% | 18.0% | 24.8% |
| Gross >30 count | 101 | 35 | 70 | 32 |
| Gross >40 rate | 5.3% | 14.5% | 10.3% | 15.5% |
| Gross >40 count | 59 | 23 | 40 | 20 |
| Net+ rate | 16.8% | 29.6% | 28.3% | 32.6% |
| Spearman @8 bars | +0.4355 | -0.0101 | +0.1768 | -0.0115 |

### Per-Symbol Gross>30 Rate

| Symbol | G1-A | G1-B | G1-C | G1-D |
|:-------|:----:|:----:|:----:|:----:|
| BNB | 9.0% | 18.0% | 16.7% | 23.7% |
| BTC | 8.6% | 22.4% | 15.7% | 22.7% |
| ETH | 9.5% | 25.0% | 22.4% | 27.7% |

### Per-Side Gross>30 Rate

| Side | G1-A | G1-B | G1-C | G1-D |
|:-----|:----:|:----:|:----:|:----:|
| BUY | 22.2% | 27.3% | 23.5% | 27.3% |
| SELL | 8.8% | 21.6% | 17.7% | 24.6% |

## Discovery Gate Evaluation

```
PRIMARY DISCOVERY TARGET
  Gross>30 rate    >= 18%
  Gross>40 rate    >= 10%
  Mean gross @72   > -10 bps
  Event sample     >= 150
```

| Variant | Gross>30 | Gross>40 | Mean @72 | n | Gate |
|:--------|:--------:|:--------:|:--------:|--:|:----:|
| `G1A_EVENT_ONLY` | 9.0% | 5.3% | -21.83 | 1117 | ✗ FAIL |
| `G1B_COMPRESSION` | 22.0% | 14.5% | +0.45 | 159 | ✓ PASS |
| `G1C_OPPORTUNITY` | 18.0% | 10.3% | -4.72 | 389 | ✗ FAIL |
| `G1D_COMPRESSION_OPPORT` | 24.8% | 15.5% | +2.06 | 129 | ✗ FAIL |
