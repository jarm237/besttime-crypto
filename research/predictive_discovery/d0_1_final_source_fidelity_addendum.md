# D0.1 Final Source Fidelity Reconciliation Addendum

This is the single bounded D0.1 economic replay authorized to close artifact consistency and execution/valuation timing. It does not open D0.2, R8-R11, D1, or neural production work.

- Previous economic scorecard: `sha256:53b96d457e71b456847d346545174f8f383467460b3e5f66c016bfd6c427a991`
- Canonical corrected economic scorecard: `sha256:9f2057e4d71824f87f2bc06cad6ee0ec23f86879ce0f61ef2bf1e6b8d1e12f0a`
- Source commit at generation: `84694945a6816cb37490275a2d1bcfe36da05ba8`
- Runner source: `sha256:775a451239995ca99ff565ebf3d327fab6eb9116303eda2ba68182aafa288b3c`

## Reconciliation Result

The previously committed scorecard and report were mutually consistent. The inconsistent +531.06% agent figure was not sourced from that committed scorecard. The corrected replay now makes the source explicit: every report carries the SHA-256 of the exact economic scorecard loaded to render it.

The economic input contract changed from pre-execution `btc_close[t]` valuation to the close of the bar beginning at execution time: `feature_close[t]` remains decision information, `execution_open[t]` executes the pending order, and `valuation_close[t]` marks the post-trade holdings one hour later.

| Policy | Full Return (previous → corrected) | Validation Return (previous → corrected) | Trades (previous → corrected) | Turnover (previous → corrected) |
| :--- | ---: | ---: | ---: | ---: |
| **BTC Buy & Hold** | `+251.40%` → **`+248.94%`** | `-5.44%` → **`-6.51%`** | `1` → **`1`** | `1.00x` → **`1.00x`** |
| **Static 50/50** | `+104.89%` → **`+104.17%`** | `-0.80%` → **`-1.36%`** | `1269` → **`1269`** | `5.95x` → **`5.95x`** |
| **R7 Weekly Adaptation** | `+134.89%` → **`+134.22%`** | `+3.69%` → **`+3.04%`** | `178` → **`178`** | `25.90x` → **`25.90x`** |
| **Derivatives-Informed Trend** | `+128.93%` → **`+128.93%`** | `+7.95%` → **`+7.95%`** | `198` → **`198`** | `114.11x` → **`114.11x`** |
| **Price-Only Trend Control** | `+168.68%` → **`+168.68%`** | `+5.02%` → **`+5.02%`** | `242` → **`242`** | `136.67x` → **`136.67x`** |

## Closure

Population counters are now computed from row-level counterfactuals, required PIT/accounting evidence fails closed when absent, and a feature-builder-to-simulator integration test covers the temporal price contract. The predictive conclusion remains evidence-derived; no new strategy search was performed.
