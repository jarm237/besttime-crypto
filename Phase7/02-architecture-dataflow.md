# Phase 7 — Architecture & Data Flow

Collectors (Alternative Data Layer)

- Base Interface: `collector_base.py`
- Concrete Collectors: Binance, DefiLlama, FRED, Yahoo Finance, Glassnode, Deribit, ETF, Reddit, Google Trends

Data flow summary:

Collectors -> Raw Store (`data/raw_alternative/`) -> `AlternativeDataCollector` -> Normalizer + Feature Builder -> `WorldState.alternative` -> `Causal Context Bridge` -> ML Models & Causal Decision Engine
