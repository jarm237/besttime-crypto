# Worktree Disposition & Inventory Report (v2)

**Repository**: `besttime-crypto`
**Branch**: `model-coverage/22-symbol-v1-dev` (98 commits ahead of `main`, 0 behind)
**Commit**: `f96c6b8`
**Status**: 72 candidate files staged; 99 transient/scratch files remain intentionally untracked
**Mode**: `PLANNING_ONLY / CANDIDATE_STAGED_REVIEW` (No commit created, no source code mutated)

---

## 1. Tracked Content Changes (52 Files)

### A. Source, Scripts & Config (10 files) - `KEEP`
- `btc_scraper/core/db.py`
- `btc_scraper/core/runtime_ownership.py`
- `btc_scraper/ml_engine/inference_coordinator.py`
- `pytest.ini`
- `scripts/repair_evidence_epoch_lineage.py`
- `scripts/hmr_v4b_2b_premium_audit.py`
- `scripts/run_canary_until_seal_ready.py`
- `scripts/run_manual_runner.py`
- `scripts/runtime_migration_preflight.py`
- `scripts/test_sentiment_trend.py`

### B. Test Suite Files (31 files) - `KEEP`
1. `tests/ml/test_h14_integrity.py`
2. `tests/ml/test_model_coverage_mc8_manifest_worktree.py`
3. `tests/ml/test_model_coverage_mc9_authorization.py`
4. `tests/ml/test_model_coverage_mc9_release_identity.py`
5. `tests/ml/test_model_coverage_mc9_seal.py`
6. `tests/ml/test_non_evidence_inference_smoke.py`
7. `tests/ml/test_p7_a4_resume_contract.py`
8. `tests/ml/test_p7_r3a_supervised_child.py`
9. `tests/ml/test_p8_economic_evaluation.py`
10. `tests/ml/test_repair_evidence_epoch.py`
11. `tests/test_cross_market_audit.py`
12. `tests/test_cross_market_provenance_audit.py`
13. `tests/test_decision_engine.py`
14. `tests/test_etf_audit.py`
15. `tests/test_etf_integration_audit.py`
16. `tests/test_etf_provenance_audit.py`
17. `tests/test_liquidation_provenance_audit.py`
18. `tests/test_ml_models.py`
19. `tests/test_options_provenance_audit.py`
20. `tests/test_phase21_integration.py`
21. `tests/test_phase4_operational_resilience.py`
22. `tests/test_premium_audit.py`
23. `tests/test_runtime_migration_preflight.py`
24. `tests/test_runtime_ownership.py`
25. `tests/test_stablecoin_audit.py`
26. `tests/test_stablecoin_provenance_audit.py`
27. `tests/test_stage1_pipeline.py`
28. `tests/test_timegan_stage3.py`
29. `tests/test_trade_flow_audit.py`
30. `tests/test_trade_flow_provenance_audit.py`
31. `tests/test_validate_alternative_history.py`

### C. Restored Model & Data Binaries (9 files) - `RESTORED_TO_HEAD` (excluded from the 51 changed files)
- **3 PyTorch Models (`TEST_RUNTIME_POLLUTION`)**:
  - `supervisor.pt`
  - `adversarial.pt`
  - `autoencoder.pt`
- **6 Parquet Replay Data (`REGENERATED_BYTE_DRIFT_SEMANTICALLY_EQUAL`)**:
  - `research/historical_market_replay_v4/v4b_2b_premium_asset_stability.parquet`
  - `research/historical_market_replay_v4/v4b_2b_premium_conditional.parquet`
  - `research/historical_market_replay_v4/v4b_2b_premium_funding_redundancy.parquet`
  - `research/historical_market_replay_v4/v4b_2b_premium_monthly_stability.parquet`
  - `research/historical_market_replay_v4/v4b_2b_premium_quantiles.parquet`
  - `research/historical_market_replay_v4/v4b_2b_premium_tail_sensitivity.parquet`

### D. Research Manifests & Reports (11 files) - `KEEP`
- `research/historical_market_replay_v4/v4b_3a_liquidation_source_manifest.json`
- `research/historical_market_replay_v4/v4b_4a_trade_flow_source_manifest.json`
- `research/historical_market_replay_v4/v4b_4b_trade_flow_audit.json`
- `research/historical_market_replay_v4/v4b_4b_trade_flow_report.md`
- `research/historical_market_replay_v4/v4b_5a_options_provenance_audit.json`
- `research/historical_market_replay_v4/v4b_5a_options_source_manifest.json`
- `research/historical_market_replay_v4/v4c_1a_cross_market_source_manifest.json`
- `research/historical_market_replay_v4/v4c_2a_stablecoin_source_manifest.json`
- `research/historical_market_replay_v4/v4c_3a_etf_provenance_audit.json`
- `research/historical_market_replay_v4/v4c_3a_etf_source_manifest.json`
- `research/historical_market_replay_v4/v4c_3b_etf_audit.json`

---

## 2. EOL Cleanup Revalidated (0 Current EOL-Only Changes)
Các path dưới đây đã được xác minh content-equivalent với `HEAD` khi bỏ khác biệt EOL và đã phục hồi line endings gốc:
`research/historical_market_replay_v4/v4b_2b_premium_audit.json`, `v4b_2b_premium_report.md`, `v4b_3a_liquidation_coverage.json`, `v4b_3a_liquidation_provenance_audit.json`, `v4b_3a_liquidation_provenance_report.md`, `v4b_4a_trade_flow_coverage.json`, `v4b_4a_trade_flow_provenance_audit.json`, `v4b_4a_trade_flow_provenance_report.md`, `v4b_5a_options_coverage.json`, `v4b_5a_options_provenance_report.md`, `v4c_1a_cross_market_coverage.json`, `v4c_1a_cross_market_provenance_audit.json`, `v4c_1a_cross_market_provenance_report.md`, `v4c_1b_cross_market_audit.json`, `v4c_1b_cross_market_report.md`, `v4c_2a_stablecoin_coverage.json`, `v4c_2a_stablecoin_provenance_audit.json`, `v4c_2a_stablecoin_provenance_report.md`, `v4c_2b_stablecoin_audit.json`, `v4c_2b_stablecoin_report.md`, `v4c_3a_etf_coverage.json`, `v4c_3a_etf_provenance_report.md`, `v4c_3b_etf_report.md`, `v4d_1_etf_integration_audit.json`, `v4d_1_etf_integration_report.md`.

---

The Full regression rerun touched 23 of these paths again through EOL normalization. They were revalidated with `git diff --ignore-space-at-eol` and restored to `HEAD`. The test-created `btc_scraper/data/fallback_buffer.db` mutation was also restored to `HEAD`.

---

## 3. Untracked Files Inventory (99 Current Untracked Files)

### A. Shard Artifacts (76 Files) - `TRANSIENT_EXCLUDED`
- 38 XMLs (`full_regression_shard_*.xml`)
- 38 LOGs (`full_regression_shard_*.log`)

### B. Scratch Scripts (16 Files) - `SCRATCH_EXCLUDED`
- `scratch/fix_audit_tests.py`, `scratch/rebuild_p7_manifest.py`, `scratch/search_git_h14_commits.py`, `scratch/solve_exact_h14.py`, `scratch/solve_h14_5rows.py`, `scratch/solve_h14_complete.py`, `scratch/solve_h14_raw_full.py`, `scratch/solve_h14_streams.py`, `scratch/compute_hashes.py`, `scratch/verify_closure.py`, `scratch/inspect_git.py`, `scratch/verify_staged_matches_plan.py`, `scratch/verify_staged_blob_hashes.py`, v.v.

### C. Raw Streams (3 Files) - `QUARANTINE_NON_AUTHORITATIVE`
- `historical-h14-prospective-validation-design-discrimination/data/h14_1_prospective_analysis_stream.jsonl`
- `historical-h14-prospective-validation-design-discrimination/data/h14_1_prospective_design_decisions.jsonl`
- `historical-h14-prospective-validation-design-discrimination/data/h14_2_decision_divergence_accounting.jsonl`

### D. Stale / Excluded Evidence Checkpoints (4 Files) - `QUARANTINED / EXCLUDED`
- `evidence/next-step-20260922/candidate_seal_report.json` (`REJECTED_INTEGRITY_FAIL` - stale checkpoint)
- `evidence/next-step-20260922/manual_verification_full_plan_summary.json`
- `evidence/next-step-20260922/manual_verification_full_shard_24_of_32_summary.json`
- `evidence/next-step-20260922/full_tail_junit.xml`

*Tổng cộng untracked*: 76 + 16 + 3 + 4 = **99 files**.

> [!NOTE]
> Ngoài ra, `git status` ghi nhận 11 file research Markdown có trạng thái EOL/stat-only trong working tree nhưng nội dung ngữ nghĩa hoàn toàn trùng khớp với `HEAD`.

---

## 4. Artifact Disposition & Provenance Assessment — 9 Binaries & Inputs

### A. Execution Environment Context
- **Official Virtualenv Interpreter**: `D:\Workspaces\besttime-crypto\.venv\Scripts\python.exe`
- **Python**: `3.14.5`
- **Pandas**: `3.0.3`
- **PyArrow**: `25.0.0` (`.venv`) [Global: `24.0.0`]
- **PyTorch**: `2.12.0+cpu` (`.venv`) [Global: `2.12.1+cu126`]
- **Git Commit Baseline**: `f96c6b8` (`model-coverage/22-symbol-v1-dev`)

### B. Input Artifact Hashes (Premium Audit Lineage)
1. `research/historical_market_replay_v4/v4a_outcome_scaffold.parquet`:
   `6c47d09b7e607987883a179e6f0a63d3f57aab91171cc0b6ee601a40bc8ce8f9`
2. `research/historical_market_replay_v4/v4b_2b_premium_history.parquet`:
   `a9aa00675254fc437031c1fa714e342948381cd9c9364013fdf3f9b382d25071`
3. `data/historical_funding_rates.parquet`:
   `1fcdd6a53a6c40b5de05d84200c33aa074f17be03ff1d967d1b7cb9c0f02383c`

### C. 9 Binary Artifacts Lineage & Hash Comparison

| Binary File | Classification | Pre-cleanup Worktree SHA-256 (64 chars) | HEAD SHA-256 (64 chars) | Root Cause & Action Plan |
|---|---|---|---|---|
| `supervisor.pt` | `TEST_RUNTIME_POLLUTION` | `1aef1a1c39804713b784f7c214f70762c8a4822539cc8d5e38f67df84b826001` | `e643caeac24a7f500c5a775715f16f9ec4a42e03174e4c02d41279fd64e2a132` | `test_full_pipeline_device_detection` từng ghi vào repo root. Đã phục hồi `HEAD`; test hiện dùng thư mục tạm. |
| `adversarial.pt` | `TEST_RUNTIME_POLLUTION` | `ca6dd594260d73b6c35a1f244bc8b59d0e68b2c348db793585507eab655977f7` | `5ac3bc388766fa4843b08e853dc43c1ef6a390386b403f2a500a38d4ce06ffdd` | Tương tự trên. |
| `autoencoder.pt` | `TEST_RUNTIME_POLLUTION` | `368fc852576e7d8d77242deb4c66e582fa8d0d5f3b1be7e49222ae87f4f8cb34` | `4e659ab82ff01370c67c153a43ffc33f9da5b7ead5f35ebbc3e821c549b53278` | Tương tự trên. |
| `v4b_2b_premium_asset_stability.parquet` | `REGENERATED_BYTE_DRIFT` | `eb745f17e5f5adbe08c6348b2cada1ad38dcc20b5cb2c75369c5b3bf893baa19` | `7d94a2833ee62cb7a740b5e80ac258e82ea6fb64e314a5ce44b429c3f1aeb645` | `test_determinism_invariant` từng ghi vào repo. Semantic `df.equals(HEAD) == True`; đã phục hồi `HEAD` và test hiện dùng `tmp_path`. |
| `v4b_2b_premium_conditional.parquet` | `REGENERATED_BYTE_DRIFT` | `57401bb3b834b1fd8a4c8807f74fb725e4f229a598aa87b06fe4be12b0bc391a` | `0dbfd910036e06587dc0d0aeced50caaabe377061250b6fcb2fa0177fcaa2245` | Tương tự trên. Semantic equal. |
| `v4b_2b_premium_funding_redundancy.parquet` | `REGENERATED_BYTE_DRIFT` | `6fb9eaa1f974ab6562f00fe6f558ceb4fa19feabdba312a501014b8e6f8b1583` | `94f0322bb2ae78979b39bc763b261674d1c6eee9a5d668572535cd31dd508ba9` | Tương tự trên. Semantic equal. |
| `v4b_2b_premium_monthly_stability.parquet` | `REGENERATED_BYTE_DRIFT` | `6453793d96c1b05daafa5ccae26d2924c6e6799a89a8f111627881af2e63a72a` | `66e239e2cd863f69b691b6c067572b6dcbb46994071aa9206fa1c869a8b93b05` | Tương tự trên. Semantic equal. |
| `v4b_2b_premium_quantiles.parquet` | `REGENERATED_BYTE_DRIFT` | `33cb43c523e608ac904f3c415f3d474e0d48fafd2eb1e01c820f3cfcc8bebf40` | `01e229204facb3337f9aee82587fb738c535ce95ce290d3c00d22e040b486660` | Tương tự trên. Semantic equal. |
| `v4b_2b_premium_tail_sensitivity.parquet` | `REGENERATED_BYTE_DRIFT` | `999b190a5068092156ac1eeeb33a6e0b965f524e212fbfdf7bdf4ee238f740ed` | `11616045a72a7d16343b29f7c633564be1a7f503bd7d5169bb321200c583a736` | Tương tự trên. Semantic equal. |

Sau cleanup, SHA-256 hiện tại của cả 9 artifact đều trùng cột `HEAD SHA-256`; không file nào còn xuất hiện trong `git status`.

---

## 5. Remediation Implementation Status — `FULL_PASS_VERIFY_PASS`

### A. Thay đổi đã triển khai
1. **PyTorch Checkpoint Test (`tests/test_timegan_stage3.py`)**:
   - `test_full_pipeline_device_detection` truyền `checkpoint_dir` là một `TemporaryDirectory` và xác nhận toàn bộ checkpoint nằm trong thư mục đó.
2. **Premium Audit Producer (`scripts/hmr_v4b_2b_premium_audit.py`)**:
   - `run_audit` nhận `output_dir` nhưng giữ nguyên canonical `OUT_DIR` làm mặc định production.
   - CLI nhận `--output-dir`; toàn bộ parquet, JSON và Markdown được ghi vào thư mục được chỉ định.
3. **Determinism Test (`tests/test_premium_audit.py`)**:
   - Chạy audit với `--output-dir=<tmp_path>`.
   - Kiểm tra semantic equality của sáu parquet với baseline và xác nhận hash canonical không thay đổi.

### B. GitNexus và Source Gate đã thực hiện
1. Đã chạy `context` và upstream `impact` cho `run_stage3_pipeline`, `test_full_pipeline_device_detection`, `run_audit` và `test_determinism_invariant`.
2. GitNexus báo `CRITICAL` cho test device-detection nhưng graph bị nhiễu/truncate; ba target còn lại trả `UNKNOWN` hoặc không resolve được exact UID.
3. Source text search xác nhận:
   - Chỉ `test_full_pipeline_device_detection` gọi `run_stage3_pipeline` mà không truyền `checkpoint_dir`.
   - Premium audit chỉ được kích hoạt bởi entry point của script và subprocess trong `test_premium_audit.py`.

### C. Verification
- Người dùng đã chạy targeted pytest trên `.venv`: `2 passed in 94.53s`.
- Cả 9 artifact đã được phục hồi về `HEAD` và xác minh lại bằng SHA-256.
- Cả 25 thay đổi EOL-only đã được phục hồi về `HEAD`; semantic content không thay đổi.
- `git diff --check` cho ba file remediation đã đạt exit code 0.
- Full regression collection passed with 2,069 tests from 246 files across 6 shards.
- Full regression aggregation passed with 0 failures, 0 errors, and 8 skipped tests.
- `Phase Verify` passed the Git whitespace, GitNexus refresh, and GitNexus change-detection gates.

---

## 6. Candidate Staging Selection

- **52 tracked content changes**: source, scripts, config, tests, and 11 research artifacts listed above (C1-C4).
- **20 governance & evidence assets**: execution plan, runner, canonical test evidence, status reports, runtime probe, branch delta disposition, GitNexus reviews, partition plan, and this disposition (C5).
- **Tổng số candidate files đã stage**: **72 files** (khớp chính xác 100% với phân vùng C1-C5).
- **99 files intentionally excluded/untracked**: 76 shard logs/XML, 4 stale checkpoints, 16 scratch scripts, và 3 quarantined raw streams.
- Evidence hashes và exclusions được cố định trong `candidate_verification_manifest.json`.
