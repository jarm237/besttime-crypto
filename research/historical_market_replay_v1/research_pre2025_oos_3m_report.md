# Historical Market Replay V1 STRICT Smoke

Milestone: `HMR-V1.3 OOS EFFICACY SAMPLE`
Window: `2025-01-01T00:00:00+00:00` to `2025-03-31T23:45:00+00:00` (15m)
Coins: `BTC, ETH, BNB`

## Gates

| Gate | Status | Note |
| --- | --- | --- |
| NO_LOOKAHEAD | PASS | checked 25920 sanitized signals |
| REPLAY_PARITY_SANITY | PASS | market cycles `8640/8640`; production policy path `PASS` |
| PRODUCTION_POLICY_PATH_PARITY | PASS | `25920/25920` observations |
| MODEL_TEMPORAL_VALIDITY | PASS | cutoff `2024-11-30T21:00:00+00:00` |
| DETERMINISTIC_REPLAY | PASS | metrics/trade/decision summaries match across rerun |
| EXECUTION_ACCOUNTING | PASS | residual `3.637978807091713e-11` |

## Current Policy Metrics

| Metric | Value |
| --- | ---: |
| gross_pnl | -700.6866817854063 |
| fees | 994.9417030474837 |
| slippage_attribution | 407.926085946229 |
| spread_attribution | 198.98833367016184 |
| net_pnl | -1695.6283848328899 |
| ending_equity | 8304.371615167147 |
| win_rate | 0.14150943396226415 |
| avg_win | 2.58763490169002 |
| avg_loss | 6.637626210289161 |
| expectancy_per_trade | -5.3321647321789 |
| profit_factor | 0.06425990437547079 |
| max_drawdown | 0.1731023216507362 |
| n_trades | 318 |

## Activity

- cycles: `8640`
- signal cycles: `8640`
- predictions: `25920`
- decisions: `{'BUY': 0, 'SELL': 1039, 'HOLD': 24881}`
- execution eligible: `1039`
- trades opened/closed: `{'opened': 318, 'closed': 318, 'open_at_end': 0}`

## Decision Funnel

```json
{
  "canonical_policy_directional": 1130,
  "entry_risk_eligible": 1039,
  "feature_vectors": 25920,
  "final_actions": {
    "BUY": 0,
    "HOLD": 24881,
    "SELL": 1039
  },
  "inference_completed": 25920,
  "market_observations": 25920,
  "meta_threshold_passed": 25920,
  "posterior_directional": 1130,
  "signal_score_threshold_passed": 25920,
  "technical_directional": 1175
}
```

## Breakdowns

```json
{
  "by_coin": {
    "BNB": {
      "net_pnl": -524.316671320218,
      "trades": 99,
      "win_rate": 0.12121212121212122,
      "wins": 12
    },
    "BTC": {
      "net_pnl": -569.8761682282358,
      "trades": 110,
      "win_rate": 0.16363636363636364,
      "wins": 18
    },
    "ETH": {
      "net_pnl": -601.4355452844363,
      "trades": 109,
      "win_rate": 0.13761467889908258,
      "wins": 15
    }
  },
  "by_side": {
    "SHORT": {
      "net_pnl": -1695.6283848328892,
      "trades": 318,
      "win_rate": 0.14150943396226415,
      "wins": 45
    }
  },
  "monthly": {
    "2025-01": {
      "net_pnl": -651.7197127257947,
      "trades": 113,
      "win_rate": 0.09734513274336283,
      "wins": 11
    },
    "2025-02": {
      "net_pnl": -484.41476877191366,
      "trades": 93,
      "win_rate": 0.16129032258064516,
      "wins": 15
    },
    "2025-03": {
      "net_pnl": -540.5256481345621,
      "trades": 110,
      "win_rate": 0.17272727272727273,
      "wins": 19
    },
    "2025-04": {
      "net_pnl": -18.96825520061959,
      "trades": 2,
      "win_rate": 0.0,
      "wins": 0
    }
  },
  "regime": {
    "BREAKOUT_BEAR": {
      "net_pnl": -0.12993241480203643,
      "trades": 2,
      "win_rate": 0.5,
      "wins": 1
    },
    "BREAKOUT_BULL": {
      "net_pnl": -14.849008925864018,
      "trades": 3,
      "win_rate": 0.3333333333333333,
      "wins": 1
    },
    "COMPRESSION": {
      "net_pnl": -16.474788256227804,
      "trades": 3,
      "win_rate": 0.0,
      "wins": 0
    },
    "MEAN_REVERSION": {
      "net_pnl": -719.3746344875645,
      "trades": 123,
      "win_rate": 0.12195121951219512,
      "wins": 15
    },
    "RANGING": {
      "net_pnl": -884.1899085961674,
      "trades": 167,
      "win_rate": 0.1377245508982036,
      "wins": 23
    },
    "STRONG_TREND": {
      "net_pnl": -4.8987022302671335,
      "trades": 1,
      "win_rate": 0.0,
      "wins": 0
    },
    "STRONG_TREND_BEAR": {
      "net_pnl": -9.339984969765071,
      "trades": 1,
      "win_rate": 0.0,
      "wins": 0
    },
    "WEAK_TREND": {
      "net_pnl": -21.561076911964552,
      "trades": 5,
      "win_rate": 0.0,
      "wins": 0
    },
    "WEAK_TREND_BEAR": {
      "net_pnl": -27.17303483334719,
      "trades": 7,
      "win_rate": 0.14285714285714285,
      "wins": 1
    },
    "WEAK_TREND_BULL": {
      "net_pnl": 2.3626867930798463,
      "trades": 6,
      "win_rate": 0.6666666666666666,
      "wins": 4
    }
  }
}
```

## Status

This report is a COUNTERFACTUAL_OOS_EFFICACY_SAMPLE, not a strategy conclusion.
