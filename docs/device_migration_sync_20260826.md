# Device Migration Synchronization History

- **Date & Time:** 2026-08-26 14:30:10 (Local Time, UTC+7)
- **Purpose:** Synchronize all local work to remote (GitHub) to prepare for changing local devices.
- **Repository:** `besttime-crypto` (`git@github.com:jarm237/besttime-crypto.git`)

---

## 1. Branch Sync Details

| Local Branch | Target Remote Branch | Status | Commit / Tip | Notes |
| :--- | :--- | :--- | :--- | :--- |
| `main` | `origin/main` | Pushed | `dee7707` | Includes 1 commit ahead of origin (`dee7707` - define dedicated 22-symbol model coverage branch) |
| `model-coverage/22-symbol-v1` | `origin/model-coverage/22-symbol-v1` | Pushed | `fdbc402` | Includes 35 commits ahead of remote branch |
| `model-coverage/22-symbol-v1-dev` | `origin/model-coverage/22-symbol-v1-dev` | Created & Pushed | `d058351` | Created from detached HEAD (`1c7ab37`) and contains all uncommitted changes |

---

## 2. Saved Uncommitted Changes
The following modifications and new files were committed to the `model-coverage/22-symbol-v1-dev` branch (Commit `d058351`):

### Modified Files:
- `p7_attempt5_final_verdict.json`
- `p7_attempt5_final_verdict.json.sha256`
- `p7_attempt5_legacy_parity_report.json`
- `p7_attempt5_legacy_parity_report.json.sha256`
- `p7_attempt5_lineage_report.json`
- `p7_attempt5_lineage_report.json.sha256`
- `p7_attempt5_liveness_report.json`
- `p7_attempt5_liveness_report.json.sha256`
- `tests/ml/test_p7_attempt5_authorization.py`

### Newly Added (Untracked) Files:
- `btc_scraper/ml_engine/p8_economic_extractor.py`
- `p7_attempt5_final_activation_verdict.json`
- `p7_attempt5_final_activation_verdict.json.sha256`
- `p7_attempt5_release_identity_closure.json`
- `p7_attempt5_release_identity_closure.json.sha256`
- `p7_attempt5_resume_spawn_record_20260826T013814Z.json`
- `p7_attempt5_resume_spawn_record_20260826T013814Z.json.sha256`
- `p7_attempt5_runtime_composition_report.json`
- `p7_attempt5_runtime_composition_report.json.sha256`
- `p7_attempt5_runtime_identity_contract.json`
- `p7_attempt5_runtime_identity_contract.json.sha256`
- `p7_attempt5_schema_equivalence_report.json`
- `p7_attempt5_schema_equivalence_report.json.sha256`
- `p7_end_to_end_lineage_closure.json`
- `p7_end_to_end_lineage_closure.json.sha256`
- `p7_evidence_integrity_report.json`
- `p7_evidence_integrity_report.json.sha256`
- `p7_final_seal_readiness.json`
- `p7_final_seal_readiness.json.sha256`
- `p7_final_verdict.json`
- `p7_final_verdict.json.sha256`
- `p7_first_actionable_decision_report.json`
- `p7_first_actionable_decision_report.json.sha256`
- `p7_first_execution_attempt_report.json`
- `p7_first_execution_attempt_report.json.sha256`
- `p7_first_fill_report.json`
- `p7_first_fill_report.json.sha256`
- `p7_first_outcome_report.json`
- `p7_first_outcome_report.json.sha256`
- `p7_gitnexus_audit_report.json`
- `p7_gitnexus_audit_report.json.sha256`
- `p7_incident_summary.json`
- `p7_incident_summary.json.sha256`
- `p7_long_run_stability_report.json`
- `p7_long_run_stability_report.json.sha256`
- `p7_o8_failure_allowlist.json`
- `p7_o8_failure_allowlist.json.sha256`
- `p7_postseal_observation_baseline.json`
- `p7_postseal_observation_baseline.json.sha256`
- `p7_postseal_verifier_remediation.json`
- `p7_postseal_verifier_remediation.json.sha256`
- `p7_prediction_evidence_report.json`
- `p7_prediction_evidence_report.json.sha256`
- `p7_release_immutability_report.json`
- `p7_release_immutability_report.json.sha256`
- `p7_sustained_health_report.json`
- `p7_sustained_health_report.json.sha256`
- `p7_v1r1_full_regression_report.json`
- `p7_v1r1_full_regression_report.json.sha256`
- `p8_economic_effectiveness_report.json`
- `p8_economic_effectiveness_report.md`
- `p8_economic_evaluation_contract.json`
- `p8_economic_observation_plan.md`
- `scripts/` (22 new scripts related to p7 activation and verification)
- `tests/` (21 new tests related to p7 and p8 verification)

---

## 3. Outstanding Local Stashes (Not Synchronized to Remote)
The following stashes are present only on the local machine and will need manual transition if needed:
- `stash@{0}: On main: codex-pre-sync-hidden-logs-2026-07-17`
- `stash@{1}: On main: codex-pre-sync-main-2026-07-17`
- `stash@{2}: On main: temp preserve current work before reapplying stash`
- `stash@{3}: On main: WIP before pulling main`

---

## 4. GitNexus Audit State
- **Refreshed GitNexus Index:** Completed successfully.
- **Change Detection:** Ran against the `main` branch:
  - 418 files changed, 1704 symbols affected.
  - Risk level: `critical` (due to candidate building, validation reporting, and ML evaluation changes).
  - Affected execution flows: 273 (including `Start_telegram_listener` and `Close_position`).
