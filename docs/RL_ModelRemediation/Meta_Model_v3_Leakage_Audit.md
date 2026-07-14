# Meta Model v3 Leakage Audit

**Executed:** 2026-07-14  
**Decision:** candidate remains blocked. This audit establishes reproducible checks; upstream observed-at provenance is still required for promotion.

## Dataset checks

- Dataset: `data\feature_store\training\ml_dataset_v3.parquet`; rows: 24,070; v3 features: 99.
- Raw-parquet columns missing before v3 derived preprocessing: 23 (coin_AEVO, coin_AR, coin_AVAX, coin_BNB, coin_BTC, coin_DOGE, coin_ENA, coin_ETH, coin_IOTA, coin_NEAR, coin_SOL, coin_SOPH, coin_TAO, coin_TRB, coin_TRUMP, coin_TRX, coin_WLD, coin_XLM, coin_XPL, coin_XRP, coin_ZEC, entry_hour, entry_dayofweek). These 23 expected coin/calendar fields are reconstructed by the v3 transform; they are not by themselves evidence of leakage.
- Outcome-adjacent configured feature names: 0 (none).
- Duplicate `(coin, entry_time)` records: 0.
- Availability manifest: [feature_availability_manifest.json](feature_availability_manifest.json). Every feature is conservatively marked pending upstream `observed_at` proof; this prevents a false clean bill of health.

## Purged chronological holdout

An ExtraTrees diagnostic model was trained on the first 85% ordered records; one decision interval was embargoed before the last 15% real chronological test partition. ROC-AUC: **0.8443**. This diagnostic is not comparable to the saved v3 ensemble and is not a promotion result.

The saved **exact v3 pipeline** was also evaluated with its recorded feature order on the same final 15% slice: ROC-AUC **0.8382**. This is an in-artifact holdout replay, not an independent leakage clearance: the dataset still lacks per-feature observed-at provenance.

## Remaining promotion blockers

1. Add per-feature observed-at/source timestamps and assert `observed_at <= entry_time`.
2. Run embargoed multi-window and per-symbol-group evaluations using the exact v3 pipeline.
3. Complete feature-group ablation and verify synthetic data exclusion.
4. Demonstrate runtime feature-schema parity and calibration on unseen outcomes.
