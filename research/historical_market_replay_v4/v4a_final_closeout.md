# HMR-V4A Final Closeout Report

This report summarizes the status and rejections for the HMR-V4A Independent Information Source Audit phase.

## Summary Status

```text
HMR-V4A — Independent Information Source Audit

Funding                 REJECTED_FINAL
Reconstructed IV skew   REJECTED_FINAL
DVOL                    REJECT_NON_TRANSPORTABLE
Alternative.me          REJECTED
Stablecoin liquidity    REJECTED
DeFi TVL                REJECTED

Promotable sources      0
Directional sources     0
Magnitude sources       0
Regime sources          0

Cross-source modeling   BLOCKED
ML training             BLOCKED
Oracle combination      BLOCKED
Feature rescue          BLOCKED

CURRENT INFORMATION INVENTORY
= EXHAUSTED
```

## Details of Rejections

### 1. Binance Funding
- **Verdict**: `REJECTED_FINAL`
- **Rationale**: Signed directional information was insufficient to produce viable returns.

### 2. Reconstructed IV Skew
- **Verdict**: `REJECTED_FINAL`
- **Rationale**: Failed to demonstrate edge; proxy limitations.

### 3. Deribit DVOL
- **Verdict**: `REJECT_NON_TRANSPORTABLE`
- **Rationale**: Magnitude/timing relationship failed to transport out-of-distribution (OOD). Even as a regime conditioning tool, it failed the validation gate.

### 4. Alternative.me Fear & Greed
- **Verdict**: `REJECTED`
- **Rationale**: Level and delta features were non-transportable between periods (sign flips and hit-rate flips in validation periods).

### 5. Stablecoin Liquidity (DefiLlama)
- **Verdict**: `REJECTED`
- **Rationale**: Support collapse due to distribution drift (applying Period A boundaries left Periods B and C with empty buckets). Level features also showed heavy calendar trend confounding.

### 6. DeFi TVL (DefiLlama)
- **Verdict**: `REJECTED`
- **Rationale**: Absolute level had high calendar trend correlation. Change features exhibited severe non-transportability or sign inversions (e.g. `defi_tvl_change_30d` inverted signs between Discovery Period A and Validation Periods B/C).

---

## Action Plan

Since the current historical information inventory is exhausted with 0 promoted sources, we proceed directly to **HMR-V4B: Independent Information Acquisition Program** instead of modeling with failed features.
Our next task is to perform the PIT provenance and availability audit of the **Open Interest** derivatives positioning data.
