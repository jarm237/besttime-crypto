# AHDV-W1.5/W1.6 Wave 1 Closeout

Wave 1 is closed. Do not continue provider investigation on the critical path.

## Final Wave 1 Classifications

| Source | Classification | Replay behavior |
| --- | --- | --- |
| `binance_funding` | `H1_HISTORICAL` | production fallback |
| `deribit_dvol` | `H2_AS_OF_RECONSTRUCTABLE` | only use candle/observation completed before `T` |
| `alternative_me` | `H1_HISTORICAL` | production fallback |
| `defillama_stablecoin` | `H1_HISTORICAL` | production fallback |
| `defillama_tvl` | `H1_HISTORICAL` | production fallback |
| `fred` | `UNCLASSIFIED / PROBE_BLOCKED_ENVIRONMENT` | production fallback |

## Deribit Replay Constraint

The `[low, high]` DVOL range contract is only for validating snapshot alignment.

Replay must not use high, low, or close from the candle containing `T` until that candle is complete. For `STRICT_V1`, `deribit_dvol` may only use an observation whose candle close is strictly available before the replay clock.

## Historical Market Replay V1

```text
R1 ReplayClock + historical OHLCV
↓
R2 exact production feature pipeline
↓
R3 fidelity-aware alternative provider
   H3/H4 → historical exact
   H2    → reconstructed
   H0/H1/blocked → production fallback
↓
R4 exact production decision path
↓
R5 historical execution + position + outcome
↓
R6 CURRENT_POLICY baseline
↓
R7 PnL / WinRate / PF / EV / MaxDD / trades
```

## Replay Profiles

`STRICT_V1`

```text
PIT-safe data
+ production fallback for H0/H1/blocked
+ reconstructed H2 only when observation completed before T
```

`RESEARCH_V1`

```text
STRICT_V1
+ historical H1/H2 data tagged NON_PIT_VERIFIED
```

Compare:

```text
Δ decisions
Δ trades
Δ win rate
Δ net PnL
Δ expectancy
Δ profit factor
Δ max drawdown
```

## Stop Rule

Do not open Wave 2 before the baseline profitability report of the current policy. If `STRICT_V1` and `RESEARCH_V1` are close, do not spend more critical-path time promoting alternative sources to H3/H4. If they diverge materially, return only to the source that caused material decision delta.

