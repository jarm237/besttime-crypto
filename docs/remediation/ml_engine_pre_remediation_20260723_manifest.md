# ML Engine Pre-remediation Evidence Manifest

- Source tag: `ml-engine-pre-remediation-20260723`
- Source commit: `d75a87da6cb834b94a6aa63555f7e52db44156fa`
- Captured: 2026-07-23
- Promotion posture: frozen; explicit override required
- Automated live entry: blocked

| Evidence | SHA-256 |
|---|---|
| `logs/model_registry.json` | `873b7267edf16a29b3e170cf279771172c41a6c5a097f7c8f241659a1f6a3dfc` |
| `logs/meta_model.json` | `bf7794ed9da75193ebfe8027c89f2636416b46a09572fa6c34200c543b80057f` |
| `logs/meta_model.joblib` | `4f7bc98a6c18d04d7853a180c4f68763298580128a206bf159f4d16c956cf1e1` |
| `logs/adaptive_model.metadata.json` | `91ff29cfc2b201cfa3bd8a1c2b6fdc5b6744eb6b6b4cce3ae4ba36168685ad32` |
| `logs/adaptive_model.joblib` | `5395280db76329ad16d79694ee2cc718fd47e22ce8c87ce18be8ac6449c5fbae` |
| `logs/rl_models/production/metadata.json` | `7bc0735eaf27d3ccc83a873d4c4bce3cfd3dbb35f681f4bd0e82c1745535de89` |
| `logs/rl_models/production/rl_exit_ppo.zip` | `ae894e5835b0e145d3bffc164e5d29500bea245d225b70aeef437de06cb3a489` |

The original evidence remains in place and is immutable by remediation code. Historical calibration reports are invalid for promotion until regenerated because they are affected by `INVALIDATED_HOLDOUT_SELECTION_LEAKAGE` and `INVALIDATED_CALIBRATION_BUCKET_BUG`.
