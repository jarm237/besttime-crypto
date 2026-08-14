# Historical Market Replay V1 STRICT Smoke

Milestone: `HMR-V1 SMOKE REMEDIATION`
Window: `2025-01-01T00:00:00+00:00` to `2025-01-07T23:45:00+00:00` (15m)
Coins: `BTC, ETH, BNB`

## Gates

| Gate | Status | Note |
| --- | --- | --- |
| NO_LOOKAHEAD | PASS | checked 55 sanitized signals |
| REPLAY_PARITY_SANITY | FAIL | market cycles `672/672`; production policy path `FAIL` |
| DETERMINISTIC_REPLAY | PASS | metrics/trade/decision summaries match across rerun |
| EXECUTION_ACCOUNTING | PASS | residual `3.637978807091713e-12` |

## Current Policy Metrics

| Metric | Value |
| --- | ---: |
| gross_pnl | -104.58831315215843 |
| fees | 149.45950264808835 |
| slippage_attribution | 51.129859466840344 |
| spread_attribution | 29.891899373742767 |
| net_pnl | -254.04781580024678 |
| ending_equity | 9745.952184199758 |
| win_rate | 0.022222222222222223 |
| avg_win | 0.31303884748278477 |
| avg_loss | 5.7809285147211265 |
| expectancy_per_trade | -5.645507017783261 |
| profit_factor | 0.0012306879842667604 |
| max_drawdown | 0.028504347170578374 |
| n_trades | 45 |

## Activity

- cycles: `672`
- signal cycles: `48`
- predictions: `55`
- decisions: `{'BUY': 10, 'SELL': 45, 'HOLD': 0}`
- execution eligible: `55`
- trades opened/closed: `{'opened': 45, 'closed': 45, 'open_at_end': 0}`

## Breakdowns

```json
{
  "by_coin": {
    "BNB": {
      "net_pnl": -55.88029640079357,
      "trades": 12,
      "win_rate": 0.0,
      "wins": 0
    },
    "BTC": {
      "net_pnl": -88.82867874413581,
      "trades": 15,
      "win_rate": 0.06666666666666667,
      "wins": 1
    },
    "ETH": {
      "net_pnl": -109.33884065531738,
      "trades": 18,
      "win_rate": 0.0,
      "wins": 0
    }
  },
  "by_side": {
    "LONG": {
      "net_pnl": -38.478192555842966,
      "trades": 8,
      "win_rate": 0.0,
      "wins": 0
    },
    "SHORT": {
      "net_pnl": -215.56962324440389,
      "trades": 37,
      "win_rate": 0.02702702702702703,
      "wins": 1
    }
  },
  "monthly": {
    "2025-01": {
      "net_pnl": -254.04781580024687,
      "trades": 45,
      "win_rate": 0.022222222222222223,
      "wins": 1
    }
  },
  "regime": {
    "Ranging": {
      "net_pnl": -254.04781580024687,
      "trades": 45,
      "win_rate": 0.022222222222222223,
      "wins": 1
    }
  }
}
```

## Status

This report is SMOKE_DIAGNOSTIC_ONLY and NOT_EFFICACY_EVIDENCE until every gate passes.
