# HMR-V5-B0 Economic Cost Contract

This document defines the frozen economic cost scenarios to be applied during the **HMR-V5-B1 Path-Aware Exit Capture Audit**. 

To prevent post-hoc optimization and overfitting, these values are pre-registered and frozen prior to running any exit simulations.

---

## 1. Frozen Cost Scenarios

| Scenario | Fees (bps) | Spread (bps) | Slippage (bps) | Adverse Selection (bps) | Total Floor (bps) | Rationale / Source |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **`RESEARCH_IDEALIZED`** | 1.00 | 0.25 | 0.00 | 0.00 | **2.50** | VIP tier zero-slippage trading matching V5-A1 baseline assumptions. |
| **`MAKER_REALISTIC`** | 2.00 | 0.50 | 0.50 | 0.50 | **7.00** | Passive maker order placement incorporating toxic flow adverse selection. |
| **`TAKER_REALISTIC`** | 5.00 | 1.00 | 1.50 | 0.00 | **15.00** | Aggressive market order crossing matching typical retail taker conditions. |

---

## 2. Convention and Formulas

For all scenarios, the round-trip transaction costs are defined as:

$$\text{Cost Floor}_{\text{round-trip}} = 2 \times \text{Fees} + 2 \times \text{Spread} + 2 \times \text{Slippage} + 2 \times \text{Adverse Selection}$$

This cost floor is directly subtracted from gross trade expected value (Gross EV) to compute Net EV:

$$\text{Net EV} = \text{Gross EV} - \text{Cost Floor}_{\text{round-trip}}$$

---

## 3. Governance Rules
- **No Floor Re-tuning**: The above cost floors are locked. Re-adjusting or interpolating cost floors after exit audit results are analyzed is strictly prohibited.
- **Economic Viability Gate**: A strategy candidate exit family is considered viable if and only if it produces positive Net EV under `MAKER_REALISTIC` (7.0 bps). Under `TAKER_REALISTIC` (15.0 bps), positive Net EV is highly desired but not a blocker for architecture promotion.
