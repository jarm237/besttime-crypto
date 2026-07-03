# Phase 7 — Alternative Data Layer Implementation Plan

> Project: `besttime-crypto` — AI Quant Trading Platform  
> Phase: **7 — Alternative Data Layer**  
> Strategy: **Free-first pipeline**  
> Updated: 2026-07-03  
> Important update: **Glassnode is removed from the default free pipeline** and is now treated as an optional paid adapter.

---

## 1. Objective

Build a free-first, production-ready alternative data platform that enriches the existing AI Quant system without depending on paid data providers.

The goal is to expand beyond OHLCV by adding:

- Funding rate.
- Open interest.
- Orderbook imbalance.
- Stablecoin supply.
- TVL / DeFi liquidity.
- Fear & Greed.
- Blockchain network activity.
- Whale / large transfer proxy where available.
- Macro context.
- ETF / options data where free APIs are usable.

---

## 2. Key Design Rule

Phase 7 must run without any paid API key.

```env
FREE_FIRST_MODE=true
```

Default behavior:

```text
System must not fail if paid providers are missing.
Paid collectors must return "skipped", not raise exceptions.
```

---

## 3. Glassnode Policy Update

Glassnode should no longer be listed as a required free data source.

It is now classified as:

```text
Optional paid adapter
```

Recommended config:

```env
ENABLE_GLASSNODE=false
GLASSNODE_API_KEY=
```

Collector behavior:

```python
import os

class GlassnodeCollector:
    def __init__(self):
        self.enabled = os.getenv("ENABLE_GLASSNODE", "false").lower() == "true"
        self.api_key = os.getenv("GLASSNODE_API_KEY")

    def fetch(self):
        if not self.enabled:
            return {
                "source": "glassnode",
                "status": "skipped",
                "reason": "disabled_free_plan_not_supported",
                "data": None,
            }

        if not self.api_key:
            return {
                "source": "glassnode",
                "status": "skipped",
                "reason": "missing_api_key",
                "data": None,
            }

        # Fetch paid data here
```

### Rule

```text
Do not block Phase 7 if Glassnode is unavailable.
Do not include Glassnode features in mandatory ML dataset schema.
Do not require GLASSNODE_API_KEY in .env.
```

---

## 4. Free-first Provider Classification

### Core Free Providers

```python
FREE_FIRST_PROVIDERS = [
    "binance",
    "defillama",
    "alternative_me",
    "blockchain_com",
    "blockchair",
    "yahoo_finance",
    "stooq",
    "fred",
    "deribit",
]
```

### Optional Paid Providers

```python
PAID_OPTIONAL_PROVIDERS = [
    "glassnode",
    "whale_alert",
    "cryptoquant",
    "coinmetrics_paid",
]
```

---

## 5. Updated Data Source Map

| Data Need | Default Free Source | Optional Paid Source | Status |
|---|---|---|---|
| OHLCV | Binance Spot/Futures | — | Required |
| Trades | Binance WebSocket | — | Required |
| Orderbook | Binance Depth Stream | — | Required |
| Funding Rate | Binance Futures, Bybit | — | Required |
| Open Interest | Binance Futures, Bybit | — | Required |
| Stablecoin Supply | DefiLlama Stablecoins | CoinMetrics paid | Required |
| TVL / DeFi Liquidity | DefiLlama | — | Required |
| Fear & Greed | Alternative.me | — | Required |
| Active Addresses | Blockchain.com, Blockchair proxy | Glassnode | Optional |
| Transaction Count | Blockchain.com, Blockchair | Glassnode | Optional |
| Hashrate | Blockchain.com | Glassnode | Optional |
| Difficulty | Blockchain.com | Glassnode | Optional |
| Exchange Flow | Not reliable free | Glassnode, CryptoQuant | Optional |
| Whale Flow | Blockchair proxy, optional Whale Alert key | Whale Alert paid | Optional |
| MVRV / NUPL / SOPR | Proxy only or skipped | Glassnode | Optional |
| Macro DXY/VIX | Yahoo Finance, Stooq | — | Required |
| US Yield / Fed Data | FRED | — | Required |
| Options IV | Deribit | — | Optional but free |
| ETF Flow | Free ETF sources if stable, otherwise manual/CSV | Paid ETF APIs | Optional |

---

## 6. Updated Architecture

```text
Collectors
  ├── BinanceCollector
  │     ├── OHLCV
  │     ├── Trades
  │     ├── Orderbook
  │     ├── Funding
  │     └── Open Interest
  │
  ├── DefiLlamaCollector
  │     ├── Stablecoin Supply
  │     ├── Chain TVL
  │     ├── Protocol TVL
  │     └── Bridge / DeFi Flow
  │
  ├── AlternativeMeCollector
  │     └── Fear & Greed
  │
  ├── BlockchainCollector
  │     ├── Hashrate
  │     ├── Difficulty
  │     ├── Transaction Count
  │     └── Active Address Proxy
  │
  ├── BlockchairCollector
  │     ├── Address / Transaction Data
  │     └── Large Transfer Proxy
  │
  ├── MacroCollector
  │     ├── Yahoo Finance / Stooq
  │     └── FRED
  │
  ├── DeribitCollector
  │     ├── Options IV
  │     ├── Options OI
  │     └── Skew
  │
  └── OptionalPaidCollectors
        ├── GlassnodeCollector disabled by default
        ├── WhaleAlertCollector disabled by default
        └── CryptoQuantCollector disabled by default

        ↓
Raw Store
        ↓
Normalizer
        ↓
Feature Builder
        ↓
WorldState.alternative
        ↓
Feature Store
        ↓
ML + Causal Engine
```

---

## 7. Collector Interface

All collectors must follow the same return contract.

```python
{
    "source": "defillama",
    "status": "success | skipped | error",
    "reason": None,
    "timestamp": "2026-07-03T00:00:00Z",
    "data": {},
    "metadata": {
        "is_free_source": True,
        "requires_api_key": False,
        "freshness_seconds": 300
    }
}
```

Paid disabled collector example:

```python
{
    "source": "glassnode",
    "status": "skipped",
    "reason": "disabled_free_plan_not_supported",
    "data": None
}
```

This prevents collector failures from breaking the entire pipeline.

---

## 8. Required Collectors

### 8.1. Binance Collector

Data:

```text
OHLCV
Trades
Orderbook
Funding Rate
Open Interest
Liquidations if available
```

Features:

```python
funding_rate
funding_zscore
open_interest
open_interest_delta
orderbook_imbalance
bid_ask_spread
micro_price
liquidity_wall_score
market_buy_sell_pressure
```

Priority: **Critical**

---

### 8.2. DefiLlama Collector

Data:

```text
Stablecoin supply
Chain stablecoin supply
TVL
Protocol TVL
Bridge volume
Fees / revenue where available
```

Features:

```python
stablecoin_supply_total
stablecoin_supply_change_1d
stablecoin_supply_change_7d
stablecoin_momentum
chain_tvl
chain_tvl_change_1d
defi_liquidity_score
bridge_flow_score
```

Priority: **Critical**

---

### 8.3. Alternative.me Collector

Data:

```text
Fear & Greed Index
```

Features:

```python
fear_greed_raw
fear_greed_score
fear_greed_zscore
fear_greed_regime
```

Priority: **Critical**

---

### 8.4. Blockchain.com Collector

Data:

```text
Hashrate
Difficulty
Transaction count
Mempool metrics if available
```

Features:

```python
btc_hashrate
btc_hashrate_change_7d
btc_difficulty
btc_tx_count
btc_network_activity_score
```

Priority: **High**

---

### 8.5. Blockchair Collector

Data:

```text
Transaction count
Large transaction proxy
Address / chain statistics
```

Features:

```python
large_tx_count
large_tx_volume_proxy
network_activity_proxy
whale_activity_proxy
```

Priority: **Medium**

Important:

```text
Blockchair parser must be hardened.
Never assume response shape.
Handle missing indexes and empty responses safely.
```

---

### 8.6. Macro Collector

Sources:

```text
Yahoo Finance
Stooq
FRED
```

Data:

```text
DXY
VIX
Gold
Oil
US10Y
Fed Funds Rate
CPI
Unemployment
```

Features:

```python
dxy
dxy_change_1d
vix
vix_change_1d
gold_change_1d
us10y
macro_risk_score
risk_on_score
```

Priority: **Critical**

---

### 8.7. Deribit Collector

Data:

```text
BTC Options IV
ETH Options IV
Open Interest
Skew
Term Structure
```

Features:

```python
btc_iv
eth_iv
iv_rank
iv_change_1d
options_skew
options_risk_score
```

Priority: **Medium / High**

---

## 9. Disabled-by-default Optional Paid Collectors

### 9.1. Glassnode Collector

```env
ENABLE_GLASSNODE=false
GLASSNODE_API_KEY=
```

Use only when paid access exists.

Potential data:

```text
MVRV
NUPL
SOPR
Exchange Balance
Exchange Net Position Change
Realized Price
Dormancy
```

Feature names should be optional:

```python
glassnode_mvrv
glassnode_sopr
glassnode_nupl
glassnode_exchange_netflow
```

Do not include these in mandatory model training.

---

### 9.2. Whale Alert Collector

```env
ENABLE_WHALE_ALERT=false
WHALE_ALERT_API_KEY=
```

If no key:

```python
{
    "source": "whale_alert",
    "status": "skipped",
    "reason": "missing_or_disabled_api_key"
}
```

---

### 9.3. CryptoQuant Collector

```env
ENABLE_CRYPTOQUANT=false
CRYPTOQUANT_API_KEY=
```

Optional only.

---

## 10. Free Replacement for Glassnode Metrics

| Original Glassnode-like Metric | Free Replacement | Implementation |
|---|---|---|
| Active addresses | Blockchain.com / Blockchair proxy | Use network stats |
| Transaction count | Blockchain.com / Blockchair | Direct metric |
| Hashrate | Blockchain.com | Direct metric |
| Difficulty | Blockchain.com | Direct metric |
| Exchange netflow | Skip or proxy | Use exchange wallet list only if reliable |
| Whale flow | Blockchair proxy | Large transaction threshold |
| MVRV | Skip in free phase | Optional proxy only |
| NUPL | Skip in free phase | Optional paid |
| SOPR | Skip in free phase | Optional paid |
| Stablecoin supply | DefiLlama | Direct metric |
| TVL | DefiLlama | Direct metric |

Rule:

```text
If a free proxy is unreliable, skip the feature rather than polluting the ML dataset.
```

---

## 11. Derived Feature Layer

The raw source is less important than the derived feature.

Recommended derived features:

```python
liquidity_pressure
funding_pressure
open_interest_pressure
stablecoin_momentum
defi_liquidity_score
macro_risk_score
risk_on_score
orderbook_imbalance_score
large_tx_proxy_score
options_risk_score
```

Example:

```python
risk_on_score = (
    0.25 * stablecoin_momentum
    + 0.20 * defi_liquidity_score
    + 0.20 * inverse_dxy_pressure
    + 0.15 * inverse_vix_pressure
    + 0.10 * funding_health_score
    + 0.10 * orderbook_support_score
)
```

---

## 12. Updated WorldState Layer

Add:

```python
from dataclasses import dataclass

@dataclass
class AlternativeLayer:
    stablecoin_supply_total: float | None = None
    stablecoin_momentum: float | None = None
    chain_tvl: float | None = None
    defi_liquidity_score: float | None = None
    orderbook_imbalance: float | None = None
    funding_pressure: float | None = None
    open_interest_pressure: float | None = None
    large_tx_proxy_score: float | None = None
    options_iv_rank: float | None = None
    options_skew: float | None = None
    macro_risk_score: float | None = None
    risk_on_score: float | None = None
```

WorldState:

```python
@dataclass
class WorldState:
    macro: MacroLayer
    liquidity: LiquidityLayer
    crypto: CryptoLayer
    sentiment: SentimentLayer
    risk: RiskLayer
    alternative: AlternativeLayer
```

---

## 13. Scheduler

Recommended frequency:

| Collector | Frequency |
|---|---:|
| Binance orderbook | 1s–5s |
| Binance OHLCV | 1m / 15m |
| Funding rate | 5m–15m |
| Open interest | 5m–15m |
| Alternative.me | 1h |
| DefiLlama stablecoins | 1h |
| DefiLlama TVL | 1h–4h |
| Blockchain.com | 15m–1h |
| Blockchair | 15m–1h |
| Macro Yahoo/Stooq | 15m–1h |
| FRED | 1d |
| Deribit options | 5m–30m |
| Glassnode optional | disabled by default |

---

## 14. Sprint Plan

## Sprint 1 — Free-first Foundation

### Tasks

- Add provider classification.
- Add `ENABLE_*` flags.
- Implement collector return contract.
- Create `BaseCollector`.
- Create `CollectorResult`.
- Add skip-safe behavior.

### Deliverables

```text
collectors/base.py
collectors/provider_config.py
collectors/result.py
.env.example updated
```

### Acceptance Criteria

- System runs with no paid API key.
- Disabled paid collectors return `status="skipped"`.
- No collector crash blocks the pipeline.

---

## Sprint 2 — Binance + Market Microstructure

### Tasks

- Implement Binance spot/futures collector.
- Add orderbook stream.
- Add funding and OI collector.
- Compute orderbook imbalance.
- Compute funding pressure.

### Deliverables

```text
binance_collector.py
orderbook_features.py
funding_features.py
```

### Acceptance Criteria

- Funding and OI are collected.
- Orderbook imbalance is generated.
- Features are stored with timestamp.

---

## Sprint 3 — DefiLlama + Stablecoin Liquidity

### Tasks

- Implement DefiLlama collector.
- Fetch stablecoin supply.
- Fetch TVL.
- Build stablecoin momentum features.
- Build DeFi liquidity score.

### Deliverables

```text
defillama_collector.py
stablecoin_features.py
defi_liquidity_features.py
```

### Acceptance Criteria

- Stablecoin supply data is available.
- TVL data is available.
- Derived features are point-in-time safe.

---

## Sprint 4 — Macro Collector

### Tasks

- Implement Yahoo Finance / Stooq adapter.
- Implement FRED adapter.
- Fetch DXY, VIX, Gold, US10Y.
- Build macro risk score.

### Deliverables

```text
macro_collector.py
macro_features.py
```

### Acceptance Criteria

- Macro data can be fetched without paid key.
- Fallback source works if Yahoo fails.
- Macro risk score is generated.

---

## Sprint 5 — Blockchain.com + Blockchair

### Tasks

- Implement Blockchain.com collector.
- Implement Blockchair collector.
- Harden parser against missing fields.
- Build network activity score.
- Build large transaction proxy.

### Deliverables

```text
blockchain_collector.py
blockchair_collector.py
network_activity_features.py
```

### Acceptance Criteria

- Parser never raises KeyError on malformed response.
- Missing data is marked as unavailable.
- Features are optional, not mandatory.

---

## Sprint 6 — Deribit Options

### Tasks

- Implement Deribit collector.
- Fetch BTC/ETH options data.
- Compute IV rank and skew.
- Build options risk score.

### Deliverables

```text
deribit_collector.py
options_features.py
```

### Acceptance Criteria

- BTC/ETH IV available.
- Options features are timestamped.
- Missing options data does not block signal generation.

---

## Sprint 7 — Optional Paid Adapters

### Tasks

- Implement disabled-by-default Glassnode adapter.
- Implement disabled-by-default Whale Alert adapter.
- Implement disabled-by-default CryptoQuant adapter.
- Add env flags and skip behavior.

### Deliverables

```text
glassnode_collector.py
whale_alert_collector.py
cryptoquant_collector.py
```

### Acceptance Criteria

- All paid collectors are disabled by default.
- No API key required.
- Paid collectors do not appear in required health checks.

---

## Sprint 8 — Feature Builder + WorldState Integration

### Tasks

- Normalize all Phase 7 features.
- Add AlternativeLayer.
- Update WorldState builder.
- Update FeatureSnapshot.
- Update ML dataset builder.
- Update dashboard.

### Deliverables

```text
alternative_layer.py
alternative_feature_builder.py
world_state.py updated
feature_snapshot.py updated
dashboard Alternative Data tab
```

### Acceptance Criteria

- Alternative features appear in WorldState.
- FeatureSnapshot includes alternative layer.
- ML dataset can include free-first alternative features.

---

## 15. Updated `.env.example`

```env
# Free-first mode
FREE_FIRST_MODE=true

# Core free providers
ENABLE_BINANCE=true
ENABLE_DEFILLAMA=true
ENABLE_ALTERNATIVE_ME=true
ENABLE_BLOCKCHAIN_COM=true
ENABLE_BLOCKCHAIR=true
ENABLE_YAHOO_FINANCE=true
ENABLE_STOOQ=true
ENABLE_FRED=true
ENABLE_DERIBIT=true

# Optional paid providers — disabled by default
ENABLE_GLASSNODE=false
GLASSNODE_API_KEY=

ENABLE_WHALE_ALERT=false
WHALE_ALERT_API_KEY=

ENABLE_CRYPTOQUANT=false
CRYPTOQUANT_API_KEY=
```

---

## 16. Success Criteria

| Metric | Target |
|---|---:|
| Pipeline runs without paid API keys | 100% |
| Required collector uptime | > 95% |
| Paid collector required for startup | 0 |
| Missing data crash | 0 |
| Blockchair parser KeyError | 0 |
| Feature freshness for market data | < 5 min |
| Feature freshness for macro/stablecoin | < 1–4h |
| Alternative features in WorldState | Yes |
| Alternative features in ML dataset | Yes |
| Glassnode default status | skipped |

---

## 17. Updated Definition of Done

Phase 7 is complete when:

- Glassnode is not required.
- System works in free-first mode.
- Binance, DefiLlama, Alternative.me, Blockchain.com, Blockchair, Yahoo/Stooq/FRED and Deribit are implemented or safely skippable.
- Paid collectors are disabled by default.
- Collector failures do not break the pipeline.
- AlternativeLayer is added to WorldState.
- Derived features are available for ML and Causal Context.
- Dashboard shows provider health and skipped/failed/success status.
- Feature Store contains timestamped alternative data.

---

## 18. Recommended First Code Change

Start with provider gating:

```python
FREE_FIRST_PROVIDERS = [
    "binance",
    "defillama",
    "alternative_me",
    "blockchain_com",
    "blockchair",
    "yahoo_finance",
    "stooq",
    "fred",
    "deribit",
]

PAID_OPTIONAL_PROVIDERS = [
    "glassnode",
    "whale_alert",
    "cryptoquant",
]
```

Then update `.env.example`:

```env
ENABLE_GLASSNODE=false
GLASSNODE_API_KEY=
```

This avoids repeating the current problem where a free-first pipeline fails because a paid API key is missing.
