# HMR-V2.3R: Target-Aligned Pool Validation Report

This report profiles the filtered V2 candidate pool (n=60) against the original V1 pool (n=1175) 
at the target economic horizons established in Phase V2.2.

## 1. Classification Targets Comparison (@72 bars)

| Metric | V1 Pool | V2 Pool | Delta | Notes |
|:-------|:-------:|:-------:|:-----:|:------|
| **Pool Size ($n$)** | `1175` | `60` | `-1115` | |
| **Mean Gross Return** | `-22.62 bps` | `-19.45 bps` | `+3.17 bps` | Aligned with GROSS target |
| **Median Gross Return** | `-19.15 bps` | `-13.23 bps` | `+5.92 bps` | |
| **Gross > 30bps Rate** | `8.9%` | `11.7%` | `+2.8%` | Target A2 enrichment |
| **Gross > 40bps Rate** | `5.1%` | `5.0%` | `-0.1%` | Target A1 enrichment |
| **Net+ Rate** | `16.4%` | `20.0%` | `+3.6%` | Target B1 enrichment |
| **Mean Positive Payoff** | `+23.19 bps` | `+21.41 bps` | `-1.78 bps` | |
| **Mean Negative Payoff** | `-41.44 bps` | `-41.46 bps` | `-0.02 bps` | |

## 2. Regression Target Comparison (@8 bars)

| Metric | V1 Pool | V2 Pool | Delta |
|:-------|:-------:|:-------:|:-----:|
| **Mean Gross Return** | `-23.57 bps` | `-21.63 bps` | `+1.94 bps` |
| **Median Gross Return** | `-21.35 bps` | `-16.50 bps` | `+4.86 bps` |
| **Spearman Correlation** | `+0.4227` | `+0.0732` | `-0.3496` |

## 3. Diagnosis and Validation Gates

### A. Economic Quality & Target Enrichment
* **Target Enrichment (>30bps @72bars)**: `1.32x` (from `8.9%` to `11.7%`)  
* **Target Enrichment (>40bps @72bars)**: `0.98x` (from `5.1%` to `5.0%`)  
* **Net+ Enrichment (@72bars)**: `1.22x` (from `16.4%` to `20.0%`)  

### B. Learnability & Sample Support

* **Total Candidates ($n$)**: `60`  

* **Gross > 30bps expected count**: `7`  

* **Gross > 40bps expected count**: `3`  

* **Sample Sufficiency Status**: **⚠️ BLOCKED (Sample Starvation)**  
  - Training a robust research classifier requires at least **30 positives** in the validation fold.  
  - The current V2 pool contains only `7` positives for `Gross>30` and `3` positives for `Gross>40`.
