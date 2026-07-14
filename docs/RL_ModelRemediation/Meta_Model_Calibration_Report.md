# Meta Model Calibration and Drift Controls

The production v3.1 metadata records isotonic calibration. Middle buckets have low error, but tails are unsupported: 0.0-0.4 has 1,373 samples and +14.6 pp error; 0.8-1.0 has only 35 samples and -15.7 pp error.

Implemented runtime control: the raw prediction is retained and logged, while `sizing_probability` is clamped to `[0.40, 0.80]`. A versioned prediction envelope records artifact SHA, schema, feature hash, calibration method and latency.

`btc_scraper/ml_engine/drift_monitor.py` provides Brier, ECE, MCE, evidence-aware buckets (minimum 100 samples) and PSI. Operational thresholds remain: PSI >0.20 warning, >0.30 critical; ECE >0.10 critical; rolling AUC drop >0.05 requires investigation.

Rolling outcome monitoring requires post-trade outcome linkage, so it is not fabricated from prediction-only logs.
