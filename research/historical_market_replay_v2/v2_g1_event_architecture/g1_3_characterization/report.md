# HMR-V2-G1.3: Whipsaw, Strength, and Context Characterization Report

Analyzed **1117 SMA50_BREAK candidates** over the period **2024-12-27** to **2025-04-01**.

## 1. Whipsaw-Prone Diagnostic Classifier (G1.4)

Splitting candidates into `WHIPSAW_PRONE` (crossovers >= 2 in last 16 bars) versus `NON_WHIPSAW`:

| Regime | n | Mean Gross @72 (bps) | Gross >30bps Rate | Gross >40bps Rate | Net+ Rate |
|:-------|--:|---------------------:|------------------:|------------------:|----------:|
| WHIPSAW_PRONE | 1117 | -21.83 | 9.0% | 5.3% | 16.8% |

## 2. Whipsaw-Specific Economic Diagnosis Matrix (G1.7)

2D Matrix: Crossing frequency (Low/High) x SMA50 Slope Magnitude (Weak/Strong):

| Matrix Group | n | Mean Gross @72 (bps) | Gross >30bps Rate | Gross >40bps Rate | Net+ Rate |
|:-------------|--:|---------------------:|------------------:|------------------:|----------:|
| HighCross_StrongSlope | 559 | -21.56 | 9.3% | 4.8% | 16.5% |
| HighCross_WeakSlope | 558 | -22.10 | 8.8% | 5.7% | 17.2% |

## 3. Quintile Sweeps Spread Analysis

### Feature: `recent_cross_count_16bars`
| Quintile | Range | n | Mean Gross @72 (bps) | Gross >30bps Rate | Gross >40bps Rate | Net+ Rate |
|:--------:|:------|--:|---------------------:|------------------:|------------------:|----------:|
| 1 | `2.0000` to `6.0000` | 223 | -20.18 | 10.8% | 6.3% | 18.4% |
| 2 | `6.0000` to `8.0000` | 223 | -22.36 | 6.7% | 4.9% | 15.2% |
| 3 | `8.0000` to `9.0000` | 223 | -18.25 | 10.3% | 6.3% | 17.9% |
| 4 | `9.0000` to `10.0000` | 223 | -22.78 | 9.0% | 4.5% | 17.5% |
| 5 | `10.0000` to `14.0000` | 225 | -25.57 | 8.4% | 4.4% | 15.1% |

### Feature: `break_distance_atr`
| Quintile | Range | n | Mean Gross @72 (bps) | Gross >30bps Rate | Gross >40bps Rate | Net+ Rate |
|:--------:|:------|--:|---------------------:|------------------:|------------------:|----------:|
| 1 | `0.0003` to `0.2013` | 223 | -0.04 | 21.5% | 14.3% | 32.7% |
| 2 | `0.2028` to `0.3597` | 223 | -11.07 | 13.5% | 6.7% | 24.2% |
| 3 | `0.3601` to `0.5387` | 223 | -22.64 | 7.2% | 3.1% | 13.5% |
| 4 | `0.5391` to `0.7763` | 223 | -29.25 | 3.1% | 2.2% | 11.2% |
| 5 | `0.7766` to `1.7655` | 225 | -45.96 | 0.0% | 0.0% | 2.7% |

### Feature: `candle_body_atr`
| Quintile | Range | n | Mean Gross @72 (bps) | Gross >30bps Rate | Gross >40bps Rate | Net+ Rate |
|:--------:|:------|--:|---------------------:|------------------:|------------------:|----------:|
| 1 | `0.0002` to `0.1456` | 223 | -0.88 | 20.6% | 13.9% | 28.7% |
| 2 | `0.1467` to `0.2852` | 223 | -10.28 | 13.9% | 7.6% | 28.3% |
| 3 | `0.2854` to `0.4410` | 223 | -19.48 | 8.1% | 4.5% | 15.7% |
| 4 | `0.4414` to `0.6804` | 223 | -27.97 | 2.7% | 0.4% | 9.0% |
| 5 | `0.6824` to `1.4300` | 225 | -50.29 | 0.0% | 0.0% | 2.7% |

### Feature: `volume_ratio`
| Quintile | Range | n | Mean Gross @72 (bps) | Gross >30bps Rate | Gross >40bps Rate | Net+ Rate |
|:--------:|:------|--:|---------------------:|------------------:|------------------:|----------:|
| 1 | `0.0039` to `0.4209` | 223 | -22.96 | 10.8% | 6.7% | 18.8% |
| 2 | `0.4246` to `0.8264` | 223 | -22.78 | 5.8% | 3.6% | 12.6% |
| 3 | `0.8269` to `1.1787` | 223 | -21.18 | 10.3% | 7.6% | 17.5% |
| 4 | `1.1793` to `1.5432` | 223 | -22.79 | 9.0% | 4.5% | 15.7% |
| 5 | `1.5439` to `2.5351` | 225 | -19.47 | 9.3% | 4.0% | 19.6% |

### Feature: `sma50_slope`
| Quintile | Range | n | Mean Gross @72 (bps) | Gross >30bps Rate | Gross >40bps Rate | Net+ Rate |
|:--------:|:------|--:|---------------------:|------------------:|------------------:|----------:|
| 1 | `-0.0045` to `-0.0020` | 223 | -24.02 | 8.1% | 4.0% | 15.2% |
| 2 | `-0.0020` to `-0.0014` | 223 | -20.04 | 9.4% | 5.8% | 17.0% |
| 3 | `-0.0014` to `-0.0009` | 223 | -23.58 | 7.6% | 3.1% | 15.7% |
| 4 | `-0.0009` to `-0.0004` | 223 | -25.24 | 6.3% | 4.5% | 12.6% |
| 5 | `-0.0004` to `0.0020` | 225 | -16.34 | 13.8% | 8.9% | 23.6% |

### Feature: `ema9_ema21_distance`
| Quintile | Range | n | Mean Gross @72 (bps) | Gross >30bps Rate | Gross >40bps Rate | Net+ Rate |
|:--------:|:------|--:|---------------------:|------------------:|------------------:|----------:|
| 1 | `-15.7569` to `-6.6902` | 223 | -44.89 | 1.3% | 0.4% | 5.4% |
| 2 | `-6.6679` to `-4.9802` | 223 | -28.75 | 8.1% | 4.5% | 15.7% |
| 3 | `-4.9694` to `-3.7007` | 223 | -19.77 | 7.6% | 4.0% | 14.3% |
| 4 | `-3.7001` to `-2.4248` | 223 | -12.38 | 9.4% | 5.8% | 18.8% |
| 5 | `-2.4231` to `-0.0041` | 225 | -3.54 | 18.7% | 11.6% | 29.8% |

### Feature: `room_to_structure_bps`
| Quintile | Range | n | Mean Gross @72 (bps) | Gross >30bps Rate | Gross >40bps Rate | Net+ Rate |
|:--------:|:------|--:|---------------------:|------------------:|------------------:|----------:|
| 1 | `0.3846` to `23.4528` | 223 | -38.78 | 1.3% | 1.3% | 5.8% |
| 2 | `23.4957` to `37.1435` | 223 | -29.04 | 3.1% | 1.3% | 11.2% |
| 3 | `37.1695` to `48.5033` | 223 | -22.64 | 9.0% | 4.0% | 16.1% |
| 4 | `48.5517` to `63.4208` | 223 | -6.70 | 14.3% | 8.5% | 24.7% |
| 5 | `63.4695` to `135.9690` | 225 | -12.09 | 17.3% | 11.1% | 26.2% |


## 4. Transition Gate Verdict

* **SMA50_BREAK_CONTEXTUAL_EDGE Gate Status**: **PASS**  

  - **Winning Subgroup**: `Quintile 1 of feature break_distance_atr`  

  - **Result**: Pre-entry context successfully isolated a region that enriches `Gross > 30bps` rate above the 15% threshold with adequate sample size. **We retain the SMA50_BREAK trigger family and proceed to evaluate event confirmation filters**.
