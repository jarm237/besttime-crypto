# Besttime-Crypto — Remediation Roadmap

## Thứ tự triển khai

```text
Phase 0 — Ổn định hệ thống
  ↓
Phase 1 — Hoàn thiện Execution Pipeline
  ↓
Phase 2 — Data & Alternative Data Quality
  ↓
Phase 3 — Model Governance & Continuous Learning
  ↓
Phase 4 — Infrastructure & Operational Resilience
  ↓
Phase 5 — Paper Trading Validation
  ↓
Phase 6 — Live Production Readiness
```

## Nguyên tắc

- P0 phải hoàn tất trước P1.
- Không chuyển phase nếu acceptance criteria chưa đạt.
- Không bật live trước khi Phase 5 kết luận GO.
- Mọi thay đổi model và execution phải có rollback.

## Cập Nhật Vận Hành Mới Nhất

| Ngày | Báo cáo | Trạng thái |
| --- | --- | --- |
| 2026-07-17 | `System_Status_Report_2026-07-17.md` | Documentation rollup; live trading blocked; Gate A/shadow evidence pending |
| 2026-07-17 | `System_Operational_Update_2026-07-17.md` | Trade provenance implemented; WLD operational correction applied; shadow evidence not started |
| 2026-08-13 | `../research/H13_validation_sample_density_and_design_research.md` | H10 closed immutable; H11/H12 blocked; H13.0 diagnostic-only validation-density lane opened |
| 2026-08-13 | `../../historical-h13-validation-density/reports/h13_0_validation_sample_density_diagnostic.md` | H13.0 diagnostic passed from release-local frozen H10 artifacts; root cause distribution is 6 symbol-subset, 1 regime-filter |
| 2026-08-13 | `../../historical-h13-validation-density/reports/h13_1_symbol_subset_density_and_generalization.md` | H13.1 passed; primary finding is mixed symbol-subset drift plus selectivity-density tradeoff |
| 2026-08-13 | `../../historical-h13-validation-density/reports/h13_2_symbol_stability_and_evidence_accumulation_design_opening_record.md` | H13.2 contract frozen; design research will compare symbol-stability semantics with evidence-accumulation horizons |
| 2026-08-13 | `../../historical-h13-validation-density/reports/h13_2_symbol_stability_and_evidence_accumulation_design.md` | H13.2 executed 9 frozen design cells; output is multi-factor design required |
| 2026-08-13 | `../../historical-h13-validation-density/reports/h13_3_multi_factor_validation_design_contract_freeze.md` | H13.3 froze multi-factor validation design space; policy search remains closed |
| 2026-08-13 | `../../historical-h13-validation-density/reports/h13_4_multi_factor_validation_design_execution.md` | H13.4 executed 5 frozen multi-factor design cells; output is multi-factor design adequate at studyability level, with MF2/MF4 tied by frozen hierarchy |
| 2026-08-13 | `../../historical-h13-validation-density/reports/h13_5_tied_design_membership_and_replay_input_freeze.md` | H13.5 preserved the MF2/MF4 tie and froze both membership schedules plus replay input before outcome access |
| 2026-08-13 | `../../historical-h13-validation-density/reports/h13_6_market_replay_v2_and_quality_gates.md` | H13.6 replayed 148 canonical paths once; MF2/MF4 both remain viable with mixed block-level quality |
| 2026-08-13 | `../../historical-h13-validation-density/reports/h13_7_final_validation_design_acceptance.md` | H13.7 closed H13 with both MF2/MF4 viable with limits; no robust single validation design selected |
| 2026-08-13 | `../../historical-h14-prospective-validation-design-discrimination/reports/h14_0_prospective_validation_design_discrimination_contract_freeze.md` | H14.0 froze prospective validation-design discrimination contract; no policy search or production change |
| 2026-08-13 | `../../historical-h14-prospective-validation-design-discrimination/reports/h14_1_prospective_shadow_stream_initialization.md` | H14.1 initialized prospective MF2/MF4 shadow streams from a frozen post-H14.0 boundary; no replay, policy search, or production change |

Trạng thái hiện tại:

```text
Trade provenance taxonomy: IMPLEMENTED
System paper vs user Telegram/UI/CLI distinction: IMPLEMENTED
WLD duplicate open correction: APPLIED
Gate A runtime evidence: PENDING
Shadow evidence window: NOT STARTED
Runtime calibration readiness: BLOCKED
Meta promotion readiness: BLOCKED
H10 policy research: CLOSED_IMMUTABLE
H11 robust-input lane: BLOCKED_NO_ROBUST_INPUT_CANDIDATE
H12 validated-policy lane: BLOCKED_NO_VALIDATED_POLICY_CANDIDATE
Next research lane: H13_VALIDATION_SAMPLE_DENSITY_AND_DESIGN_RESEARCH
H13.0 diagnostic: H13.0_VALIDATION_SAMPLE_DENSITY_DIAGNOSTIC
H13.0 diagnostic status: PASS
H13.0 primary finding: SAMPLE_INSUFFICIENCY_DOMINATED_BY_SYMBOL_SUBSET_TOO_NARROW
H13.1 opened: YES
H13.1 phase: H13.1_SYMBOL_SUBSET_DENSITY_AND_GENERALIZATION_RESEARCH
H13.1 status: PASS
H13.1 primary finding: MIXED_SYMBOL_SUBSET_DRIFT_AND_SELECTIVITY_DENSITY_TRADEOFF
H13.2 phase: H13.2_SYMBOL_STABILITY_AND_EVIDENCE_ACCUMULATION_DESIGN_RESEARCH
H13.2 status: PASS_WITH_LIMITS
H13.2 output: MULTI_FACTOR_DESIGN_REQUIRED
H13.2 design cells evaluated: 9
H13.3 status: PASS
H13.3 phase: H13.3_MULTI_FACTOR_VALIDATION_DESIGN_CONTRACT_FREEZE
H13.3 frozen design cells: 5
H13.3 design selection rules frozen: PASS
H13.4 status: PASS_WITH_LIMITS
H13.4 phase: H13.4_MULTI_FACTOR_VALIDATION_DESIGN_EXECUTION
H13.4 output: MULTI_FACTOR_DESIGN_ADEQUATE
H13.4 design cells evaluated: 5
H13.4 top studyability tier: MF2, MF4
H13.4 tie resolution: UNRESOLVED_BY_FROZEN_H13_3_HIERARCHY
H13.4 quality metrics used for selection: NO
H13.5 status: PASS
H13.5 phase: H13.5_TIED_DESIGN_MEMBERSHIP_AND_REPLAY_INPUT_FREEZE
H13.5 source top tier designs: MF2, MF4
H13.5 top tier tie preserved: YES
H13.5 post-hoc tie break: 0
H13.5 designs frozen: 2
H13.5 design blocks frozen: 6
H13.5 hypothetical decisions frozen: 296
H13.5 replay input rows: 296
H13.5 unique canonical execution paths: 148
H13.6 status: PASS_WITH_LIMITS
H13.6 phase: H13.6_MARKET_REPLAY_V2_AND_INDEPENDENT_QUALITY_GATES
H13.6 output: BOTH_DESIGNS_REMAIN_VIABLE
H13.6 unique replay keys: 148
H13.6 replay keys accounted for: 148
H13.6 design memberships: 296
H13.6 canonical outcomes: 148
H13.6 pseudo-replication guard: PASS
H13.6 MF2 quality gate: PASS_WITH_LIMITS
H13.6 MF4 quality gate: PASS_WITH_LIMITS
H13.6 MF2 quality stability: MIXED
H13.6 MF4 quality stability: MIXED
H13.6 post-hoc tie break: 0
H13 status: COMPLETED_IMMUTABLE
H13.7 status: PASS_WITH_LIMITS
H13.7 phase: H13.7_FINAL_VALIDATION_DESIGN_ACCEPTANCE
H13 output: BOTH_DESIGNS_REMAIN_VIABLE_WITH_LIMITS
MF2 validation design: VIABLE_WITH_LIMITS
MF4 validation design: VIABLE_WITH_LIMITS
Studyability acceptable: YES
Quality gate acceptable: YES
Quality generalization: NOT_ESTABLISHED
Robust validation design: NONE
Single validation design selected: NO
Next research lane: H14_PROSPECTIVE_VALIDATION_DESIGN_DISCRIMINATION
H14 status: OPEN
H14.0 status: PASS
H14.0 phase: H14.0_PROSPECTIVE_VALIDATION_DESIGN_DISCRIMINATION_CONTRACT_FREEZE
H14.0 prospective observation only: YES
H14.0 outcome access before decision freeze: FORBIDDEN
H14.0 MF2 semantics mutated: NO
H14.0 MF4 semantics mutated: NO
H14.0 active canary mutated: NO
H14.1 status: PASS
H14.1 phase: H14.1_PROSPECTIVE_SHADOW_STREAM_INITIALIZATION
H14.1 prospective start timestamp: 2026-08-13T08:50:07Z
H14.1 MF2 membership schedule frozen: PASS
H14.1 MF4 membership schedule frozen: PASS
H14.1 pre-boundary records accepted: 0
H14.1 canonical analysis shared by both designs: YES
H14.1 quality outcome accessed for selection: NO
H14.1 Market Replay V2 used: NO
H14.1 production change: BLOCKED
H14.1 next phase: H14.2_DECISION_DIVERGENCE_AND_DENSITY_ACCUMULATION
H13 historical quality outcome accessed: YES
H13.6 Market Replay V2 run: YES
Longer-window-only lane: NOT_JUSTIFIED
Selection objective redesign: NOT_JUSTIFIED
Policy search: CLOSED
Longer validation window research opened: NO
Production change: BLOCKED
Live trading: DISABLED
```
