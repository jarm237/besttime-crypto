# 04 ML Training And Governance

Status: mixed; governance is paper-ready, training requires remediation.

## Positive Findings

- Training scripts exist for adaptive model, meta model v3, many-coin training, slippage model, RL exit, TimeGAN and calibration.
- Model registry, governed artifact loader, promotion gates, readiness gate, operational health, and shadow validation modules exist.
- Runtime evidence health can be used by registry checks.

## Gaps

- There are many training entry points; the canonical production training path must be documented.
- Dataset immutability and manifest/hash enforcement need review across all training scripts.
- `ML_MODEL_PROMOTION_OVERRIDE` is a privileged bypass and should be audited.
- Full metrics and holdout/calibration evidence were not regenerated in this pass.

## Classification

Training: `REQUIRES_REMEDIATION`

Governance: `PAPER_READY`

