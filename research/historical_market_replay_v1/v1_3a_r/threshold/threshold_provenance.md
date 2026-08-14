# R7 — Threshold Provenance Audit

## Git Traceability

The thresholds `buy_threshold = 0.65` and `sell_threshold = 0.35` were traced in the repository history:

- `980e870 feat: implement comprehensive causal reasoning engine and supporting infrastructure for explainable market analysis.`
- `fa9669d Add comprehensive tests for ML models, portfolio management, and RL environments`

## Core Findings

1. **Origin Commit**: Commit `fa9669dd469612fee7629ea74028ab793b1b4f19` (Date: Sun Jun 28 17:05:56 2026) first introduced the `MetaDecisionEngine` class and hardcoded these default thresholds:
   ```python
   buy_threshold: float = 0.65,
   sell_threshold: float = 0.35,
   ```
2. **Tuning Provenance**: No other configuration files, environment variables, or dynamic tuning scripts override these thresholds. They act as static bounds across the entire execution funnel.
3. **Semantic Alignment**: The thresholds fit the probability contract: a `0.65` posterior represents a 65% probability of a trade winning. However, under isotonic calibration collapse, the maximum calibrated win probability is `16.67%`, making a `0.65` threshold structurally impossible to exceed for any BUY trade.

**Conclusion**: `THRESHOLD_SEMANTICS_MATCH` — The scale of 0.65/0.35 aligns with the probability contract, but is incompatible with the collapsed calibration output.

**Gate**: `THRESHOLD_PROVENANCE_AUDITED = PASS`
