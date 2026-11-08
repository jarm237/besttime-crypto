# Kế hoạch thực thi bước tiếp theo — besttime-crypto

**Ngày lập:** 2026-09-22

**Repository:** `besttime-crypto`

**Nhánh hiện tại:** `model-coverage/22-symbol-v1-dev`

**Commit nền:** `f96c6b8b64516dd76d3af132dac316c5672e35be`

**Phạm vi:** khôi phục tính tái lập của release, đóng các lỗ hổng integrity, đưa regression về sạch, đồng bộ bằng chứng trạng thái và chỉ sau đó mới xem xét tái kích hoạt paper canary.

## 1. Kết quả cần đạt

Kế hoạch này đưa repository từ trạng thái “nền tảng kỹ thuật đã triển khai nhưng workspace chưa sạch và bằng chứng vận hành chưa đủ” tới một mốc có thể kiểm chứng được:

```text
SOURCE_INTEGRITY_VERIFIED
        ↓
RELEASE_BUNDLE_REPRODUCIBLE
        ↓
LAUNCHER_FAIL_CLOSED_VERIFIED
        ↓
FULL_REGRESSION_CLEAN
        ↓
STATUS_EVIDENCE_RECONCILED
        ↓
PAPER_CANARY_READY_FOR_EXPLICIT_AUTHORIZATION
        ↓
NATURAL_ECONOMIC_EVIDENCE_ACCUMULATION
```

Mốc cuối của kế hoạch **không phải live trading**. Kết quả tối đa được phép là paper canary có kiểm soát và thu thập bằng chứng tự nhiên. Mọi kích hoạt vốn thật tiếp tục bị chặn.

## 2. Baseline đã xác minh

| Hạng mục | Trạng thái tại 2026-09-22 |
|---|---|
| Git | Đi trước `origin/main` 98 commit; đi trước remote cùng nhánh 9 commit |
| Working tree | 10 file tracked bị sửa, 10 file untracked |
| GitNexus | Index hiện tại tại `f96c6b8`; 19.843 symbols, 761 flows |
| Diff risk | `HIGH`; 12 symbols và 9 execution flows bị ảnh hưởng |
| Test discovery | 2.066 tests |
| Targeted tests | 32 tests đã pass |
| Full regression | Dừng ở 24% do thiếu release bundle cục bộ |
| Model coverage | MC9 `CLOSED`, release `SEALED`; 22 canonical symbols, 9 routable, 13 disabled |
| H14 | `CLOSED`, `RESEARCH_HARD_STOP`, H14.3 `BLOCKED_FINAL` |
| P8 | `ACCUMULATING`; 0 fills, 0 closed trades trong report hiện có |
| Runtime process | Không có process bot/paper-canary đang chạy |
| Production promotion | `NOT_AUTHORIZED` |
| Real money | `false` trong manifest hiện tại |

Lỗi regression đầu tiên hiện tại:

```text
tests/ml/test_model_coverage_mc8_negative.py::test_missing_model_raises_integrity_error
FileNotFoundError:
runtime/releases/model-coverage-v1/model_coverage_mc6_inference_registry.json
```

## 3. Ràng buộc không được vi phạm

1. Không mở lại H14, không thay đổi verdict H14 và không dùng dữ liệu H14 để tuning lại policy.
2. Không hợp thức hóa stream sai checksum bằng cách nới lỏng điều kiện kiểm tra.
3. Không copy thủ công model hoặc registry vào release bundle mà không có manifest và hash lineage.
4. Không sửa artifact sealed tại chỗ. Nếu identity thay đổi, phải tạo release ID hoặc revision mới.
5. Không chạy paper canary từ working tree bẩn.
6. Không tự động retry/restart runtime và không vượt spawn budget đã đóng băng.
7. Không tạo synthetic trades để làm chín P8.
8. Không cho phép live/real-money trong bất kỳ bước nào của kế hoạch này.
9. Không xóa hoặc ghi đè 20 thay đổi hiện có trước khi phân loại nguồn gốc và chủ sở hữu.
10. Mọi thay đổi code phải đi qua GitNexus `context` và upstream `impact` trước khi sửa.

## 4. Cảnh báo blast radius

GitNexus đã xác minh:

- `scripts/reconstitute_h14_evidence.py::build`: risk `LOW`, 4 dependents; tuy nhiên đây là biên provenance nên rủi ro governance được nâng lên **HIGH** theo ngữ cảnh.
- `scripts/p7_safe_paper_canary_launcher.py::validate_launch_request`: risk `MEDIUM`, 22 dependents, 10 direct callers; ảnh hưởng preflight, authorization snapshot và launch path.
- `scripts/mc8_assemble_bundle.py::main`: risk `LOW` trong call graph; rủi ro vận hành vẫn **HIGH** vì đầu ra là release artifact boundary.
- Toàn bộ diff hiện tại: risk `HIGH`, ảnh hưởng 9 execution flows liên quan model loading, deserialization, runtime compatibility và artifact resolution.

Do đó các work package dưới đây phải được thực hiện tuần tự theo gate. Không gộp sửa integrity, dựng bundle và kích hoạt runtime trong cùng một commit.

## 5. Kế hoạch thực thi

### WP0 — Đóng băng baseline và phân loại working tree

**Mục tiêu:** tạo một baseline có thể tái kiểm tra mà không làm mất thay đổi hiện có.

#### Công việc

- [ ] Ghi lại commit, branch, upstream divergence và `git status --porcelain=v2`.
- [ ] Lập danh mục 10 file tracked đã sửa và 10 file untracked theo nhóm:
  - launcher/governance;
  - release manifest/checksum;
  - H14 raw/reconstituted evidence;
  - tests;
  - scratch/recovery scripts.
- [ ] Với từng file, ghi rõ một trong các disposition:
  - `KEEP_AND_VALIDATE`;
  - `REGENERATE_FROM_SOURCE`;
  - `QUARANTINE_NON_AUTHORITATIVE`;
  - `DISCARD_ONLY_WITH_EXPLICIT_APPROVAL`.
- [ ] Tính SHA-256 cho tất cả manifest, sidecar và H14 JSONL đang được xem là nguồn đầu vào.
- [ ] Ghi lại danh sách process và heartbeat mới nhất; không coi `runtime_state=RUNNING` là liveness nếu không có process và heartbeat tươi.
- [ ] Chốt release lineage đang được phục hồi: `model-coverage-v1`, `model-coverage-v1-r1`, hay release `b05603d9`. Không trộn file giữa các lineage.

#### Deliverables

- `evidence/next-step-20260922/baseline_inventory.json`
- `evidence/next-step-20260922/worktree_disposition.md`
- `evidence/next-step-20260922/hash_inventory.json`

#### Gate G0 — Baseline Frozen

- Không có file hiện hữu bị xóa hoặc ghi đè.
- Mỗi thay đổi hiện tại có owner/disposition rõ ràng.
- Một release lineage duy nhất được chọn làm đối tượng phục hồi.
- `git diff --check` được ghi nhận đúng trạng thái, kể cả lỗi blank-line hiện có.

**Ước lượng:** 0,5 ngày kỹ thuật.

---

### WP1 — Khôi phục H14 evidence integrity

**Mục tiêu:** bảo đảm dữ liệu H14 chỉ được tái dựng khi raw stream khớp provenance đã đóng băng.

#### Vấn đề cần xử lý

Thay đổi hiện tại trong `reconstitute_h14_evidence.py` chỉ raise khi checksum sai **và** stream rỗng. Điều đó cho phép một stream không rỗng nhưng đã bị sửa vượt qua checksum gate.

#### Công việc

- [ ] Chạy lại GitNexus context/impact cho `build` ngay trước khi sửa.
- [ ] Khôi phục invariant fail-closed:
  - thiếu file → fail;
  - file rỗng → fail;
  - SHA-256 khác checkpoint → fail;
  - row count hoặc semantic identity khác checkpoint → fail;
  - không được tự động cập nhật expected hash từ file đang kiểm tra.
- [ ] Đối chiếu ba raw stream untracked với checkpoint sequence 681.
- [ ] Nếu hash không khớp:
  - giữ nguyên bản gốc;
  - tạo báo cáo mismatch;
  - xác định nguồn phục hồi từ commit/checkpoint đã seal;
  - không gắn nhãn authoritative cho tới khi provenance được chứng minh.
- [ ] Bổ sung negative tests cho các trường hợp:
  - non-empty stream bị đổi một byte;
  - thêm một record hợp lệ về schema nhưng sai provenance;
  - reorder records;
  - duplicate semantic key;
  - checkpoint hash bị thay đổi;
  - thiếu một trong ba stream.
- [ ] Giữ nguyên kết luận H14:
  - `CLOSED`;
  - `RESEARCH_HARD_STOP`;
  - H14.3 `BLOCKED_FINAL`;
  - successor research `NOT_AUTHORIZED`.

#### Kiểm tra bắt buộc

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/ml/test_h14_integrity.py
.\.venv\Scripts\python.exe scripts/reconstitute_h14_evidence.py
```

Lần chạy thứ hai phải tạo output byte-for-byte giống lần đầu khi input hợp lệ.

#### Gate G1 — H14 Integrity Closed

- Mọi mutation của raw stream đều bị chặn.
- Reconstitution deterministic.
- 647 authoritative analysis rows và 1.294 decision rows chỉ được công nhận khi hash/checkpoint khớp.
- Không có thay đổi model, threshold, policy hoặc H14 verdict.

**Ước lượng:** 1 ngày kỹ thuật.

---

### WP2 — Tái tạo release bundle theo lineage được quản trị

**Mục tiêu:** khôi phục bundle mà MC8/MC9 tests yêu cầu, không copy ad hoc và không làm biến đổi release sealed.

#### Công việc

- [ ] Chạy GitNexus context/impact cho:
  - `mc8_assemble_bundle.py::main`;
  - `InferenceRouter`;
  - `GovernedArtifactLoader`;
  - release readback/preflight entry points.
- [ ] Xác định vì sao bundle không tồn tại trên máy:
  - chưa provision sau chuyển máy;
  - bị loại bởi `/runtime/` trong `.gitignore`;
  - bundle cũ chỉ tồn tại ở máy/worktree trước;
  - test đang trỏ nhầm `model-coverage-v1` trong khi runtime contract là `model-coverage-v1-r1`.
- [ ] Đối chiếu source inputs:
  - inference registry;
  - model artifacts;
  - calibrators;
  - feature schema;
  - release manifest;
  - sidecars;
  - expected SHA-256.
- [ ] Dựng bundle trong staging/versioned directory; không ghi đè bundle sealed.
- [ ] Chạy assembler/readback bằng clean pinned worktree tương ứng với source commit.
- [ ] Xác minh self-containment: bundle không phụ thuộc file model ngoài release root.
- [ ] Xác minh tất cả đường dẫn trong registry là relative, nằm trong bundle và không escape root.
- [ ] Xác minh 9 routable symbols có đủ model/calibrator; 13 disabled symbols fail closed.
- [ ] So sánh bundle hash với release identity. Nếu không khớp, dừng và tạo release revision mới thay vì sửa hash để “cho pass”.
- [ ] Làm rõ test contract:
  - nếu authoritative release là `v1`, provision đúng `v1`;
  - nếu `v1-r1` đã supersede `v1`, cập nhật contract/test bằng một migration có bằng chứng, không symlink hoặc copy trá hình.

#### Kiểm tra bắt buộc

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/ml/test_model_coverage_mc8_negative.py `
  tests/ml/test_model_coverage_mc8_self_containment.py `
  tests/ml/test_model_coverage_mc8_seal.py `
  tests/ml/test_model_coverage_mc9_release_identity.py
```

#### Gate G2 — Release Reproducible

- Release registry tồn tại tại đúng identity/path.
- Bundle self-contained và hash-valid.
- Missing/corrupt model, calibrator, registry hoặc schema đều fail closed.
- Rebuild lặp lại tạo cùng manifest/hash.
- Không có artifact sealed nào bị sửa tại chỗ.

**Ước lượng:** 1–1,5 ngày kỹ thuật.

---

### WP3 — Hoàn tất launcher hardening và authorization contract

**Mục tiêu:** bảo đảm launcher chỉ có thể spawn một paper runtime từ đúng pinned boundary.

#### Công việc

- [ ] Chạy lại upstream impact cho `LaunchRequest`, `from_manifest` và `validate_launch_request`.
- [ ] Loại bỏ fallback hash hard-code hoặc implicit default. Mọi expected hash phải đến từ manifest/authorization đã seal.
- [ ] Xác minh thứ tự fail-closed trước spawn:
  1. mode phải là `PAPER`;
  2. `real_money_enabled=false`;
  3. pinned root không được trùng repository root/CWD;
  4. manifest hash khớp;
  5. release commit/tree khớp;
  6. pinned worktree sạch;
  7. artifact tồn tại và hash khớp;
  8. sidecar tồn tại và hash khớp;
  9. registry tồn tại và hash khớp;
  10. không có runner conflict;
  11. authorization còn `ARMED`, chưa consumed;
  12. spawn budget bằng 1, restart budget bằng 0.
- [ ] Bảo đảm validation failure không consume authorization và không spawn child.
- [ ] Bảo đảm sau spawn, authorization được consume atomically.
- [ ] Bảo đảm supervisor ghi nhận exit code/stderr và không tự retry.
- [ ] Tách commit launcher khỏi commit H14 và release provisioning.

#### Kiểm tra bắt buộc

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/ml/test_p7_safe_launcher_contract.py `
  tests/ml/test_p7_g6_authorization_snapshot.py `
  tests/ml/test_p7_r3a_supervised_child.py `
  tests/ml/test_p7_attempt5_runtime_composition.py `
  tests/ml/test_ml_engine_static_safety.py
```

#### Gate G3 — Launcher Fail-Closed

- Tất cả identity-negative tests pass.
- Không còn default hash hoặc đường dẫn ngầm.
- Validate-only không thay đổi immutable inputs.
- Một authorization chỉ tạo tối đa một spawn.
- GitNexus không báo caller/flow ngoài danh sách dự kiến.

**Ước lượng:** 1 ngày kỹ thuật.

---

### WP4 — Đưa regression về clean pass

**Mục tiêu:** thay thế các historical/conditional pass bằng kết quả hiện tại có exit code 0.

#### Trình tự test

1. Static và formatting:

   ```powershell
   git diff --check
   .\.venv\Scripts\python.exe -m pytest -q tests/ml/test_ml_engine_static_safety.py
   ```

2. H14 integrity suite.
3. MC8/MC9 bundle, negative, seal và readback suites.
4. P7 launcher, authorization, runtime composition và lineage suites.
5. Toàn bộ `tests/ml/`.
6. Full offline suite 2.066 tests.
7. Network-marked tests chạy riêng, chỉ khi môi trường và credential test được phê duyệt.

#### Quy tắc kết quả

- Không sử dụng allowlist lịch sử để che regression mới.
- Không coi `CONDITIONAL_PASS` là clean pass.
- Không sửa expected output chỉ để khớp implementation nếu contract chưa được phê duyệt.
- Lưu command, commit/tree, Python version, start/end time, passed/failed/skipped và log hash.
- Flaky test phải được lặp tối thiểu 3 lần và phân loại nguyên nhân trước khi cho qua.

#### Gate G4 — Regression Clean

- `git diff --check` exit 0.
- Targeted suites exit 0.
- `tests/ml/` exit 0.
- Full offline suite exit 0, không có unexpected skip/xpass.
- Không có missing local artifact ngoài các dependency được khai báo rõ.

**Ước lượng:** 0,5–1 ngày kỹ thuật, chưa tính thời gian xử lý lỗi mới.

---

### WP5 — Đồng bộ source of truth và báo cáo trạng thái

**Mục tiêu:** loại bỏ mâu thuẫn giữa README, roadmap, H14 state, P7/P8 reports và runtime state files.

#### Công việc

- [ ] Chọn một machine-readable status index làm nguồn chính.
- [ ] Đánh dấu `docs/research/research_cycle_state.json` là stale hoặc cập nhật nó theo H14 final branch state.
- [ ] Không ghi `RUNNING` chỉ dựa trên state file; liveness phải yêu cầu:
  - process còn tồn tại;
  - heartbeat trong SLA;
  - epoch/deployment identity khớp;
  - semantic progress tăng.
- [ ] Tạo P7 status report mới từ release/authorization/runtime evidence hiện tại.
- [ ] Tạo P8 report mới nhưng giữ verdict `ACCUMULATING` nếu chưa có closed natural trades.
- [ ] Cập nhật README để không hard-code số test cũ.
- [ ] Ghi rõ sự khác biệt giữa:
  - implementation complete;
  - paper-ready;
  - paper-active;
  - economic evidence mature;
  - live-authorized.
- [ ] Mọi generated report phải có timestamp, commit, tree, input hashes và generator version.

#### Gate G5 — Evidence Reconciled

- Không còn hai artifact authoritative đưa ra verdict trái nhau.
- Stale runtime state không thể được trình bày như runtime active.
- H14 final state, model coverage state và P7/P8 state được liên kết bằng provenance rõ ràng.
- README phản ánh đúng trạng thái “paper only, live blocked”.

**Ước lượng:** 0,5–1 ngày kỹ thuật.

---

### WP6 — Seal candidate và GitNexus change review

**Mục tiêu:** tạo candidate có thể review trước bất kỳ runtime action nào.

#### Công việc

- [ ] Refresh GitNexus index.
- [ ] Chạy change detection so với `main` và kiểm tra toàn bộ persistence/API/runtime boundaries.
- [ ] Chạy upstream impact lại cho tất cả symbol đã sửa.
- [ ] Xác minh không có `partial: true`, `truncated: true` hoặc `risk: UNKNOWN` chưa được xử lý.
- [ ] Tách commit theo boundary:
  1. H14 integrity;
  2. release provisioning/reproducibility;
  3. launcher hardening;
  4. tests và status reconciliation.
- [ ] Không commit scratch solvers hoặc raw evidence chưa được phân loại.
- [ ] Gắn hash của full regression report vào candidate seal report.

#### Lệnh kiểm tra cuối

```powershell
& 'C:\Program Files\Git\bin\bash.exe' ./scripts/gitnexus-refresh.sh
node .gitnexus/run.cjs detect-changes `
  --repo besttime-crypto --scope compare --base-ref main
```

Trên Windows hiện tại, gọi shell script qua Git Bash nếu `bash` không có trong PATH.

#### Gate G6 — Candidate Sealed

- Working tree chỉ chứa thay đổi dự kiến.
- GitNexus change set khớp kế hoạch.
- Không có HIGH/CRITICAL risk chưa review.
- Regression report clean và gắn đúng commit/tree.
- Release bundle và manifest immutable sau seal.

**Ước lượng:** 0,5 ngày kỹ thuật.

---

### WP7 — Tái kích hoạt paper canary có phê duyệt riêng

**Mục tiêu:** chạy một paper canary mới, có giám sát, không retry, không real money.

WP này chỉ bắt đầu khi G0–G6 đều pass và có phê duyệt rõ ràng cho runtime action.

#### Preflight bắt buộc

- [ ] Release identity/readback pass.
- [ ] Pinned worktree sạch và detached tại đúng commit.
- [ ] Manifest, artifact, sidecar và registry hashes khớp.
- [ ] Epoch ID, deployment ID và paper run ID mới, không tái sử dụng ID cũ.
- [ ] `mode=PAPER`.
- [ ] `real_money_enabled=false`.
- [ ] `LIVE_TRADING_ENABLED=false`.
- [ ] Testnet/dry-run boundary được xác minh.
- [ ] Không có runner conflict.
- [ ] Authorization mới ở trạng thái `ARMED`.
- [ ] Spawn budget 1; restart budget 0; automatic retry forbidden.

#### Sau spawn

- [ ] G8-A: process/release/epoch identity pass.
- [ ] G8-B: heartbeat và semantic progress được duy trì qua cửa sổ giám sát.
- [ ] G9: first cycle có prediction → final decision lineage hoàn chỉnh.
- [ ] G10: observation handoff ghi đúng evidence partition.
- [ ] Nếu child exit, pause, identity drift hoặc hash drift: fail closed; không tự restart.

#### Gate G7 — Paper Canary Active

- Runtime process thực sự tồn tại.
- Heartbeat tươi và semantic counters tăng.
- Không có disabled-symbol leak.
- Không có real-money path.
- Authorization đã consumed đúng một lần.

**Ước lượng:** 0,5 ngày để chuẩn bị/kích hoạt; thời gian giám sát tách riêng.

---

### WP8 — Tích lũy bằng chứng kinh tế P8

**Mục tiêu:** đánh giá kinh tế bằng closed natural trades từ sealed runtime.

#### Quy tắc thu thập

- Synthetic trades: `FORBIDDEN`.
- Intervention: `NONE`.
- Outcome leakage: `FORBIDDEN`.
- Tuning trước maturity threshold: `FORBIDDEN`.
- Đơn vị chính: closed natural trade.
- Chỉ số chính: realized net EV/trade sau phí và slippage thực tế nếu có.

#### Maturity gates

| Mức | Điều kiện | Hành động được phép |
|---|---:|---|
| Accumulating | `N = 0` hoặc chưa có closed trade | Chỉ kiểm tra pipeline/evidence |
| Preliminary | `N < 30` | Không ra quyết định kinh tế |
| Diagnostic | `30 <= N < 100` | Phân tích chẩn đoán, không promotion |
| Primary review | `N >= 100` | Được phép review EV/PF/drawdown theo contract |

#### Evidence funnel cần theo dõi

```text
prediction
→ final decision
→ actionable decision
→ execution attempt
→ fill
→ closed position
→ linked outcome
→ fee/slippage accounting
→ P8 economic sample
```

#### Gate G8 — Economic Review Ready

- Tối thiểu 100 closed natural trades hợp lệ.
- Prediction/decision/order/fill/outcome lineage đầy đủ.
- Không duplicate, orphan hoặc cross-epoch contamination.
- Chi phí được account theo contract.
- Không có model/policy change trong cửa sổ quan sát.
- Chỉ sau gate này mới lập economic verdict; verdict đó vẫn không tự động cấp quyền live.

**Ước lượng:** phụ thuộc tần suất sự kiện thị trường; không cam kết theo ngày lịch.

## 6. Thứ tự commit đề xuất

| Commit | Nội dung | Điều kiện trước commit |
|---|---|---|
| C1 | H14 strict integrity restoration + negative tests | G1 pass |
| C2 | Release bundle provisioning/rebuild contract | G2 pass |
| C3 | Launcher/authorization fail-closed hardening | G3 pass |
| C4 | Regression fixes không đổi contract | G4 pass |
| C5 | Status/evidence reconciliation | G5 pass |
| C6 | Candidate seal metadata | G6 pass |

Không đưa generated runtime observations của WP7/WP8 vào cùng commit với code changes.

## 7. Ma trận kiểm thử tối thiểu

| Boundary | Positive tests | Negative tests |
|---|---|---|
| H14 raw streams | deterministic rebuild | byte mutation, reorder, duplicate, wrong checkpoint |
| Release bundle | readback, self-containment | missing/corrupt model, calibrator, registry, schema |
| Artifact loader | valid approved-root load | path escape, unknown hash, disallowed deserialization |
| Launcher | validate-only, one spawn | live mode, dirty tree, hash mismatch, boundary collision |
| Authorization | atomic consume | reused, expired/consumed, wrong release, excess spawn |
| Runtime | heartbeat + semantic progress | stale heartbeat, child exit, identity drift |
| Lineage | end-to-end linked event | orphan fill/outcome, cross-epoch contamination |
| Economics | natural closed trade accounting | synthetic/intervened/leaky sample rejection |

## 8. Stop conditions

Dừng ngay work package hiện tại và không chuyển gate nếu xảy ra một trong các điều kiện:

- Không xác định được release lineage authoritative.
- Raw H14 stream sai hash mà không có nguồn phục hồi đã seal.
- Bundle rebuild không tái lập được hash.
- GitNexus trả `risk: UNKNOWN`, `partial` hoặc `truncated` cho critical boundary.
- Full suite có regression mới.
- Launcher có thể spawn trước khi hoàn tất identity validation.
- Runtime ghi `RUNNING` nhưng không có process/heartbeat/semantic progress đồng thời.
- Phát hiện live credential/order path trong paper canary.
- Model hoặc policy thay đổi trong P8 observation window.

## 9. Definition of Done

Kế hoạch được coi là hoàn thành về mặt kỹ thuật khi:

- [ ] H14 integrity fail-closed và H14 vẫn immutable.
- [ ] Release bundle authoritative được dựng lại reproducibly.
- [ ] MC8/MC9 bundle/readback/negative tests pass.
- [ ] P7 launcher và authorization tests pass.
- [ ] Full offline suite 2.066 tests hoặc số test cập nhật hơn exit 0.
- [ ] `git diff --check` pass.
- [ ] GitNexus refresh và compare-change review không có bất ngờ.
- [ ] Status artifacts không còn mâu thuẫn.
- [ ] Candidate seal gắn đúng commit/tree/test evidence hashes.
- [ ] Paper canary chỉ được đánh dấu `ACTIVE` khi process, heartbeat và semantic progress cùng pass.
- [ ] P8 tiếp tục `ACCUMULATING` cho tới khi đạt maturity contract.
- [ ] Live/real-money vẫn `NOT_AUTHORIZED`.

## 10. Ước lượng tổng thể

| Nhóm việc | Nỗ lực dự kiến |
|---|---:|
| WP0–WP1: baseline + H14 integrity | 1–1,5 ngày |
| WP2: release reproducibility | 1–1,5 ngày |
| WP3: launcher hardening | 1 ngày |
| WP4–WP6: regression, docs, seal | 1,5–2,5 ngày |
| WP7: paper-canary activation | 0,5 ngày + giám sát |
| WP8: economic accumulation | phụ thuộc sự kiện tự nhiên |

Tổng phần kỹ thuật trước quan sát: khoảng **5–7 ngày làm việc**, với điều kiện không phát sinh regression hoặc thiếu artifact nguồn. Thời gian để đạt P8 primary review không thể rút ngắn bằng synthetic data và phụ thuộc số closed natural trades.
