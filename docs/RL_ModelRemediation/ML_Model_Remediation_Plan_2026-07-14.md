# Kế hoạch Remediation Chi Tiết cho Hệ thống ML Trading

> **Ngày lập:** 14/07/2026  
> **Nguồn đầu vào:** Báo cáo rà soát các mô hình ML trong hệ thống  
> **Mục tiêu:** Loại bỏ rủi ro model/artifact mismatch, ngăn model chưa đủ bằng chứng tác động đến vốn, chuẩn hóa model governance và thiết lập quy trình promotion/rollback có thể kiểm chứng.

---

## 1. Mục tiêu remediation

Kế hoạch này tập trung vào 6 mục tiêu chính:

1. Đảm bảo runtime luôn sử dụng đúng artifact, đúng schema và đúng version.
2. Ngăn model chưa được chứng minh vượt baseline tác động trực tiếp đến lệnh.
3. Chuẩn hóa đường dẫn, metadata, hash và registry của model.
4. Kiểm soát feature drift, observation drift, calibration drift và data leakage.
5. Xây dựng promotion gate thống nhất cho supervised learning, RL và execution model.
6. Đảm bảo mỗi prediction có thể truy vết ngược tới model, feature schema và dữ liệu đầu vào.

---

## 2. Phạm vi

### 2.1 Trong phạm vi

- Ensemble Meta Model v3.1.
- Adaptive Random Forest.
- Recurrent PPO Exit Manager.
- Meta Model v3 candidate.
- TimeGAN và dữ liệu synthetic phục vụ RL.
- Slippage Model v2.
- Model registry, artifact management, prediction logging, drift monitoring.
- Unit test, integration test, replay test, shadow test và promotion gate.

### 2.2 Ngoài phạm vi

- Thay đổi chiến lược giao dịch kỹ thuật cốt lõi.
- Tối ưu exchange execution engine ngoài phần liên quan tới model slippage.
- Thay đổi dashboard UI lớn.
- Huấn luyện lại toàn bộ model trước khi hoàn tất các remediation nền tảng.

---

## 3. Nguyên tắc triển khai

1. **Safety first:** Model chưa vượt baseline chỉ được shadow/advisory.
2. **Canonical artifact:** Mỗi model chỉ có một đường dẫn production chính thức.
3. **Fail closed:** Không load được model, schema mismatch hoặc hash sai thì không dùng model.
4. **No silent fallback:** Fallback phải được log, metric hóa và hiển thị health status.
5. **Point-in-time correctness:** Feature dùng để train và inference phải tồn tại đúng thời điểm ra quyết định.
6. **Promotion bằng bằng chứng:** Không promotion chỉ dựa vào một chỉ số AUC hoặc reward đơn lẻ.
7. **Rollback tức thời:** Mọi promotion phải có previous production artifact để rollback.

---

# 4. Roadmap tổng thể

| Workstream | Mức độ | Thời gian gợi ý | Kết quả chính |
|---|---:|---:|---|
| WS1. Artifact & Path Consistency | P0 | 1–2 ngày | Runtime dùng đúng artifact và schema |
| WS2. Runtime Safety Guards | P0 | 1–2 ngày | RL/model lỗi không tác động live |
| WS3. Prediction Traceability | P0 | 1–2 ngày | Mỗi prediction truy vết được |
| WS4. Meta Model Calibration & Drift | P1 | 3–5 ngày | Giám sát calibration/drift rolling |
| WS5. RL Re-evaluation & Promotion Gate | P1 | 5–8 ngày | Đánh giá lại PPO theo observation 20 chiều |
| WS6. Meta Model v3 Leakage Audit | P1 | 4–7 ngày | Xác minh AUC cao có hợp lệ hay không |
| WS7. Slippage Model v2 Completion | P2 | 4–6 ngày | Artifact ML hợp lệ hoặc fallback rõ ràng |
| WS8. TimeGAN Governance | P2 | 2–4 ngày | Synthetic data có provenance và quality gate |
| WS9. Unified Model Registry | P1 | 4–6 ngày | Registry, promotion, rollback thống nhất |
| WS10. CI/CD & Operational Runbook | P1 | 3–5 ngày | Gate tự động trước deploy |

---

# 5. Workstream chi tiết

## WS1. Chuẩn hóa artifact và đường dẫn model

### Vấn đề

Adaptive Random Forest đang có hai artifact:

- `logs/adaptive_model.joblib`
- `btc_scraper/logs/adaptive_model.joblib`

Trainer và runtime loader không dùng cùng đường dẫn. Runtime có thể đang sử dụng artifact cũ mà không có cảnh báo.

### Công việc

#### 1.1 Tạo cấu hình model path tập trung

Tạo file:

```text
config/model_artifacts.yaml
```

Ví dụ:

```yaml
adaptive_rf:
  production_path: logs/adaptive_model.joblib
  metadata_path: logs/adaptive_model.metadata.json
  schema_version: adaptive-rf-v2

meta_model:
  production_path: logs/meta_model.joblib
  metadata_path: logs/meta_model.json
  schema_version: meta-v3.1-43f

rl_exit:
  production_path: logs/rl_models/production/rl_exit_ppo.zip
  metadata_path: logs/rl_models/production/metadata.json
  observation_schema_version: rl-exit-obs-v2
```

Không hard-code path tại nhiều module.

#### 1.2 Tạo `ArtifactResolver`

Tạo module:

```text
btc_scraper/ml_engine/artifact_resolver.py
```

Trách nhiệm:

- Resolve đường dẫn tuyệt đối từ project root.
- Kiểm tra file tồn tại.
- Kiểm tra SHA-256.
- Kiểm tra model type.
- Kiểm tra feature count và feature names.
- Kiểm tra schema version.
- Trả về structured load result.
- Không fallback sang artifact khác nếu chưa được cấu hình.

#### 1.3 Chuẩn hóa metadata

Mỗi artifact cần metadata tối thiểu:

```json
{
  "model_name": "adaptive_rf",
  "model_version": "2026.07.14.1",
  "artifact_sha256": "...",
  "trained_at": "2026-07-14T...",
  "training_dataset_id": "...",
  "training_sample_count": 18800,
  "feature_schema_version": "adaptive-rf-v2",
  "feature_names": [],
  "library_versions": {},
  "git_commit": "...",
  "status": "production"
}
```

#### 1.4 Migration artifact

- Chọn `logs/adaptive_model.joblib` làm canonical.
- Di chuyển artifact cũ vào `logs/model_archive/adaptive_rf/`.
- Không xóa artifact cũ ngay.
- Tạo migration report ghi hash, kích thước, thời điểm và model properties.

### Kiểm thử

- Unit test resolver với file tồn tại/không tồn tại/hash sai/schema sai.
- Integration test khẳng định `signal_score.py` load đúng canonical path.
- Test log phải chứa model version và SHA.
- Test cố tình đặt artifact khác ở `btc_scraper/logs/`; runtime không được load file đó.

### Acceptance criteria

- Chỉ còn một artifact production canonical.
- Trainer và runtime cùng đọc cấu hình chung.
- Schema/hash mismatch làm model bị disable.
- Không có silent fallback.
- Health endpoint hiển thị artifact đang active.

---

## WS2. Runtime safety guard cho model

### Vấn đề

- PPO hiện không chứng minh vượt baseline.
- Observation runtime đã thay đổi từ 18 lên 20 chiều.
- Loader chọn file PPO mới nhất theo tên, không theo trạng thái production.
- Model lỗi có thể bị che bởi fallback hoặc recommendation logic.

### Công việc

#### 2.1 Khóa PPO ở shadow mode mặc định

Cấu hình:

```env
RL_EXIT_MODE=shadow
RL_EXIT_ALLOW_LIVE_ACTION=false
```

Mode hợp lệ:

- `disabled`
- `shadow`
- `advisory`
- `active`

Chỉ `active` mới được phép ảnh hưởng execution, nhưng phải qua promotion gate.

#### 2.2 Loại bỏ cơ chế “latest filename wins”

Không chọn model bằng glob mới nhất:

```python
rl_exit_ppo_*.zip
```

Thay bằng registry hoặc symlink/canonical path:

```text
logs/rl_models/production/rl_exit_ppo.zip
```

#### 2.3 Observation contract

Tạo dataclass hoặc Pydantic model:

```python
class RLExitObservationV2:
    schema_version: Literal["rl-exit-obs-v2"]
    values: list[float]
    feature_names: list[str]
```

Guard:

- Chính xác 20 chiều.
- Thứ tự feature cố định.
- Không NaN/Inf.
- Giá trị normalized đúng range.
- Model metadata phải khai báo cùng observation schema.

#### 2.4 Action safety mapping

Mọi action RL phải đi qua rule guard:

```text
RL recommendation
      |
      v
Position risk guard
      |
      v
Allowed action / downgraded action / rejected
```

Ví dụ:

- `EXIT`: chỉ advisory nếu confidence thấp.
- `PARTIAL_CLOSE_50`: giới hạn phần trăm.
- `MOVE_SL_TO_BREAKEVEN`: không làm SL xấu hơn.
- `TRAILING_SL_ATR`: clamp theo min/max ATR.
- Không cho RL tăng risk hoặc mở thêm vị thế.

#### 2.5 Circuit breaker cho inference

Disable model khi:

- Inference exception vượt ngưỡng.
- Observation mismatch.
- Latency vượt SLA.
- Prediction phân phối bất thường.
- Model output không thuộc action space.
- Model file hash thay đổi ngoài deployment.

### Acceptance criteria

- PPO mặc định shadow.
- Không model nào được chọn chỉ vì filename mới hơn.
- Observation mismatch làm inference bị reject.
- RL không thể bypass risk rule.
- Có metric cho accepted/rejected/downgraded recommendations.

---

## WS3. Prediction traceability và audit log

### Vấn đề

Prediction log chưa đủ thông tin để biết chính xác model nào đã tạo quyết định.

### Công việc

#### 3.1 Chuẩn hóa prediction envelope

Mỗi prediction phải có:

```json
{
  "prediction_id": "uuid",
  "timestamp": "...",
  "symbol": "BTCUSDT",
  "decision_context": "entry|exit|slippage",
  "model_name": "meta_model",
  "model_version": "2026.07.14.1",
  "artifact_sha256": "...",
  "feature_schema_version": "meta-v3.1-43f",
  "feature_hash": "...",
  "calibration_method": "isotonic",
  "raw_prediction": 0.73,
  "calibrated_prediction": 0.68,
  "fallback_used": false,
  "latency_ms": 12.4,
  "git_commit": "...",
  "deployment_id": "..."
}
```

#### 3.2 Feature snapshot

Không nhất thiết log toàn bộ feature ở log chính. Có thể:

- Lưu feature values vào JSONL hoặc database.
- Log `feature_hash`.
- Mask/redact nếu có dữ liệu nhạy cảm.
- Đảm bảo replay được prediction.

#### 3.3 Liên kết decision và execution

Thêm:

- `signal_id`
- `position_id`
- `order_id`
- `fill_id`
- `prediction_id`

Cho phép truy vết:

```text
prediction -> signal -> order -> fill -> outcome
```

#### 3.4 Retention

- Prediction metadata: tối thiểu 180 ngày.
- Feature snapshot: tối thiểu 90 ngày.
- Production promotion record: không xóa.
- Artifact hash registry: không xóa.

### Acceptance criteria

- Có thể chọn một order bất kỳ và truy ra model/version/hash.
- Có replay script tái tạo prediction từ feature snapshot.
- Fallback luôn được đánh dấu.
- Không có prediction production thiếu schema version.

---

## WS4. Meta Model v3.1 calibration và drift monitoring

### Vấn đề

Calibration ở hai tail xác suất chưa tốt:

- Bucket thấp có sai lệch lớn.
- Bucket cao có sai lệch lớn và số mẫu nhỏ.
- Xác suất cực trị dễ bị hiểu sai thành confidence cao.

### Công việc

#### 4.1 Giới hạn confidence sử dụng trong runtime

Tạm thời:

```text
calibrated_probability < 0.40 -> không tự động suy diễn tail
calibrated_probability > 0.80 -> clamp hoặc yêu cầu minimum sample support
```

Khuyến nghị:

- Clamp production probability vào `[0.40, 0.80]` cho sizing.
- Raw probability vẫn được log.
- Không tăng position size chỉ vì probability > 0.80.

#### 4.2 Calibration dashboard

Theo dõi rolling 7/14/30 ngày:

- Brier score.
- Expected Calibration Error.
- Maximum Calibration Error.
- ROC-AUC.
- PR-AUC.
- Win rate theo decile.
- Sample count theo bucket.
- Prediction distribution.
- PSI và feature drift.

#### 4.3 Gate theo sample count

Không kết luận calibration bucket nếu:

```text
bucket_sample_count < 100
```

Bucket sample thấp phải hiển thị trạng thái `insufficient_evidence`.

#### 4.4 Recalibration pipeline

Tách recalibration khỏi full retrain:

```text
Model weights giữ nguyên
        |
        v
New calibration window
        |
        v
Compare Platt / Isotonic / Beta calibration
        |
        v
Promote calibrator nếu vượt gate
```

#### 4.5 Drift alert

Cảnh báo khi:

- PSI > 0.20: warning.
- PSI > 0.30: critical.
- Rolling AUC giảm > 0.05 so với production baseline.
- ECE > 0.10.
- Tail prediction tăng bất thường.
- Feature missing rate tăng.

### Acceptance criteria

- Dashboard có metric theo bucket.
- Tail probability không trực tiếp tăng sizing.
- Recalibration có artifact/version riêng.
- Drift alert có severity và runbook.

---

## WS5. Đánh giá lại RL PPO và promotion gate

### Vấn đề

- PPO kém rule-based baseline.
- Observation schema đã đổi.
- Training reward âm.
- Evaluation cũ không đủ để active.

### Công việc

#### 5.1 Đóng băng artifact hiện tại

Gắn trạng thái:

```json
{
  "status": "shadow",
  "promotion_blocked": true,
  "reason": "underperforms_rule_baseline_and_observation_drift"
}
```

#### 5.2 Xây dựng evaluation dataset đúng chuẩn

- Walk-forward theo thời gian.
- Tách theo symbol.
- Tách theo regime.
- Có phí, slippage, latency.
- Không dùng sequence từ tương lai.
- Synthetic data không được nằm trong test set production.
- Test set phải là dữ liệu real market unseen.

#### 5.3 Baseline bắt buộc

So sánh với:

1. Rule-based exit hiện tại.
2. Hold-to-SL/TP.
3. Trailing stop ATR.
4. Random policy sanity check.

#### 5.4 Metrics

Không chỉ dùng reward:

- Net PnL.
- Sharpe/Sortino.
- Max drawdown.
- Profit factor.
- Win rate.
- Expected shortfall.
- Average holding time.
- Turnover.
- Commission/slippage cost.
- Tail loss.
- Action stability.
- Catastrophic exit count.

#### 5.5 Promotion gate đề xuất

PPO chỉ được từ shadow lên advisory nếu:

- Không observation mismatch.
- Vượt baseline về net PnL.
- Không làm max drawdown xấu hơn quá 5%.
- Bootstrap confidence interval của delta reward/PnL không hoàn toàn âm.
- Ít nhất 1.000 episode hoặc số mẫu tương đương.
- Kết quả ổn định trên ít nhất 3 regime.
- Không có catastrophic action.

Từ advisory lên active:

- Shadow tối thiểu 30 ngày.
- Ít nhất 500 quyết định exit đủ outcome.
- Vượt baseline sau fee/slippage.
- Không critical incident.
- Có rollback test.

#### 5.6 Offline replay và shadow comparison

Mỗi quyết định live:

```text
Rule action
RL action
Final guarded action
Outcome
Counterfactual estimate
```

### Acceptance criteria

- Có report mới dùng observation 20 chiều.
- PPO không active trước khi qua gate.
- Evaluation tách real và synthetic.
- Kết quả so sánh baseline có confidence interval.
- Promotion có phê duyệt và rollback artifact.

---

## WS6. Audit Meta Model v3 candidate

### Vấn đề

Meta Model v3 có AUC 0,8382, cao bất thường so với v3.1. Có rủi ro leakage hoặc feature không tồn tại tại thời điểm entry.

### Công việc

#### 6.1 Feature availability audit

Với từng feature:

- Nguồn dữ liệu.
- Thời điểm quan sát.
- Thời điểm được ghi.
- Có dùng dữ liệu sau entry không.
- Có derived từ outcome không.
- Có chứa close/high/low của candle chưa đóng không.

Tạo `feature_availability_manifest.json`.

#### 6.2 Point-in-time join audit

Kiểm tra:

```text
feature.observed_at <= decision_at
```

Không join record theo nearest timestamp nếu có thể lấy tương lai.

#### 6.3 Split audit

So sánh:

- Random split.
- Time split.
- Purged time-series split.
- Embargo split.
- Group split theo symbol.
- Walk-forward.

Nếu AUC giảm mạnh khi dùng purged/time split, đánh dấu leakage risk.

#### 6.4 Duplicate leakage

Kiểm tra:

- Record trùng.
- Cùng signal xuất hiện ở train/test.
- Cùng candle window xuất hiện ở nhiều sample.
- Synthetic/augmented record xuất hiện ở test.
- Label leakage qua feature tên outcome/pnl/exit.

#### 6.5 Ablation study

Loại từng nhóm feature:

- Price/technical.
- Market structure.
- Sentiment.
- Regime.
- Position/outcome-adjacent features.
- Cross-asset.

Nếu một nhóm làm AUC tăng bất thường, audit sâu nhóm đó.

#### 6.6 Promotion gate

Candidate chỉ được promotion khi:

- Purged walk-forward AUC đạt ngưỡng.
- Feature availability 100%.
- Không leakage.
- Calibration đạt.
- Runtime schema parity.
- Latency đạt SLA.
- Shadow result vượt v3.1.

### Acceptance criteria

- Có leakage audit report.
- Có manifest thời điểm feature.
- Có kết quả purged walk-forward.
- Không promotion chỉ dựa vào test AUC 0,8382.
- Candidate được gắn trạng thái rõ ràng trong registry.

---

## WS7. Hoàn thiện Slippage Model v2

### Vấn đề

Code đã có loader nhưng artifact chưa tồn tại. Runtime fallback v1 rule-based mà chưa có observability đầy đủ.

### Công việc

#### 7.1 Quyết định activation state

Tạm thời đặt:

```yaml
slippage_model_v2:
  status: disabled
  fallback: rule_based_v1
```

#### 7.2 Schema parity

Đảm bảo feature train và inference giống nhau:

- Cùng tên.
- Cùng thứ tự.
- Cùng đơn vị.
- Cùng normalization.
- Cùng missing-value semantics.

#### 7.3 Dataset

Chỉ dùng fill thật hoặc paper fill đủ tin cậy:

- Order size.
- Spread.
- Depth.
- Volatility.
- Side.
- Order type.
- Latency.
- Market regime.
- Realized slippage.

Không dùng synthetic fill làm bằng chứng promotion live.

#### 7.4 Metrics

- MAE bps.
- Median absolute error.
- P90/P95 error.
- Bias theo BUY/SELL.
- Error theo symbol/regime/order type.
- Underprediction rate.
- Cost impact.

#### 7.5 Runtime fallback metrics

Log:

- `slippage_model_active`.
- `fallback_reason`.
- `prediction_source`.
- `model_version`.

### Acceptance criteria

- Artifact tồn tại với metadata/hash/schema.
- Train/inference feature parity test pass.
- Model vượt rule-based ở holdout và walk-forward.
- Fallback được metric hóa.
- Không gọi v2 là active khi artifact không có.

---

## WS8. TimeGAN governance

### Vấn đề

Synthetic OHLCV được dùng để train RL nhưng chưa có governance rõ về chất lượng và provenance.

### Công việc

#### 8.1 Dataset provenance

Mỗi synthetic dataset cần:

```json
{
  "generator_version": "...",
  "generator_hash": "...",
  "source_dataset_id": "...",
  "generated_at": "...",
  "sequence_length": 64,
  "sample_count": 10000,
  "random_seed": 42
}
```

#### 8.2 Quality metrics

So sánh real vs synthetic:

- Return distribution.
- Volatility.
- Autocorrelation.
- Cross-correlation OHLCV.
- Tail behavior.
- Drawdown distribution.
- Regime distribution.
- Discriminative score.
- Predictive score.

#### 8.3 Usage rules

- Synthetic chỉ dùng train/augmentation.
- Không dùng synthetic trong validation/test production.
- Báo cáo phải tách kết quả real-only và mixed-data.
- Giới hạn tỷ lệ synthetic trong batch.

#### 8.4 Stress scenarios

Có thể tạo dataset stress riêng, nhưng phải gắn nhãn:

```text
synthetic_stress
```

Không trộn với historical-like synthetic.

### Acceptance criteria

- Mọi file synthetic có provenance.
- Test set không chứa synthetic.
- Có quality report.
- Có tỷ lệ synthetic tối đa trong training config.

---

## WS9. Unified Model Registry và promotion workflow

### Mục tiêu

Thống nhất registry đã có với tất cả model production/candidate/shadow.

### Trạng thái chuẩn

```text
candidate
shadow
production
archive
rejected
disabled
```

### Registry record

```json
{
  "model_name": "meta_model",
  "version": "2026.07.14.1",
  "status": "production",
  "artifact_path": "...",
  "sha256": "...",
  "schema_version": "...",
  "metrics": {},
  "promotion_gate_result": {},
  "approved_by": "...",
  "promoted_at": "...",
  "previous_production_version": "..."
}
```

### Promotion flow

```text
Train
  -> Validate
  -> Register candidate
  -> Offline gate
  -> Shadow
  -> Shadow gate
  -> Production
  -> Monitor
  -> Rollback/Archive
```

### Quy tắc

- Chỉ một production version cho mỗi model.
- Promotion là atomic.
- Previous production giữ nguyên để rollback.
- Artifact không được overwrite.
- Hash mismatch tự chuyển unhealthy.
- Mọi promotion cần report được lưu.

### Acceptance criteria

- Tất cả model/artifact được đăng ký.
- Runtime chỉ load production hoặc shadow theo config.
- Promotion/rollback có test.
- Artifact overwrite bị chặn.
- Registry health hiển thị trên `/dependencies` hoặc endpoint model riêng.

---

## WS10. CI/CD, test và runbook

### 10.1 Test suite bắt buộc

#### Unit tests

- Artifact resolver.
- Metadata parser.
- Feature schema validator.
- Observation validator.
- Calibration bucket calculator.
- Drift metrics.
- Promotion gate.
- RL action guard.

#### Integration tests

- Trainer output được runtime load.
- Prediction log có đầy đủ metadata.
- Registry promotion atomic.
- Rollback hoạt động.
- Model unavailable thì fallback đúng.
- Hash mismatch thì model không load.
- Adaptive RF path consistency.
- PPO observation 20 chiều.

#### Replay tests

- Tái tạo prediction từ snapshot.
- So sánh prediction trước/sau refactor.
- Kiểm tra deterministic với cùng seed/artifact/input.

#### Failure injection

- Artifact bị corrupt.
- Metadata thiếu.
- Model inference timeout.
- NaN feature.
- Schema mismatch.
- Registry unavailable.
- Disk read-only.
- Model path bị thay đổi.

### 10.2 Deployment gate

Không deploy nếu:

- Có model path hard-code ngoài config.
- Artifact thiếu metadata/hash.
- Schema parity test fail.
- Prediction traceability test fail.
- PPO active nhưng chưa có promotion record.
- Candidate v3 chưa có leakage audit.
- Slippage v2 active nhưng artifact không tồn tại.

### 10.3 Runbook

Tạo:

```text
docs/runbooks/ML_Model_Operations_Runbook.md
```

Bao gồm:

- Kiểm tra model health.
- Xác định model đang active.
- Disable model.
- Chuyển shadow mode.
- Rollback artifact.
- Xử lý hash mismatch.
- Xử lý drift alert.
- Xử lý calibration degradation.
- Xử lý inference latency.
- Thu thập evidence sau incident.

---

# 6. Thứ tự triển khai đề xuất

## Sprint 1 — Safety và tính đúng đắn

Ưu tiên bắt buộc:

1. WS1 Artifact & Path Consistency.
2. WS2 Runtime Safety Guards.
3. WS3 Prediction Traceability.
4. Tạo health endpoint cho model.
5. Bổ sung CI gate cơ bản.

### Exit gate Sprint 1

- Adaptive RF chắc chắn dùng đúng artifact.
- PPO ở shadow mặc định.
- Không còn latest-filename selection.
- Mỗi prediction có model version/hash/schema.
- Runtime fail closed khi schema/hash sai.

---

## Sprint 2 — Validation và governance

1. WS4 Calibration & Drift.
2. WS5 RL Re-evaluation.
3. WS6 Meta v3 Leakage Audit.
4. WS9 Unified Registry.

### Exit gate Sprint 2

- Có calibration/drift dashboard.
- Có report PPO observation 20 chiều.
- Có leakage audit cho Meta v3.
- Registry quản lý promotion/rollback.

---

## Sprint 3 — Execution intelligence và synthetic governance

1. WS7 Slippage Model v2.
2. WS8 TimeGAN Governance.
3. WS10 hoàn thiện CI/CD và runbook.

### Exit gate Sprint 3

- Slippage v2 hoặc được active có bằng chứng, hoặc được đánh dấu disabled rõ ràng.
- Synthetic data có provenance.
- Test production gate tự động.
- Runbook hoàn chỉnh.

---

# 7. Ma trận ưu tiên rủi ro

| Rủi ro | Khả năng | Tác động | Ưu tiên | Biện pháp |
|---|---:|---:|---:|---|
| Runtime load nhầm Adaptive RF artifact | Cao | Cao | P0 | Canonical path + hash/schema guard |
| PPO tác động live dù kém baseline | Trung bình | Rất cao | P0 | Shadow default + promotion block |
| Observation RL mismatch | Cao | Cao | P0 | Observation contract |
| Không truy vết model tạo prediction | Cao | Cao | P0 | Prediction envelope |
| Meta v3 leakage | Trung bình | Rất cao | P1 | Purged walk-forward + feature audit |
| Calibration tail gây sizing quá mức | Trung bình | Cao | P1 | Clamp + bucket monitoring |
| Slippage v2 silent fallback | Cao | Trung bình | P1 | Explicit status + metrics |
| Synthetic data làm méo evaluation | Trung bình | Cao | P1 | Real-only test + provenance |
| Artifact bị overwrite | Trung bình | Cao | P1 | Immutable registry |
| Drift không được phát hiện | Trung bình | Cao | P1 | Rolling drift monitoring |

---

# 8. KPI và SLO đề xuất

## Artifact integrity

- 100% production artifact có SHA-256.
- 100% prediction production ghi model version.
- 0 lần silent fallback.
- 0 artifact overwrite.

## Runtime reliability

- Inference success rate ≥ 99,5%.
- P95 inference latency:
  - Meta Model ≤ 100 ms.
  - Adaptive RF ≤ 50 ms.
  - RL Exit ≤ 150 ms.
- Schema mismatch phải được phát hiện trước execution.

## Model quality

### Meta Model

- Rolling ROC-AUC không giảm quá 0,05.
- ECE ≤ 0,10.
- Brier score không xấu hơn baseline quá ngưỡng định trước.
- Mỗi calibration bucket production cần ≥100 outcome trước khi kết luận.

### RL Exit

- Không promotion nếu không vượt rule baseline.
- Max drawdown không xấu hơn baseline quá 5%.
- Không catastrophic action.
- Shadow tối thiểu 30 ngày trước active.

### Slippage

- MAE và P95 error phải tốt hơn rule-based.
- Underprediction rate phải được kiểm soát.
- Evaluation tách theo side/symbol/regime.

---

# 9. Deliverables

## Code

- `btc_scraper/ml_engine/artifact_resolver.py`
- `btc_scraper/ml_engine/model_registry.py`
- `btc_scraper/ml_engine/schema_validator.py`
- `btc_scraper/ml_engine/prediction_logger.py`
- `btc_scraper/ml_engine/drift_monitor.py`
- `btc_scraper/trading/rl_action_guard.py`

## Config

- `config/model_artifacts.yaml`
- `config/model_promotion_gates.yaml`
- `.env.example` cập nhật mode và guard.

## Reports

- `docs/remediation/Adaptive_RF_Artifact_Migration_Report.md`
- `docs/remediation/RL_Exit_Reevaluation_Report.md`
- `docs/remediation/Meta_Model_v3_Leakage_Audit.md`
- `docs/remediation/Meta_Model_Calibration_Report.md`
- `docs/remediation/Slippage_Model_v2_Validation_Report.md`
- `docs/remediation/TimeGAN_Quality_Report.md`

## Runbook

- `docs/runbooks/ML_Model_Operations_Runbook.md`

## Tests

- `tests/ml/test_artifact_resolver.py`
- `tests/ml/test_model_registry.py`
- `tests/ml/test_schema_parity.py`
- `tests/ml/test_prediction_traceability.py`
- `tests/ml/test_rl_observation_contract.py`
- `tests/ml/test_rl_action_guard.py`
- `tests/ml/test_promotion_gates.py`

---

# 10. Definition of Done tổng thể

Remediation được xem là hoàn tất khi:

1. Runtime chỉ load artifact được registry chỉ định.
2. Mọi artifact production có hash, metadata và schema version.
3. Adaptive RF trainer/loader dùng cùng canonical path.
4. PPO không thể active nếu chưa có promotion record.
5. Observation RL train/inference cùng schema 20 chiều.
6. Meta v3 có leakage audit và purged walk-forward report.
7. Meta v3.1 có calibration/drift monitoring rolling.
8. Prediction có thể truy vết tới signal, order, fill và outcome.
9. Slippage v2 có trạng thái thực tế rõ ràng; không silent fallback.
10. Synthetic data không xuất hiện trong production test set.
11. Promotion/rollback được test tự động.
12. Runbook xử lý model incident đã hoàn chỉnh.

---

# 11. Khuyến nghị quyết định ngay

Trước khi thực hiện bất kỳ huấn luyện hoặc promotion mới nào:

1. Đặt `RL_EXIT_MODE=shadow`.
2. Đặt `RL_EXIT_ALLOW_LIVE_ACTION=false`.
3. Chọn `logs/adaptive_model.joblib` làm artifact canonical.
4. Disable cơ chế chọn PPO mới nhất bằng glob.
5. Bắt buộc log model version, SHA và schema cho prediction.
6. Gắn Meta Model v3 trạng thái `candidate_blocked_pending_leakage_audit`.
7. Gắn Slippage Model v2 trạng thái `disabled_missing_artifact`.
8. Không dùng xác suất Meta Model >0,80 để tăng sizing cho đến khi đủ sample calibration.

Các thay đổi trên giảm ngay các rủi ro lớn nhất mà chưa cần retrain model.
