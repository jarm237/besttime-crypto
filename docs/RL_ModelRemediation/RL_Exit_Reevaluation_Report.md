# RL Exit Re-evaluation and Promotion Decision

**Decision:** `shadow`, promotion blocked.

The canonical artifact is `logs/rl_models/production/rl_exit_ppo.zip` (SHA-256 `ae894e5835b0e145d3bffc164e5d29500bea245d225b70aeef437de06cb3a489`). It has metadata declaring `rl-exit-obs-v2`, 20 features and `promotion_blocked=true`.

Existing evaluation evidence (`logs/phase_4_rl_report.json`) does not meet the gate: PPO mean reward is -2.1499 and PnL 0.0643, while the rule baseline has reward -1.8638 and PnL 0.1577. The current artifact therefore cannot be promoted.

Implemented controls:

- `RL_EXIT_MODE=shadow` and `RL_EXIT_ALLOW_LIVE_ACTION=false` are the defaults.
- Runtime resolves the canonical path with metadata/hash validation, never the newest filename.
- The 20-value ordered observation contract rejects wrong length, NaN/Inf and non-normalized values.
- Raw RL recommendations are logged in shadow, while the effective action is HOLD; the guard permits live action only in explicitly enabled `active` mode.

Outstanding evidence before advisory/active promotion: real-only walk-forward test, 1,000+ episodes across three regimes, bootstrap comparison with rule baseline, and 30-day/500-decision shadow record.
