# 02 Collectors And Data Quality

Status: requires remediation.

## Inventory

Collector modules cover:

- Binance market data
- Alternative.me / Fear & Greed
- ETF flows / Parsebot / Farside provider layer
- FRED/Yahoo macro
- Reddit/social
- Deribit
- Blockchain.com / Blockchair / Glassnode / DefiLlama
- Whale Alert
- Google Trends
- Alternative data scheduler and quality monitor

## Positive Findings

- Many collectors are feature-flagged by environment variable.
- Alternative data has provider status fields and quality monitoring.
- Parsebot ETF code explicitly tries to avoid fake zero data on failure.
- Raw alternative snapshots are persisted under `data/raw_alternative`.

## Gaps

- Provider-by-provider fixture/replay tests were not executable in this environment.
- Some collectors have fallback-to-neutral or fallback-to-missing behavior that needs explicit classification.
- External provider rate-limit/schema-change behavior needs replay fixtures.
- Data availability timestamps (`observed_at`, `fetched_at`, `available_at`) are not uniformly guaranteed.

## Classification

`REQUIRES_REMEDIATION`

