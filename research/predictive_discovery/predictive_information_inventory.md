# Predictive Information & Historical Feature Source Inventory

Audit of all candidate feature families, point-in-time timestamps, and historical availability.

---

## 1. Candidate Feature Families & PIT Availability Matrix

| Feature Family | Historical Source | Cadence | PIT Timestamp Used | Train (2022-23) | Val (2024) | Holdout (2025-26) | First-Principles Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **OHLCV Market Returns** | Binance Spot Public API | 1h | `open_time + 1h` (closed bar) | 100% (17,520h) | 100% (8,784h) | 100% (16,435h) | Causal log return across 1h, 4h, 24h, 72h, 168h |
| **Realized Volatility** | High-Low & Hourly Returns | 1h | `open_time + 1h` | 100% | 100% | 100% | Rolling 24h & 168h std of 1h log returns |
| **Volume & Liquidity** | Spot volume | 1h | `open_time + 1h` | 100% | 100% | 100% | Surge ratio $v / \text{SMA}(v, 24)$ & $v / \text{SMA}(v, 168)$ |
| **Trend / Moving Averages** | Spot Closes | 1h | `open_time + 1h` | 100% | 100% | 100% | Distance to SMA24 & SMA168 |
| **Cross-Asset Breadth** | 8 Canonical Coins | 1h | `open_time + 1h` | 100% | 100% | 100% | Dispersion across 8 coins & % coins > SMA168 |
| **Market Regime Indicators** | BTC Trend & Realized Vol | 1h | `open_time + 1h` | 100% | 100% | 100% | BTC Trend Sign & Volatility Regime terciles |
| **Sentiment (Fear & Greed)** | Alternative.me normalized | Daily | `conservative_available_at_utc` | 100% | 100% | 100% | Forward-filled with conservative availability lag |
| **Macro Yield Curve** | US Treasury Normalized | Daily | `conservative_available_at_utc` | 100% | 100% | 100% | 10Y - 2Y Treasury Yield Spread forward-filled |
| **On-Chain Stablecoins** | DefiLlama Normalized | Daily | `available_at` | 100% | 100% | 100% | 7-day stablecoin circulating market cap delta |
| **Derivatives Funding Rates** | Binance USD-M Futures | 8h | Settlement timestamp | 50% (2023 only) | 100% | 0% (Ends 2024-12) | **EXCLUDED FROM FULL REPLAY**: Incomplete horizon |

---

## 2. Key Data Integrity Findings

1. **Derivatives Data Disqualification**: While `historical_funding_rates.parquet` exists, it covers only 2023-2024 and only 3 coins (BTC, ETH, BNB). Testing a strategy relying on funding rates across the full 2022-2026 horizon would require backfilling or synthetic imputation, violating the zero-fake-data constraint. Therefore, funding rate is flagged as unvalidated for the primary horizon.
2. **PIT Safety of Alternative Data**: Both `fear_and_greed_2018_2026.parquet` and `treasury_yields_1990_2026.parquet` contain explicit `conservative_available_at_utc` columns accounting for publication lag. They are safe to use for causal feature engineering.
3. **Core Market Universe**: The 8-coin spot universe has 42,739 clean hourly bars with zero survivor bias and exactly 1 calendar gap (`2023-03-24 13:00 UTC` market-wide outage) correctly handled by timestamp alignment.
