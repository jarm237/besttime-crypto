# Báo Cáo Đánh Giá Mô Hình ML - besttime-crypto

Ngày đánh giá: 2026-07-17
Trạng thái đánh giá: cập nhật sau runtime linkage/provenance và WLD operational correction

Nguồn trạng thái tổng hợp: `docs/remediation/System_Status_Report_2026-07-17.md`

## Tóm Tắt Điều Hành

Hệ thống ML hiện có 3 lớp chính:

1. **Meta Model production** (`meta_model` v3.1): chấm xác suất thắng cho entry signal, ghi audit prediction chính quy vào `logs/prediction_audit/`.
2. **Adaptive RF** (`adaptive_rf`): hỗ trợ signal scoring từ dữ liệu closed trades/adaptive signals.
3. **RL Exit** (`rl_exit`): đang ở trạng thái `shadow`, dùng để khuyến nghị quản lý/thoát vị thế nhưng chưa được phép active.

Kết luận ngắn:

- Meta scoring vẫn chạy đúng sau khi bỏ Prediction Shadow.
- Production artifacts hiện resolve khỏe và khớp SHA trong metadata/registry.
- Prediction Shadow legacy đã bị loại khỏi luồng chính; nguồn audit chính hiện là `logs/prediction_audit/predictions_YYYY-MM-DD.jsonl`.
- RL Exit Shadow có tracking outcome tốt hơn Meta prediction audit.
- Điểm nghẽn lớn nhất hiện tại là **runtime outcome linkage cho Meta Model chưa khép vòng**: prediction audit có rất nhiều prediction nhưng gần như không có `signal_id`, `position_id`, `order_id`, `fill_id`, nên chưa thể dùng trực tiếp để calibration từ dữ liệu thật.
- "Continuous Learning" hiện là offline retrain/backtest learning, chưa phải continuous learning từ runtime outcome thật.
- Runtime linkage/calibration framework hiện đã có covered paper path, recovery/out-of-order evidence và Gate A evidence tooling, nhưng shadow evidence window vẫn chưa bắt đầu.
- Trade provenance đã được chuẩn hóa để tách system paper orders khỏi user Telegram/UI/CLI orders.
- WLD operational correction ngày 2026-07-17 đã xóa duplicate open WLD và sửa closed WLD gần nhất thành manual theo system signal; đây là data correction, không phải bằng chứng runtime calibration để promote model.

## Cập Nhật Vận Hành 2026-07-17

Runtime provenance mới:

```text
order_creator = system | user | test
order_channel = paper_runner | live_runner | telegram | ui | cli | manual | test | unknown
```

Điều này giúp phân biệt:
- paper orders do hệ thống tạo: `system + paper_runner`;
- manual Telegram orders: `user + telegram`;
- UI orders: `user + ui`;
- CLI orders: `user + cli`;
- manual orders theo signal vẫn là user-created, với `manual_decision_basis = system_signal`.

WLD correction:

```text
open_wld_count = 0
corrected_id = deadd193-2f1b-4bd1-afef-c75a95d33181
entry_price = 0.3978
exit_price = 0.3943
pnl_pct = 0.8798
result = WIN
trade_origin = manual
manual_decision_basis = system_signal
order_channel = telegram
```

Focused verification:

```text
tests/test_trade_provenance.py + tests/ml/test_paper_lifecycle_e2e.py: 19 passed
```

ML interpretation:
- The correction improves operational trade history consistency.
- It should not be treated as fresh runtime calibration evidence for Meta Model promotion.
- Meta Model promotion remains blocked until Gate A and shadow evidence windows are satisfied.

## 1. Kiến Trúc ML Hiện Tại

Luồng runtime chính:

```text
OHLCV / market data
  -> analyze_market()
  -> signal text + features
  -> score_signal() / evaluate_signal_score()
     -> adaptive_rf hỗ trợ base scoring
     -> meta_model predict_proba()
     -> meta probability + Kelly sizing + gating
  -> auto_trader / execution engine
  -> position_tracker khi đóng lệnh
```

Log/audit chính:

```text
Meta prediction:
  logs/prediction_audit/predictions_YYYY-MM-DD.jsonl
  logs/prediction_audit/feature_snapshots_YYYY-MM-DD.jsonl

Entry diagnostics:
  logs/meta_prob_entry_YYYY-MM-DD.log

Closed trade/adaptive outcomes:
  logs/adaptive_signals.json
  logs/adaptive_signals_v2.json

RL Exit shadow:
  logs/rl_exit_shadow_predictions.json
```

Prediction Shadow legacy đã bị bỏ:

```text
logs/shadow_predictions.json
logs/predictions_YYYY-MM-DD.log
scripts/calibration_report.py
scripts/migrate_shadow.py
scripts/simulate_shadow_mode.py
scripts/generate_april_shadow.py
```

## 2. Meta Model Production

Artifact production:

| Thuộc tính | Giá trị |
|---|---|
| Model name | `meta_model` |
| Version | `v3.1` |
| File | `logs/meta_model.joblib` |
| Metadata | `logs/meta_model.json` |
| Status | `production` |
| Schema | `meta-v3.1-43f` |
| SHA256 | `4f7bc98a6c18d04d7853a180c4f68763298580128a206bf159f4d16c956cf1e1` |
| Kích thước artifact | khoảng 2.04 MB |
| Training samples | 24.070 |
| Features production | 43 |
| Calibration method | `isotonic` |

Ensemble hiện tại:

| Model | Trọng số |
|---|---:|
| XGBoost | 54,84% |
| CatBoost | 43,60% |
| LightGBM | 1,56% |

RandomForest không còn trong ensemble production hiện tại. Đây là khác biệt lớn so với báo cáo cũ ngày 2026-06-24.

### Hiệu Suất Từ Metadata Production

| Metric | Giá trị |
|---|---:|
| CV AUC mean | 0,6160 |
| CV AUC std | 0,0192 |
| CV Accuracy mean | 0,5803 |
| Ensemble CV AUC mean | 0,6253 |
| Ensemble CV Accuracy mean | 0,5880 |
| Calibration train/calib/test | 16.849 / 3.610 / 3.611 |
| Selected calibration error | 7,36 |

Nhận xét: AUC khoảng 0,62 là hợp lý cho bài toán crypto/noisy signal, nhưng chưa đủ để tăng aggressive sizing nếu không có runtime calibration bằng outcome thật.

### Calibration Buckets Production

| Bucket | Count | Actual WR | Predicted WR | Error | Trạng thái |
|---|---:|---:|---:|---:|---|
| 0.0-0.4 | 1.373 | 34,6% | 20,0% | +14,6 | chưa tốt |
| 0.4-0.6 | 1.569 | 50,5% | 50,0% | +0,5 | tốt |
| 0.6-0.7 | 580 | 66,4% | 65,0% | +1,4 | tốt |
| 0.7-0.8 | 54 | 79,6% | 75,0% | +4,6 | khá nhưng ít mẫu |
| 0.8-1.0 | 35 | 74,3% | 90,0% | -15,7 | không đủ evidence |

Vùng trung `0.4-0.7` calibration tốt. Hai đuôi phân phối còn yếu:

- Bucket thấp `0.0-0.4` đang under-estimate win rate.
- Bucket cao `0.8-1.0` có quá ít mẫu và đang over-confident.

Runtime đã có cơ chế giữ raw prediction trong audit, đồng thời dùng sizing probability bị clamp để tránh tail calibration chưa đủ evidence làm phình position size.

## 3. Recalibration Và Continuous Learning

### Periodic Recalibration

File gần nhất:

```text
logs/recalibration_latest.json
```

Kết quả gần nhất:

| Thuộc tính | Giá trị |
|---|---:|
| Timestamp | 2026-07-15T19:00:04 |
| Total samples | 24.070 |
| Split | 16.849 / 4.814 / 2.407 |
| Best method | sigmoid |
| Best mean calibration error | 7,0 |
| Sigmoid ROC-AUC | 0,6450 |
| Sigmoid Brier | 0,2335 |
| Isotonic ROC-AUC | 0,6456 |
| Isotonic Brier | 0,2333 |

Quan trọng: `periodic_recalibration.py` tạo artifact calibrated mới dạng:

```text
logs/meta_model_calibrated_periodic_*.joblib
```

nhưng runtime production vẫn resolve qua:

```text
config/model_artifacts.yaml -> logs/meta_model.joblib
```

Vì vậy periodic recalibration hiện nên được hiểu là **tạo ứng viên/calibration artifact để review**, không phải tự động thay production model.

### Continuous Learning Weekly

`main.py` schedule:

```text
Chủ Nhật 23:30 -> scripts/continuous_learning.py
```

Pipeline này:

1. Fetch OHLCV gần đây.
2. Mô phỏng/backtest để tạo labeled trades.
3. Train lại adaptive RF.
4. Dùng TimeSeriesSplit và holdout gate.
5. Nếu pass thì lưu production, nếu fail thì lưu challenger.

Đánh giá: đây là **offline retrain/backtest learning**, không phải continuous learning từ prediction runtime thật. Nó không khép vòng:

```text
prediction_id -> signal_id -> position_id -> closed outcome -> calibration
```

Đã sửa trong lần kiểm tra này:

- `scripts/train_adaptive.py`: thêm bootstrap `sys.path` để chạy CLI từ repo root không lỗi `ModuleNotFoundError`.
- `scripts/continuous_learning.py`: import `generate_labeled_trades` chắc hơn khi chạy như script hoặc import như module.

## 4. Adaptive RF

Artifact production:

| Thuộc tính | Giá trị |
|---|---|
| Model name | `adaptive_rf` |
| Version | `2026.07.07.1` |
| File | `logs/adaptive_model.joblib` |
| Metadata | `logs/adaptive_model.metadata.json` |
| Status | `production` |
| Schema | `adaptive-rf-v2` |
| Training dataset | `adaptive_signals_v2` |
| SHA256 | `5395280db76329ad16d79694ee2cc718fd47e22ce8c87ce18be8ac6449c5fbae` |
| Kích thước artifact | khoảng 0,73 MB |

Dữ liệu outcome:

| File | Records | WIN | LOSS | BREAKEVEN | Ghi chú |
|---|---:|---:|---:|---:|---|
| `logs/adaptive_signals.json` | 19.004 | 8.530 | 10.461 | 13 | runtime/adaptive outcomes |
| `logs/adaptive_signals_v2.json` | 24.070 | 11.413 | 12.657 | 0 | dataset v2 cho training/recalibration |

Điểm cần chú ý:

- `adaptive_signals.json` có outcome thật nhưng nhiều record không có stable `id`.
- `adaptive_signals_v2.json` dùng tốt cho training offline nhưng không phải runtime prediction audit; không nên coi nó là bằng chứng calibration live.

## 5. RL Exit Agent

Artifact hiện tại:

| Thuộc tính | Giá trị |
|---|---|
| Model name | `rl_exit` |
| Version | `2026.06.28.215012` |
| File | `logs/rl_models/production/rl_exit_ppo.zip` |
| Metadata | `logs/rl_models/production/metadata.json` |
| Status | `shadow` |
| Observation schema | `rl-exit-obs-v2` |
| Observation feature count | 20 |
| SHA256 | `ae894e5835b0e145d3bffc164e5d29500bea245d225b70aeef437de06cb3a489` |
| Promotion blocked | `true` |
| Reason | `underperforms_rule_baseline_and_observation_drift` |

RL Exit Shadow runtime:

| Metric | Giá trị |
|---|---:|
| Records | 1.540 |
| Có `position_id` | 1.540 |
| Completed outcome | 1.268 |
| Pending outcome | 272 |

Phân bố action:

| Action | Count |
|---|---:|
| HOLD | 1.162 |
| MOVE_SL_TO_BE | 195 |
| EXIT | 92 |
| TRAILING_SL_ATR | 71 |
| PARTIAL_CLOSE_50 | 20 |

Completed outcomes:

| Result | Count |
|---|---:|
| WIN | 601 |
| LOSS | 583 |
| BREAKEVEN | 84 |

Đánh giá: RL Exit Shadow có tracking outcome tốt hơn Meta prediction audit vì record nào cũng có `position_id`. Tuy nhiên artifact vẫn ở trạng thái `shadow` và bị block promotion, nên không nên bật active exit policy.

## 6. Prediction Audit Sau Khi Bỏ Prediction Shadow

Prediction Shadow legacy đã được bỏ để tránh trùng tác dụng với luồng chính.

Luồng chính hiện ghi:

```text
logs/prediction_audit/predictions_YYYY-MM-DD.jsonl
logs/prediction_audit/feature_snapshots_YYYY-MM-DD.jsonl
logs/meta_prob_entry_YYYY-MM-DD.log
```

Số liệu kiểm tra:

| Metric | Giá trị |
|---|---:|
| Prediction audit files | 3 |
| Total prediction records | 23.283 |
| Decision context | `entry` |
| Records có `signal_id` | 1 |
| Records có `position_id` | 0 |

Smoke test sau khi bỏ Prediction Shadow cho thấy một lần scoring tạo đúng:

```text
prediction_audit_delta = 1
feature_snapshot_delta = 1
meta_prob_entry_delta = 1
```

và không tạo lại:

```text
logs/shadow_predictions.json
logs/predictions_YYYY-MM-DD.log
```

Kết luận: Meta scoring/audit vẫn chạy đúng, nhưng chưa đủ traceability để calibration live.

## 7. Feature Importance

Hai nguồn importance đang tồn tại:

- `logs/meta_feature_importance.json`: importance của production meta feature set.
- `logs/feature_importance_v3.json`: importance của v3/advanced feature set, có nhóm cross-sectional/fractional-diff.

Top production features từ `logs/meta_feature_importance.json`:

| Hạng | Feature | Importance |
|---:|---|---:|
| 1 | `rsi` | 0,0608 |
| 2 | `rsi_score` | 0,0552 |
| 3 | `mtf_alignment` | 0,0526 |
| 4 | `distance_resistance_pct` | 0,0512 |
| 5 | `fear_greed` | 0,0432 |
| 6 | `macd_hist` | 0,0360 |
| 7 | `macd_score` | 0,0329 |
| 8 | `adx` | 0,0314 |
| 9 | `return_15m` | 0,0304 |
| 10 | `volume_acceleration` | 0,0303 |
| 11 | `roc_14` | 0,0276 |
| 12 | `ema_distance_zscore` | 0,0264 |
| 13 | `return_1d` | 0,0259 |
| 14 | `sentiment_momentum` | 0,0254 |
| 15 | `mfi` | 0,0250 |
| 16 | `distance_support_pct` | 0,0248 |
| 17 | `return_4h` | 0,0246 |
| 18 | `cmf` | 0,0235 |
| 19 | `roc_50` | 0,0234 |
| 20 | `choch_bull` | 0,0230 |

Nhóm tín hiệu quan trọng nhất vẫn là technical momentum, multi-timeframe alignment, price structure, volatility/volume và sentiment.

## 8. Điểm Mạnh

1. **Artifact governance tốt hơn trước**  
   Production artifacts resolve qua `config/model_artifacts.yaml`, metadata có SHA, schema, status. Hash hiện khớp cho `meta_model` và `adaptive_rf`.

2. **Prediction audit chính quy**  
   Prediction envelope ghi `prediction_id`, timestamp, artifact SHA, schema, feature hash, raw/calibrated prediction và feature snapshot để replay.

3. **Calibration trung tâm khá tốt**  
   Bucket `0.4-0.7` có sai số thấp, đây là vùng nhiều quyết định thực tế.

4. **RL Exit không bị bật active khi chưa đạt**  
   Model RL Exit ở `shadow`, có reason block rõ ràng.

5. **Continuous/recalibration jobs có guard cơ bản**  
   Có split theo thời gian, holdout, calibration error gate và challenger path.

## 9. Vấn Đề Và Rủi Ro

### P0 - Meta runtime outcome linkage chưa khép vòng

Prediction audit có 23.283 records nhưng:

```text
signal_id: 1
position_id: 0
order_id: 0
fill_id: 0
```

Trong khi đó closed outcomes có tồn tại ở adaptive logs. Tức là dữ liệu để tính calibration thật có ở hệ thống, nhưng chưa nối được về từng prediction. Đây là blocker lớn nhất cho mục tiêu calibrate bằng dữ liệu live.

### P0 - Không nên gọi continuous learning là live learning

`scripts/continuous_learning.py` là offline retraining bằng dữ liệu OHLCV/backtest gần đây. Nó hữu ích, nhưng không thay thế cho:

```text
prediction -> position -> close outcome -> calibration
```

Nếu tiếp tục gọi là continuous learning mà không nói rõ offline/backtest, dễ gây hiểu nhầm rằng model đang học từ live outcomes.

### P1 - Tail calibration chưa đủ evidence

Bucket `0.8-1.0` chỉ có 35 mẫu và sai số -15,7 điểm phần trăm. Không nên dùng vùng này để tăng size mạnh. Clamp sizing probability hiện là hợp lý.

### P1 - Periodic recalibration tạo artifact nhưng chưa có promotion flow rõ

`periodic_recalibration.py` tạo `meta_model_calibrated_periodic_*.joblib`, thậm chí có log auto-commit, nhưng runtime production vẫn dùng `logs/meta_model.joblib`. Cần phân biệt rõ:

- artifact candidate/calibrator để review
- artifact production thật

### P1 - Adaptive data có id/traceability chưa đồng nhất

`adaptive_signals.json` có nhiều outcome nhưng ít record có `id`. Điều này hạn chế việc join ngược với prediction/order/fill.

### P2 - Tài liệu cũ còn nhắc Prediction Shadow

Một số tab IDE vẫn mở file báo cáo Prediction Shadow cũ. File này đã được xóa khỏi repo theo yêu cầu, nhưng nếu IDE cache hiển thị thì cần đóng tab hoặc refresh workspace để tránh nhầm.

## 10. Đề Xuất Ưu Tiên

1. **Thêm Outcome Linker cho Meta prediction audit**
   - Khi tạo signal: sinh stable `signal_id`.
   - Khi mở position: lưu `signal_id`, `prediction_id`, `position_id`.
   - Khi đóng position: ghi outcome record có `prediction_id/signal_id/position_id/result/pnl_pct/hold_hours`.
   - Tạo dataset calibration từ join này.

2. **Đổi tên rõ hai cơ chế**
   - `RL Exit Shadow`: giữ nguyên cho exit policy shadow.
   - `Meta Prediction Audit`: thay cho Prediction Shadow cũ.
   - `Meta Outcome Linkage`: tên cho vòng calibration live cần bổ sung.

3. **Gating recalibration/promotion**
   - Periodic recalibration chỉ lưu candidate.
   - Chỉ promote khi có report, registry update, schema check, artifact hash và rollback path.

4. **Giữ clamp sizing probability cho đến khi runtime calibration đủ evidence**
   - Đặc biệt không tăng size dựa trên bucket `0.8-1.0`.

5. **Đánh dấu continuous learning là offline**
   - Trong docs/runbook nên ghi rõ: weekly continuous learning hiện là offline retrain/backtest, không phải live online learning.

## 11. Trạng Thái Tổng Hợp

| Hạng mục | Trạng thái |
|---|---|
| Meta Model production artifact | Tốt |
| Meta scoring runtime | Tốt |
| Prediction audit envelope | Tốt |
| Feature snapshot replay | Tốt |
| Meta outcome linkage | Chưa đạt |
| Runtime calibration từ live outcomes | Chưa đạt |
| Adaptive RF artifact | Tốt |
| Adaptive closed outcome data | Có, nhưng traceability chưa đồng nhất |
| RL Exit Shadow tracking | Khá tốt |
| RL Exit active readiness | Chưa đạt |
| Continuous learning weekly | Có, nhưng là offline/backtest learning |
| Periodic recalibration | Có, nhưng promotion flow cần rõ hơn |

## Kết Luận

Module ML đã có nền tảng production tốt hơn báo cáo cũ: artifact governance rõ, Meta prediction audit chính quy, RL Exit ở shadow có outcome tracking, và recalibration jobs đang chạy. Việc bỏ Prediction Shadow legacy là đúng vì tránh trùng tác dụng với luồng audit chính.

Tuy nhiên mục tiêu quan trọng nhất vẫn chưa hoàn tất: **calibrate Meta Model bằng dữ liệu runtime thật**. Muốn làm được, cần khép vòng tracking từ prediction tới closed outcome. Khi chưa có linkage này, các báo cáo calibration live không nên được suy ra từ prediction-only logs hoặc từ dataset offline.
