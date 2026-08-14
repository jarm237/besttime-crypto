# Historical Market Replay V1 STRICT Smoke

Milestone: `HMR-V1.1 PRODUCTION POLICY PARITY PASS`
Window: `2025-01-01T00:00:00+00:00` to `2025-01-07T23:45:00+00:00` (15m)
Coins: `BTC, ETH, BNB`

## Gates

| Gate | Status | Note |
| --- | --- | --- |
| NO_LOOKAHEAD | PASS | checked 2016 sanitized signals |
| REPLAY_PARITY_SANITY | PASS | market cycles `672/672`; production policy path `PASS` |
| PRODUCTION_POLICY_PATH_PARITY | PASS | `2016/2016` observations |
| MODEL_TEMPORAL_VALIDITY | FAIL | cutoff `None` |
| DETERMINISTIC_REPLAY | PASS | metrics/trade/decision summaries match across rerun |
| EXECUTION_ACCOUNTING | PASS | residual `1.8189894035458565e-12` |

## Current Policy Metrics

| Metric | Value |
| --- | ---: |
| gross_pnl | 0.897386940578599 |
| fees | 16.666217973196378 |
| slippage_attribution | 6.83314969388576 |
| spread_attribution | 3.3332438637523834 |
| net_pnl | -15.76883103261778 |
| ending_equity | 9984.231168967384 |
| win_rate | 0.2 |
| avg_win | 4.949430395739758 |
| avg_loss | 5.179565357089385 |
| expectancy_per_trade | -3.1537662065235565 |
| profit_factor | 0.2388921682861557 |
| max_drawdown | 0.006091140368866959 |
| n_trades | 5 |

## Activity

- cycles: `672`
- signal cycles: `672`
- predictions: `2016`
- decisions: `{'BUY': 0, 'SELL': 5, 'HOLD': 2011}`
- execution eligible: `5`
- trades opened/closed: `{'opened': 5, 'closed': 5, 'open_at_end': 0}`

## Decision Funnel

```json
{
  "canonical_policy_directional": 5,
  "entry_risk_eligible": 5,
  "feature_vectors": 2016,
  "final_actions": {
    "BUY": 0,
    "HOLD": 2011,
    "SELL": 5
  },
  "inference_completed": 2016,
  "market_observations": 2016,
  "meta_threshold_passed": 2016,
  "posterior_directional": 5,
  "signal_score_threshold_passed": 2016,
  "technical_directional": 80
}
```

## Breakdowns

```json
{
  "by_coin": {
    "BTC": {
      "net_pnl": -6.22651144619447,
      "trades": 3,
      "win_rate": 0.3333333333333333,
      "wins": 1
    },
    "ETH": {
      "net_pnl": -9.54231958642331,
      "trades": 2,
      "win_rate": 0.0,
      "wins": 0
    }
  },
  "by_side": {
    "SHORT": {
      "net_pnl": -15.76883103261778,
      "trades": 5,
      "win_rate": 0.2,
      "wins": 1
    }
  },
  "monthly": {
    "2025-01": {
      "net_pnl": -15.76883103261778,
      "trades": 5,
      "win_rate": 0.2,
      "wins": 1
    }
  },
  "regime": {
    "MEAN_REVERSION": {
      "net_pnl": -9.54231958642331,
      "trades": 2,
      "win_rate": 0.0,
      "wins": 0
    },
    "RANGING": {
      "net_pnl": -6.22651144619447,
      "trades": 3,
      "win_rate": 0.3333333333333333,
      "wins": 1
    }
  }
}
```

## Status

This report is SMOKE_DIAGNOSTIC_ONLY and NOT_EFFICACY_EVIDENCE until every gate passes.
