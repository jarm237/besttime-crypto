# HMR-V4B Research Contract & Acquisition Governance

This document defines the research rules, data quality constraints, and decision gates for the **HMR-V4B — New Information Acquisition** phase.

---

## 1. Governance & Hard Rules

We enforce a strict protocol to prevent data mining and post-hoc rationalization:

- **Source Integrity**: Only data classified as `MARKET_OBSERVED`, `EXTERNALLY_PUBLISHED`, or `RECONSTRUCTED_FROM_EXTERNAL_OBSERVATIONS` is eligible for source promotion.
- **Prohibited Sources**: `RECONSTRUCTED_FROM_ENDOGENOUS_PRICE` and `SYNTHETIC` classes are prohibited from promotion. Reconstructing positioning features (e.g. synthetic Open Interest or synthetic Liquidations) from spot prices is blocked.
- **Quantile Invariant**: Quantile edges must be fit strictly on Period A (Discovery) and applied to Period B/C (Validation) without refitting or post-hoc adjustments.
- **No Hypothesis Reversal**: The direction and orientation of a feature's effect must be frozen in Period A. Flipping the hypothesis direction or tuning thresholds in validation periods is strictly blocked.
- **Modeling Blockers**: ML model training and cross-source modeling are blocked until at least one information source is successfully promoted.

---

## 2. Acquisition Pipeline & Candidates

The target candidates are sequenced as follows:

| Stage | Candidate | Information Family | Priority | Status |
| --- | --- | --- | :---: | --- |
| **V4B-1** | Open Interest | Derivatives Positioning | P0 | `BLOCKED_PROVENANCE` |
| **V4B-2** | Perp Spot Premium | Perp-Spot Dislocation | P0 | `REJECTED_FINAL` |
| **V4B-3** | Real Liquidations | Forced Liquidation Flow | P0 | `REJECTED_FINAL` |
| **V4B-4** | Aggressive Trade Flow | Microstructure Flow | P1 | `REJECTED_FINAL` |
| **V4B-5** | Genuine Options Chain | Volatility Tail Pricing | P1 | `REJECTED_FINAL` |

---

## 3. Decision Gate Criteria for V4B-2 (Perp Premium)

To promote the Perpetual Spot Premium, the following gates must be passed:

- **P0 Market Source**: Genuinely sourced from exchange archive.
- **P1 Historical Depth**: 2023-01-01 to 2024-12-31 covered.
- **P2 Asset Coverage**: BTC and ETH are required; BNB is optional.
- **P3 Temporal Semantics**: Timestamps represent accurate availability time.
- **P4 PIT Usability**: No lookahead or future information is used.
- **P5 Data Quality**: Missingness $< 5\%$, duplicated rows $< 1\%$.
- **P6 No Synthetic Reconstruction**: Real premium index kline data is used.

If `P0-P6` pass, we authorize **V4B-2B (Premium Information Audit)**. Otherwise, the source is marked as `BLOCKED_PROVENANCE` and we pivot immediately to **V4B-3A (Liquidation Provenance)**.

---

## 4. Transition to HMR-V4C (Exogenous & Cross-Market Discovery)

Since all market microstructure candidates (V4B-1 to V4B-5) have failed either provenance or economic information gates, the market microstructure branch is closed. The pipeline transitions to `HMR-V4C` (Exogenous & Cross-Market Information Discovery):

| Stage | Candidate | Information Family | Priority | Status |
| --- | --- | --- | :---: | --- |
| **V4C-1** | Cross-Market Risk Regime | Macro Risk / Volatility | P0 | `REJECTED_FINAL` |
| **V4C-2** | Stablecoin Liquidity / Supply | Stablecoin Issuer Flows | P1 | `REJECTED_FINAL` |
| **V4C-3** | ETF / Institutional Flow | Institutional Activity | P1 | `INTEGRATION_PROMOTED` |
| **V4C-4** | Macro Event State | Macro Release Surprises | P1 | `DISCOVERY` |
| **V4C-5** | On-chain Exchange Flow | Blockchain Wallet Activity | P2 | `DISCOVERY` |
| **V4D-1** | ETF Volatility Integration | Sizing & Dynamic Widths | P0 | `INTEGRATION_PROMOTED` |

Every V4C candidate must pass a two-phase audit:
1. **Phase A (Provenance Audit)**: Assess availability, PIT safety, timezone, revision, and market-hours alignment semantics.
2. **Phase B (Information Audit)**: Verify directional, volatility, or risk-state information strength.

### Governance & Budget Gates
- **Discovery Budget**: Maximum of 4 independent source families (V4C-1 to V4C-4).
- **Discovery Completion**: After V4C-4, close the discovery phase regardless of results.
- **Verdict Action**:
  - If zero promoted sources: Trigger `FEATURE_DISCOVERY_HARD_STOP` and reassess strategy objectives.
  - If >=1 promoted source: Declare `DISCOVERY_PHASE_COMPLETE` and proceed to Information Integration Audit.

ML model training is now **UNBLOCKED** specifically for strategy integrations that incorporate the promoted ETF Volatility source (`ETF2_ex_gbtc_net_flow_usd`). For all other sources, ML and parameter optimization remain strictly blocked.


