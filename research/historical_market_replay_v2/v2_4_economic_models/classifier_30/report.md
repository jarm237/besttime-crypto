# HMR-V2.4.3: Baseline Economic Model — Walk-Forward Results

## 1. OOS Economic Summary (GradientBoosting — mean across folds)

| Architecture | Top 1% GrossEV | Top 5% GrossEV | Top 10% GrossEV | Top 20% GrossEV |
|:-------------|:--------------:|:--------------:|:---------------:|:---------------:|
| G1-B | -2.5 | -3.5 | -1.3 | -1.5 | -1.2 |
| G1-D | +1.2 | -0.5 | -1.7 | -3.1 | -2.3 |

## 2. OOS ROC-AUC (mean across folds)

| Architecture | LogisticRegression | GradientBoosting |
|:-------------|:------------------:|:----------------:|
| G1-B | 0.547 | 0.526 |
| G1-D | 0.545 | 0.517 |

## 3. Feature Ablation Summary (GradientBoosting Top 5% GrossEV, mean)

| Feature Group Removed | G1-B GrossEV | G1-D GrossEV |
|:----------------------|:------------:|:------------:|
| ALL | -1.3 | -1.7 |
| A MARKET CONTEXT | -0.6 | -2.3 |
| B EVENT GEOMETRY | -2.8 | -2.4 |
| C STRUCTURAL | -1.3 | -0.6 |
| D WHIPSAW CONTEXT | -2.6 | -2.6 |
| E LEGACY | -1.3 | -1.7 |
| F OPTIONAL MICRO | -1.1 | -3.2 |

## 4. Economic Gate Verdicts

* **G1-B** Top-5% mean GrossEV = -1.3 bps → `REJECT`
* **G1-D** Top-5% mean GrossEV = -1.7 bps → `REJECT`

> Success criterion: OOS gross EV in top-selected cohort >= 25 bps.
> NOT: AUC > threshold.
