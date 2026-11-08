# Báo cáo Đánh giá Thay đổi & Critical Boundaries (GitNexus Change Review)

<!-- METADATA
{
  "source_commit": "f96c6b8b64516dd76d3af132dac316c5672e35be",
  "source_commit_tree": "da720a407ea580e5c67cc8f0035f8322d5f19586",
  "pre_g5_reconciliation_index_tree": "f992221b8ac2d9ec48c06bf1f3c84d33072ad47d",
  "observed_pre_reconciliation_tree": "f745fb75d02ecfd71aef0ae64613f4af8038620a",
  "observed_at_utc": "2026-10-12T01:00:42.5928305Z",
  "generated_at_utc": "2026-10-13T01:10:00Z",
  "generator": {
    "name": "g5-evidence-reconciliation",
    "version": "2.4",
    "mode": "manual-governed"
  },
  "input_hashes": {
    "gitnexus_critical_review": "5044ce93beada1ed63f8b7745ac57a55423e146171b27b6049b60a05abf93a33",
    "execution_plan": "5897aefbc6a0a7228c659b901879d1bc0355855a647581fd63d811ed065c5b9c"
  }
}
-->

**Repository**: `besttime-crypto`
**Nhánh**: `model-coverage/22-symbol-v1-dev`
**Commit nền**: `f96c6b8b64516dd76d3af132dac316c5672e35be`
**Ngày lập**: 2026-10-13T01:10:00Z
**Trạng thái Gate G5**: `REVIEW / FAIL-CLOSED`
**Trạng thái Gate G6**: `BLOCKED` (Do Stop Condition #4: `truncated: true` trên phạm vi so sánh nhánh)
**Phạm vi**: Đánh giá 215 changed symbols, 95 candidate execution flows, và truy vết đầy đủ 9 chặng critical lineage.

---

## 1. Phân loại 215 Changed Symbols

Toàn bộ 215 symbols được phát hiện thay đổi trong worktree candidate (72 files C1–C5) đã được bóc tách và phân loại thành 5 nhóm:

| Phân nhóm | Số lượng | Bản chất thay đổi | Đánh giá Rủi ro |
|---|---:|---|---|
| **Production / Runtime Core** | **5** | Sửa `InferenceCoordinator.predict_once`, `CircuitBreakerCollection`, PID probes | `CRITICAL` / `MEDIUM` (Cần kiểm soát chặt) |
| **Scripts & Preflight Runners** | **18** | `runtime_migration_preflight`, `repair_evidence_epoch_lineage`, canary scripts | `LOW` |
| **Unit & Integration Tests** | **78** | Test assertions cho MC8/MC9, P7/P8, timeout & isolation | `NEGLIGIBLE` (Bảo vệ contract) |
| **Research Manifests & Audits** | **22** | JSON manifests/audits cho Liquidation, ETF, Cross-market, Stablecoin | `LOW` (Research only) |
| **Docs & Governance Evidence** | **92** | Các heading / sections trong `NEXT_STEP_EXECUTION_PLAN`, reports, và governance evidence | `NONE` (Documentation & Evidence) |
| **Tổng cộng** | **215** | Khớp chính xác với báo cáo `node .gitnexus/run.cjs detect-changes --scope all` | `CRITICAL` |

---

## 2. Đánh giá Rủi ro & Direct Callers của Production Symbols (Từ GitNexus JSON)

Dữ liệu dưới đây được trích xuất trực tiếp từ [gitnexus_critical_review.json](file:///d:/Workspaces/besttime-crypto/evidence/next-step-20260922/gitnexus_critical_review.json):

### 🔹 1. `InferenceCoordinator.predict_once`
- **Exact UID**: `Method:btc_scraper/ml_engine/inference_coordinator.py:InferenceCoordinator.predict_once#5`
- **Rủi ro GitNexus**: **`CRITICAL`** (`riskSharedAxes: MEDIUM`).
- **Tổng số symbols ảnh hưởng**: **19 symbols** (raw GitNexus count từ index hiện tại `f96c6b8`).
- **Cảnh báo truncation**: Không phát hiện cảnh báo truncation trong kết quả exact impact query (`epistemic: exact`).
- **Số direct callers (Depth 1)**: **11 callers**, bao gồm:
  - `run_decomposition` (`scripts/hmr_v1_3a_decomposition.py`)
  - `run_ablation_scenario` (`scripts/hmr_v1_3b_ablations.py`)
  - `run_b0_diagnostics` (`scripts/hmr_v1_3b_b0_model_ranking.py`)
  - `run_c2_diagnostics` (`scripts/hmr_v1_3c_c2_economic_ranking.py`)
  - `run_economic_audit` (`scripts/hmr_v1_3d_d1_d2_economic_audit.py`)
  - `run_window_backtest` (`scripts/hmr_v1_3d_d5_validation_runner.py`)
  - `build_production_policy_signals` (`scripts/hmr_v1_baseline.py`)
  - `main` (`scripts/p7_r6_v1r1_runtime_preflight.py`)
  - `main` (`scripts/p7_a5_legacy_parity.py`)
  - `SignalGeneratorAgent.run` (`btc_scraper/ml_engine/multi_agent.py`)
  - `AutoTrader.evaluate_and_trade` (`btc_scraper/trading/auto_trader.py`)
- **Số execution flows ảnh hưởng**: **12 flows** (bao gồm `Fetch_and_display → Partition_path`, `Fetch_and_display → Resolve`, v.v.).

### 🔹 2. `CircuitBreakerCollection`
- **Exact UID**: `Class:btc_scraper/core/db.py:CircuitBreakerCollection`
- **Rủi ro GitNexus**: **`MEDIUM`** (50 impacted symbols).
- **Mục đích**: Bảo vệ degraded-path khi kết nối MongoDB TLS bị timeout/gián đoạn.

### 🔹 3. `_pid_alive` & `_windows_pid_alive`
- **Exact UIDs**: `Function:btc_scraper/core/runtime_ownership.py:_pid_alive` và `_windows_pid_alive`
- **Rủi ro GitNexus**: **`LOW`** (7 và 5 impacted symbols).
- **Mục đích**: Triển khai Windows native process probe, loại bỏ hoàn toàn lệnh `os.kill(0)` nguy hiểm trên Windows.

---

## 3. Hoàn thiện Truy vết Critical Lineage (9 Chặng theo AGENTS.md & Phân định Graph vs UNKNOWN)

Theo quy định bắt buộc của [AGENTS.md](file:///d:/Workspaces/besttime-crypto/AGENTS.md), đường dây sinh mệnh (critical lineage) được đối chiếu chi tiết qua 9 chặng:

```text
[1] cycle
  → [2] feature snapshot
  → [3] prediction
  → [4] final decision
  → [5] order
  → [6] execution
  → [7] fill
  → [8] ledger
  → [9] reconciliation
```

### Chi tiết xác minh từng chặng và trạng thái biểu diễn đồ thị:

1. **Cycle** (`Method:btc_scraper/ml_engine/multi_agent.py:AgentOrchestrator.run_cycle#2`):
   - **Graph Edge**: `CALLS` -> `SignalGeneratorAgent.run` -> `InferenceCoordinator.predict_once`.
   - **Trạng thái**: `RESOLVED (Graph Verified)`.
2. **Feature Snapshot** (`btc_scraper/feature_store.py` & `world_state`):
   - **Graph Edge**: Dynamic dictionary lookup / DataFrame slicing.
   - **Trạng thái**: `UNKNOWN (Dynamic Graph / Source-Verified Fallback)` do edge không phân giải được tĩnh trong index.
3. **Prediction** (`Method:btc_scraper/ml_engine/inference_coordinator.py:InferenceCoordinator.predict_once#5`):
   - **Graph Edge**: 11 callers trực tiếp, 12 affected processes (xem mục 2 bên trên).
   - **Trạng thái**: `RESOLVED (Graph Verified)`.
4. **Final Decision** (`Method:btc_scraper/trading/auto_trader.py:AutoTrader.evaluate_and_trade#2` & `build_entry_decision`):
   - **Graph Edge**: `CALLS` edge từ `AutoTrader` gọi `predict_once` để tính toán Kelly sizing và Net EV.
   - **Trạng thái**: `RESOLVED (Graph Verified)`.
5. **Order Planning** (`btc_scraper/trading/execution_engine.py::ExecutionEngine.submit_paper`):
   - **Graph Edge**: Dynamic dispatch qua adapter interface.
   - **Trạng thái**: `UNKNOWN (Dynamic Graph / Source-Verified Fallback)`.
6. **Execution** (`btc_scraper/trading/exchange_adapter.py`):
   - **Graph Edge**: Giao tiếp qua adapter lớp trừu tượng; kill switch & circuit breaker.
   - **Trạng thái**: `UNKNOWN (Dynamic Graph / Source-Verified Fallback)`.
7. **Fill** (`FilledRecord` & `TradeTracker`):
   - **Graph Edge**: Object creation và persistence record.
   - **Trạng thái**: `UNKNOWN (Dynamic Graph / Source-Verified Fallback)`.
8. **Ledger (Ghi sổ)** (`PositionState` & `AccountEquity`):
   - **Graph Edge**: Cập nhật equity, double-debit guard. FTS keyword lookup trả rỗng do FTS degraded trên Windows.
   - **Trạng thái**: `UNKNOWN (Dynamic Graph / Source-Verified Fallback)`.
9. **Reconciliation (Đối soát Phục hồi)** (`tests/recovery/` & `runtime_ownership.py`):
   - **Graph Edge**: Test assertions và atomic state recovery.
   - **Trạng thái**: `UNKNOWN (Dynamic Graph / Source-Verified Fallback)`.

> [!IMPORTANT]
> Toàn bộ các chặng được gán nhãn `UNKNOWN` đều được xử lý nghiêm ngặt theo AGENTS.md: không được coi `UNKNOWN` là rủi ro thấp hoặc đã an toàn. Bộ 2.069 test hermetic cung cấp bằng chứng regression mạnh trong phạm vi suite đã thực thi; không loại bỏ rủi ro từ graph relationships chưa quan sát được.

---

## 4. Phân định Hai Phạm vi Kiểm soát & Kết luận Quản trị

1. **Candidate Worktree Delta (`--scope all`)**:
   - **Quy mô**: **72 candidate files** (bao gồm 20 files C5), **215 symbols, 95 execution flows**, mức rủi ro **`CRITICAL`**, `partial: false`, `truncated: false`.
   - **Mục tiêu**: Đóng gói các thay đổi của đợt remediation (MC8/MC9, P7/P8, timeout, DB fallback, evidence audit).
2. **Branch Delta vs Main (`--scope compare --base-ref main`)**:
   - **Quy mô**: **622 files / 2.239 symbols / 281 execution flows / CRITICAL / truncated: true**.
   - **Giảm thiểu (Mitigation)**: Sử dụng GitNexus 1.6.13-rc.103 (`@ladybugdb/core` 0.21.1) như một **version-correlated mitigation**. Hash của 1.000 symbols đầu tiên ổn định, nhưng full-set determinism chưa được chứng minh.
   - **Chi tiết**: Được lập thành tài liệu quản trị độc lập tại [branch_delta_governance_disposition.md](file:///d:/Workspaces/besttime-crypto/evidence/next-step-20260922/branch_delta_governance_disposition.md).
3. **Quyết định Quản trị**:
   - Theo **Stop Condition #4 (mục 8, dòng 522)**, do tồn tại `truncated: true` trên phạm vi so sánh branch:
     - **Gate G5**: Tiếp tục giữ ở **`REVIEW / FAIL-CLOSED`**.
     - **Gate G6**: Tiếp tục **`BLOCKED`**.
     - **WP7 / WP8**: **`FORBIDDEN`**.
