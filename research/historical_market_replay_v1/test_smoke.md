# Historical Market Replay V1 STRICT Smoke

Milestone: `HMR-V1.3 OOS EFFICACY SAMPLE`
Window: `2025-01-01T00:00:00+00:00` to `2025-01-07T23:45:00+00:00` (15m)
Coins: `BTC, ETH, BNB`

## Gates

| Gate | Status | Note |
| --- | --- | --- |
| NO_LOOKAHEAD | PASS | checked 2016 sanitized signals |
| REPLAY_PARITY_SANITY | PASS | market cycles `672/672`; production policy path `PASS` |
| PRODUCTION_POLICY_PATH_PARITY | PASS | `2016/2016` observations |
| MODEL_TEMPORAL_VALIDITY | PASS | cutoff `2024-11-30T21:00:00+00:00` |
| DETERMINISTIC_REPLAY | PASS | metrics/trade/decision summaries match across rerun |
| EXECUTION_ACCOUNTING | PASS | residual `5.4569682106375694e-12` |

## Current Policy Metrics

| Metric | Value |
| --- | ---: |
| gross_pnl | -66.25251060315986 |
| fees | 79.71622852840247 |
| slippage_attribution | 32.68365228591544 |
| spread_attribution | 15.943244841260999 |
| net_pnl | -145.96873913156233 |
| ending_equity | 9854.031260868443 |
| win_rate | 0.125 |
| avg_win | 3.2031345685950434 |
| avg_loss | 7.40848299225464 |
| expectancy_per_trade | -6.082030797148429 |
| profit_factor | 0.061765769474645876 |
| max_drawdown | 0.018850735411090887 |
| n_trades | 24 |

## Activity

- cycles: `672`
- signal cycles: `672`
- predictions: `2016`
- decisions: `{'BUY': 0, 'SELL': 70, 'HOLD': 1946}`
- execution eligible: `70`
- trades opened/closed: `{'opened': 24, 'closed': 24, 'open_at_end': 0}`

## Decision Funnel

```json
{
  "canonical_policy_directional": 77,
  "entry_risk_eligible": 70,
  "feature_vectors": 2016,
  "final_actions": {
    "BUY": 0,
    "HOLD": 1946,
    "SELL": 70
  },
  "inference_completed": 2016,
  "market_observations": 2016,
  "meta_threshold_passed": 2016,
  "posterior_directional": 77,
  "signal_score_threshold_passed": 2016,
  "technical_directional": 80
}
```

## Breakdowns

```json
{
  "by_coin": {
    "BNB": {
      "net_pnl": -48.23441293053469,
      "trades": 7,
      "win_rate": 0.0,
      "wins": 0
    },
    "BTC": {
      "net_pnl": -33.48607915077644,
      "trades": 8,
      "win_rate": 0.25,
      "wins": 2
    },
    "ETH": {
      "net_pnl": -64.24824705025121,
      "trades": 9,
      "win_rate": 0.1111111111111111,
      "wins": 1
    }
  },
  "by_side": {
    "SHORT": {
      "net_pnl": -145.9687391315623,
      "trades": 24,
      "win_rate": 0.125,
      "wins": 3
    }
  },
  "monthly": {
    "2025-01": {
      "net_pnl": -145.9687391315623,
      "trades": 24,
      "win_rate": 0.125,
      "wins": 3
    }
  },
  "regime": {
    "MEAN_REVERSION": {
      "net_pnl": -70.89315385990218,
      "trades": 10,
      "win_rate": 0.1,
      "wins": 1
    },
    "RANGING": {
      "net_pnl": -75.07558527166013,
      "trades": 14,
      "win_rate": 0.14285714285714285,
      "wins": 2
    }
  }
}
```

## Status

This report is a COUNTERFACTUAL_OOS_EFFICACY_SAMPLE, not a strategy conclusion.
