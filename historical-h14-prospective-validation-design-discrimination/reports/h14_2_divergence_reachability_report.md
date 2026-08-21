# H14.2-G7 divergence reachability report

## Probe boundary

The replay uses only the 647 authoritative records' timestamp, symbol, and already-frozen `current_policy_action`, plus candidate membership sets. It does not join outcomes, future bars, PnL, win/loss, MFE, MAE, or profit factor.

Observed span: 6.0521 days. Shared-policy actionable observations: 8 (BTC 4, ETH 2, BNB 2). The current designs expose only four because BTC is excluded by both schedules.

MF4 remains frozen at `{ETHUSDT, BNBUSDT}`. The table exhaustively enumerates every non-empty MF2 subset in the current three-symbol universe.

| Candidate MF2 subset | Shared | MF2-only | MF4-only | Disagreement | Days to 400 actionable | Days to 350 disagreement | Days to 175 MF2-only | Days to 175 MF4-only |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | 0 | 4 | 4 | 8 | 302.6 | 264.8 | 264.8 | 264.8 |
| ETH | 2 | 0 | 2 | 2 | 605.2 | 1059.1 | UNBOUNDED | 529.6 |
| BNB | 2 | 0 | 2 | 2 | 605.2 | 1059.1 | UNBOUNDED | 529.6 |
| BTC, ETH | 2 | 4 | 2 | 6 | 302.6 | 353.0 | 264.8 | 529.6 |
| BTC, BNB | 2 | 4 | 2 | 6 | 302.6 | 353.0 | 264.8 | 529.6 |
| ETH, BNB | 4 | 0 | 0 | 0 | 605.2 | UNBOUNDED | UNBOUNDED | UNBOUNDED |
| BTC, ETH, BNB | 4 | 4 | 0 | 4 | 302.6 | 529.6 | 264.8 | UNBOUNDED |

Projection formula for a non-zero observed count `n`:

```text
projected_total_days(target) = target × 6.0520833333 / n
```

Zero rates map to `UNBOUNDED`. Projections are descriptive and do not alter G5.

## Upper-bound conclusion

The best mathematically balanced candidate is MF2 `{BTCUSDT}` versus fixed MF4 `{ETHUSDT, BNBUSDT}`. It is not selected and is not scientifically justified merely by balance. Even this upper-bound partition requires approximately 302.6 days for 400 actionable and 264.8 days for each 175-observation exclusive subgroup.

No membership candidate is `VOLUME_REACHABLE_WITHIN_HORIZON`. Random allocation cannot improve the shared-policy actionable upper bound. A policy divergence might change action volume, but it is outside the frozen membership-design estimand and lacks prospectively frozen candidates.

```text
STRUCTURAL_REACHABILITY          YES, conditional on membership divergence
VOLUME_REACHABILITY_60_DAYS      NO
G5_THRESHOLDS_MODIFIED           NO
TRANSITION_RECOMMENDED           NO
```

