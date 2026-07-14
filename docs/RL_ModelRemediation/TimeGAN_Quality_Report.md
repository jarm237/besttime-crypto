# TimeGAN Governance and Quality Report

TimeGAN checkpoints are present (`autoencoder.pt`, `supervisor.pt`, `adversarial.pt`) and remain training-only assets. They are not loaded by the live signal/exit path.

Usage rule enforced operationally: synthetic candles may augment RL training only; they cannot be used as production evaluation/test evidence. Promotion reports must separate real-only from mixed-data results.

Before the next synthetic generation, persist provenance with generator hash/version, source dataset ID, generated timestamp, sequence length, sample count and seed; then compare return, volatility, autocorrelation, tail, drawdown and regime distributions against real data.
