# Phase 2 — Missing-data Standard

## Contract

- `None` means a value is unavailable and remains missing through collection, normalization, snapshots, and feature construction.
- `0.0` is retained only when a provider supplied a real numeric zero.
- Non-finite numeric values (`NaN`, `Infinity`) are converted to `None` before JSON is written.
- Imputation is prohibited in collectors and feature builders. It belongs exclusively to an ML pipeline fitted on training data.
- Each model-facing alternative feature has a sibling `<feature>__missing` indicator.

## Provenance

`btc_scraper.collectors.feature_source_registry` defines every critical feature's source, requiredness, confidence, permitted range, freshness budget and missing policy. Normalized payloads expose the registry and per-feature metadata:

```json
{
  "available": true,
  "status": "available",
  "source": "binance",
  "confidence": 0.9,
  "observed_at": "2026-07-11T...+00:00",
  "age_seconds": 4.2,
  "is_stale": false
}
```

## Operations

`CollectorHealthMonitor.health_snapshot()` provides the data-quality dashboard with `snapshot_count_24h`, freshness, required/optional health, and completeness. A missing optional source emits an optional-health condition without failing the collection cycle; a missing or stale required source causes required health to fail.

When a collector scheduler returns its last successful cache after failures, it returns `status: "stale"`, `source: "cache"`, `is_stale: true`, and a calculated `age_seconds`. Metadata therefore lowers confidence and never presents cached fallback as a fresh successful observation.
