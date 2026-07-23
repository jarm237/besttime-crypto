# ML Engine Blocker Register

Baseline tag: `ml-engine-pre-remediation-20260723` (`d75a87d`)

Automated live entry remains **BLOCKED** until every P0/P1 release gate and shadow-validation gate is explicitly signed off.

| issue_id | severity | affected_files | failure_mode | regression_test | owner | status | release_gate |
|---|---|---|---|---|---|---|---|
| MLE-001 | P0 | `decision_engine.py` | Context hard stop overwritten by posterior | `TestFinalRiskGate` | ML runtime | remediated, validation pending | A |
| MLE-002 | P0 | `decision_engine.py` | Provider path performs two inferences | `test_provider_path_does_not_reinfer` | ML runtime | remediated, validation pending | A |
| MLE-003 | P0 | `meta_model_v3.py` | Final holdout used for calibrator selection | metadata/split-lineage tests | ML training | remediated, evidence regeneration pending | B |
| MLE-004 | P0 | `meta_model_v3.py` | Bucket midpoint reported as prediction mean | calibration reference tests | ML training | remediated, evidence regeneration pending | B |
| MLE-005 | P0 | runtime model loaders | Artifact deserialized without registry/hash/schema checks | governed-loader rejection tests | ML governance | remediated, validation pending | C |
| MLE-006 | P1 | `rl_trading_env.py` | Trade-local state leaks across trades | RL isolation tests | RL | remediated, policy retrain required | D |
| MLE-007 | P1 | `rl_trading_env.py` | Time limit returns terminal state | Gymnasium semantics test | RL | remediated, policy retrain required | D |
| MLE-008 | P1 | `model_registry.py` | Concurrent read-modify-write loses updates | concurrency/CAS tests | ML governance | remediated, validation pending | E |
| MLE-009 | P1 | prediction evidence | Prediction and feature snapshot can orphan | SQLite atomicity tests | ML runtime | remediated, migration validation pending | E |
| MLE-010 | P1 | `runtime_calibration.py` | Hidden wall clock makes reports non-deterministic | fixed-clock boundary tests | ML calibration | remediated, validation pending | E |
| MLE-011 | P1 | runtime fallback paths | Silent failure hides degraded audit/governance | operational health tests | Observability | in progress | F |

No issue may be marked `closed` until its release gate, full regression suite, and required shadow evidence pass.
