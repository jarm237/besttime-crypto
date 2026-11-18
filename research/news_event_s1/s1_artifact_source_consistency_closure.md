# S1 Artifact/Source Consistency Closure

- **Status:** `CLOSED_EXPLORATORY`
- **Closure base:** `d532e393d2114467fd2720e21bed064854eecd70`

## Scope

This is an artifact/source consistency correction only. It does not rerun the S1 experiment, retrain a model, replay a strategy, crawl additional data, or authorize S1.1, S2, unified-neural integration, or production deployment.

## Corrections Applied

1. **Coverage split:** DeFiLlama contains 414 in-window Train events and 120 in-window Validation events. The 446 pre-2023 and 382 post-2025-10-31 records are explicitly excluded from those split totals.
2. **PIT audit unit:** The 796 checks are decision days with a non-empty 24h event window, checking the latest event on each day. They are not all event memberships. The corresponding counts are 1,097 memberships at 24h and 3,287 at 72h; 227 24h decision days contain multiple events.
3. **GDELT scope:** Source archives have 15-minute granularity, but collection sampled one archive every 2 hours in six bounded windows. GDELT was not used in predictive features or economic replay.
4. **Policy identity:** The misleading `R7_Weekly_Vol_Target` label is replaced by `S1_30D_VOL40_WEEKLY_SIGNAL_DAILY_REBALANCE`, describing the actual 30-day volatility estimate, 40% annualized target, weekly target update, and daily rebalancing. Canonical R7 parity is not established.
5. **Backward fill:** Economic replay no longer calls `.bfill()`. Verification of the evaluated matrix found zero rows changed by the prior `.bfill().ffill()` expression, so this source correction does not alter the recorded economic results.

## Numerical Results

The predictive and economic metrics in `canonical_s1_scorecard.json` are retained unchanged. In particular:

- 24h validation PR-AUC: price/vol `0.251999`, combined `0.226541`, delta `-0.025458`, permutation p-value `0.960396`, bootstrap 95% CI `[-0.067111, +0.002756]`.
- 72h validation PR-AUC: price/vol `0.089811`, combined `0.100151`, delta `+0.010339`, permutation p-value `0.297030`, bootstrap 95% CI `[-0.008563, +0.029606]`.
- Validation net return at 12 bps: price-only `+18.7995%`, combined `+10.4028%`; at 30 bps: price-only `+11.6313%`, combined `+4.0447%`.

## Final Scoped Verdict

- `S1_DEFILLAMA_HACK_PROXY_24H`: `NOT_SUPPORTED`
- `S1_DEFILLAMA_HACK_PROXY_72H`: `INCONCLUSIVE`
- `S1_HISTORICAL_PIT`: `PARTIAL`
- `S1_COVERAGE_SPLIT_COUNTS`: `CORRECTED_VERIFIED`
- `S1_INCREMENTAL_ECONOMIC_VALUE`: `NOT_SUPPORTED`
- `S1_GDELT_ECONOMIC_EVALUATION`: `NOT_PERFORMED`
- `S1_R7_CANONICAL_PARITY`: `FAILED`
- `S1_BACKFILL_ACTUAL_IMPACT`: `ZERO_EVALUATED_ROWS`
- `GENERAL_NEWS_INFORMATION_VALUE`: `NOT_ESTABLISHED`
- `UNIFIED_NEURAL_ALPHA`: `NOT_ESTABLISHED`
- `PRODUCTION_PROMOTION`: `NOT_AUTHORIZED`
