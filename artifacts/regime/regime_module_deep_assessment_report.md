# Báo cáo đánh giá chuyên sâu và remediation module Regime

**Ngày báo cáo:** 2026-07-30  
**Phạm vi:** `btc_scraper/regime`, detector, decision engine, feature engineering, position lifecycle, world state, backtesting, tuner, dashboard và evidence pipeline  
**Trạng thái kết luận:** `NOT_READY_FOR_PRODUCTION_ENFORCEMENT`  
**Runtime mode khuyến nghị:** `observe`

---

## 1. Tóm tắt điều hành

Module Regime trước remediation tồn tại một số lỗi semantic và integration có khả năng làm sai quyết định giao dịch:

- ATR phần trăm bị so sánh với threshold của ADX.
- ADX mất index khi chạy với `DatetimeIndex`.
- Nhánh regime quan trọng gần như không thể đạt được.
- Direction policy có thể xử lý bearish regime như bullish.
- Các consumer đọc config từ nhiều đường dẫn khác nhau.
- Regime bị mất hoặc trở thành `null` trong vòng đời position và outcome.
- Feature transition có nguy cơ rò rỉ giữa các coin.
- Backtest sử dụng sai đơn vị ATR và không mô tả rõ same-candle ambiguity.
- Tuner cũ tối ưu tuyến tính, dễ chọn multiplier ở biên mà không có bằng chứng holdout.

Remediation đã sửa các lỗi code trọng yếu, tạo canonical contract v2, bổ sung containment và rebuild các artifact nghiên cứu. Tuy nhiên, hệ thống chưa có đủ native post-remediation evidence và control/shadow validation để bật ảnh hưởng regime trong production.

Quyết định hiện tại:

```text
REJECT_ENFORCEMENT_KEEP_OBSERVE
```

---

## 2. Kiến trúc module sau remediation

### 2.1 Canonical Regime Contract

Contract mới tách rõ các chiều semantic:

- `regime_id`
- `family`
- `direction`
- `volatility`
- `liquidity`
- `confidence`
- `observed_at`
- `input_end_time`
- `source_timeframe`
- `detector_version`
- `taxonomy_version`
- `mapping_version`
- `mapping_quality`
- `config_sha256`
- `warmup_complete`
- `confidence_method`

Định nghĩa canonical nằm tại:

```text
btc_scraper/regime/contract.py
```

Mọi legacy label được xử lý qua mapping table chính xác. Các mapping mơ hồ như `STRONG_TREND`, `BREAKOUT` hoặc `HIGH_VOLATILITY` được đánh dấu `LOSSY` hoặc `INCOMPLETE`, thay vì tự suy đoán direction.

### 2.2 Config và containment

Nguồn config canonical:

```text
btc_scraper/regime/regime_config.json
```

Resolver duy nhất:

```text
btc_scraper/regime/config.py
```

Các thuộc tính an toàn:

- Validate schema và threshold relationship.
- Hash config bằng SHA-256.
- Atomic write bằng temporary file, `fsync` và `os.replace`.
- Ghi audit record khi cập nhật.
- Missing config trong `observe` hoặc `shadow_effect` chuyển sang safe defaults không thực thi.
- Missing config trong `enforce` fail closed.

Containment:

- Mặc định `REGIME_RUNTIME_ENFORCEMENT_MODE=observe`.
- `shadow_effect` không thể thay đổi quyết định thật.
- `enforce` vẫn không đủ để bật effect.
- Cần thêm `REGIME_PROMOTION_APPROVED=true`.
- Chỉ đúng một effect được phép bật trong một rollout:
  - decision weight;
  - position sizing;
  - TP/SL.
- Nếu nhiều effect cùng được yêu cầu, tất cả fail-safe về disabled.

---

## 3. Đánh giá detector

### 3.1 Các lỗi đã sửa

| Vấn đề | Trước remediation | Sau remediation |
|---|---|---|
| ATR semantics | ATR% so với ADX threshold | Threshold ATR% riêng |
| ADX index | Có thể lệch `RangeIndex`/`DatetimeIndex` | Giữ nguyên index đầu vào |
| Warm-up | Có thể phân loại confident quá sớm | Trả `UNKNOWN` và `INSUFFICIENT_HISTORY` |
| NaN | Có nguy cơ bị neutralize ngầm | Fail-visible |
| Confidence | Giá trị cố định theo branch | Khoảng cách tới threshold |
| Direction | Breakout không có polarity rõ | `BREAKOUT_BULL` và `BREAKOUT_BEAR` |
| Flip control | Không có | Minimum duration 3 bars |

### 3.2 Input guardrails

Detector kiểm tra:

- OHLC thiếu hoặc không hợp lệ;
- NaN và infinite;
- giá bằng 0 hoặc âm;
- `high < low`;
- timestamp trùng;
- timestamp không tăng đơn điệu;
- timeframe không hỗ trợ;
- ADX ngoài `[0, 100]`;
- ATR% âm hoặc vượt maximum hợp lệ.

### 3.3 Hysteresis và duration

Candidate regime mới chỉ được xác nhận sau khi tồn tại đủ:

```text
minimum_duration_bars = 3
```

Trong thời gian chờ:

- regime hiện tại được giữ nguyên;
- raw candidate vẫn được lưu để quan sát;
- confidence được decay;
- output đánh dấu `hysteresis_applied`.

---

## 4. Các điểm tích hợp

### 4.1 Analysis core

`btc_scraper/analysis/core.py`:

- Tạo canonical snapshot cho từng candle.
- Áp dụng warm-up và stabilization trên chuỗi candle.
- Lưu riêng raw regime và stabilized regime.
- TP/SL luôn tính proposed scale.
- Trong `observe` và `shadow_effect`, applied scale luôn bằng `1.0`.

### 4.2 Decision engine

`btc_scraper/ml_engine/decision_engine.py`:

- Thay substring matching bằng exact truth table.
- Sửa direction support cho `STRONG_TREND_BEAR`.
- Định nghĩa explicit policy cho `PANIC_SELL` và `PUMP_RISK`.
- Tách proposed regime weight và applied regime weight.
- Applied weight bằng `0` nếu containment chưa cho phép.

### 4.3 Position sizing và signal score

`btc_scraper/ml_engine/signal_score.py`:

- Đọc config từ resolver canonical.
- Lưu proposed multiplier riêng.
- Applied multiplier bằng `1.0` khi effect disabled.
- Gắn snapshot, config hash và effect reason vào output.
- Missing config ở non-enforcement mode không làm tăng risk.

### 4.4 Position lifecycle

`btc_scraper/trading/position_tracker.py` và `auto_trader.py`:

- Snapshot tại entry được lưu immutable.
- Position lưu family, direction, volatility, confidence, detector version, taxonomy version và config hash.
- Khi cùng một `position_id` nhận snapshot khác, record bị quarantine bằng lỗi:

```text
CONFLICTING_REGIME_SNAPSHOT_QUARANTINED
```

- Close position giữ nguyên entry snapshot, không thay bằng regime tại exit.

### 4.5 Outcome và adaptive evidence

`btc_scraper/ml_engine/adaptive_scoring.py`:

- Outcome attribution sử dụng entry snapshot.
- Không còn ghi regime `null`; thiếu lineage được biểu diễn bằng `UNKNOWN`.
- Native và backfilled evidence được phân biệt.

Historical backfill:

- Không suy luận regime từ PnL hoặc kết quả thắng/thua.
- Không tạo prediction probability từ outcome.
- Backfilled evidence không đủ điều kiện promotion.

### 4.6 World state

`btc_scraper/core/world_state.py` và `main.py`:

- Tách `technical_regime` khỏi macro `risk appetite`.
- Missing hoặc neutral signal không còn mặc định thành `RISK_OFF`.
- Chỉ BUY/SELL action rõ ràng mới map sang `RISK_ON`/`RISK_OFF`.

### 4.7 Feature engineering

`btc_scraper/feature_engineering/regime_features.py`:

- Sort theo coin và thời gian trước khi tính feature.
- Duration và transition được group theo coin.
- Không có transition từ coin này sang coin khác.
- Không sử dụng signal confidence thay cho regime confidence.
- Missing confidence có indicator riêng.
- `UNKNOWN` được giữ nguyên, không map sang trend mặc định.
- Mapping version và taxonomy version được lưu trong artifact.

### 4.8 Backtesting

`btc_scraper/backtesting/engine.py`:

- Chuyển ATR% thành price distance đúng:

```text
atr_price = price × atr_percent / 100
```

- Same-candle ambiguity có policy explicit:
  - `CONSERVATIVE_SL_FIRST`
  - `OPTIMISTIC_TP_FIRST`
  - `AMBIGUOUS_EXCLUDE`
  - `LOWER_TIMEFRAME_REPLAY`
- Trade record tách:
  - `economic_win`;
  - `target_hit_win`;
  - `timeout_profitable`.

### 4.9 Tuner

`btc_scraper/regime/regime_tuner.py`:

- Chronological train/validation/holdout.
- Embargo giữa các split.
- Minimum sample theo regime.
- Transaction cost, drawdown, turnover, instability và shrinkage penalties.
- Bootstrap confidence interval.
- Sparse hoặc unknown regime fallback về multiplier `1.0`.
- Artifact immutable và luôn `RESEARCH_ONLY`.

### 4.10 Dashboard và calibration

Dashboard expose:

- runtime mode;
- detector health;
- config health;
- config hash;
- detector/taxonomy version;
- trạng thái từng effect.

Config update qua dashboard và calibrator sử dụng atomic write và yêu cầu restart.

---

## 5. Bằng chứng historical before/after

Nguồn:

- 21 CSV;
- 2.570.232 nến sau warm-up;
- combined source SHA-256:

```text
1074112ecb2dcc1060bb397aab9ee07ad5399d4ee7b2bc3910bc995e24c97d2a
```

### 5.1 So sánh tổng quan

| Metric | Before | After |
|---|---:|---:|
| Rows | 2.570.232 | 2.570.232 |
| Unknown rate sau warm-up | 0% | 0% |
| Transition frequency | 10,0088% | 6,4332% |
| Average duration | 9,9912 bars | 15,5443 bars |

### 5.2 Phân phối after remediation

| Regime | Tỷ lệ |
|---|---:|
| RANGING | 26,0526% |
| COMPRESSION | 25,6194% |
| MEAN_REVERSION | 24,8168% |
| WEAK_TREND_BULL | 4,3112% |
| WEAK_TREND_BEAR | 3,8722% |
| WEAK_TREND | 2,9232% |
| STRONG_TREND_BULL | 2,5149% |
| STRONG_TREND_BEAR | 2,3276% |
| PUMP_RISK | 2,3629% |
| STRONG_TREND | 1,8755% |
| BREAKOUT_BULL | 1,4303% |
| BREAKOUT_BEAR | 1,3394% |
| PANIC_SELL | 0,5540% |

Nhận xét:

- Không regime nào chiếm gần 100%.
- Các branch breakout, extreme, weak trend và mean reversion đều có quan sát.
- Bull/bear distribution tương đối cân đối ở các branch directional.
- Minimum-duration làm giảm flip rate khoảng 35,7%.

---

## 6. Feature và tuning evidence

### 6.1 Feature artifact v2

- Rows: `24.070`
- Columns: `100`
- Output SHA-256:

```text
5ef9f158b34b1b51353d50c11baad7dc585999036a3f8b1ac5b8f4d745e1e091
```

- Rebuild lần hai tạo cùng SHA-256: byte-for-byte reproducible.
- `UNKNOWN`: 3.443 rows.
- Missing regime confidence: 24.070 rows.

Missing confidence 100% là thuộc tính của nguồn legacy, không phải detector v2. Artifact được đánh dấu `RESEARCH_ONLY`.

### 6.2 Tuning evidence

Tuner chỉ tìm được:

```text
train      = 9
validation = 2
holdout    = 3
```

Timestamp coverage không đầy đủ. Regime hợp lệ không đủ mẫu, do đó:

```text
selected_multiplier = 1.0
status = INSUFFICIENT_EVIDENCE
promotion_gate_passed = false
```

Đây là hành vi an toàn mong muốn.

---

## 7. Kiểm thử và chất lượng

- Regression suite: `114` tests pass.
- Remediation-specific suite: `42` tests pass.
- Python compile check: pass.
- `git diff --check`: pass.
- Feature artifact reproducibility: pass.

Nhóm test bao phủ:

- ATR unit và threshold semantics;
- ADX index alignment;
- warm-up và NaN handling;
- detector determinism;
- bull/bear symmetry;
- hysteresis và minimum duration;
- shadow non-execution;
- promotion và single-effect enforcement;
- config degradation/fail-closed;
- exact direction truth table;
- immutable entry snapshot;
- cross-coin feature isolation;
- same-candle backtest policy;
- walk-forward tuner và immutable artifact.

Cảnh báo còn lại là warning có sẵn của sklearn về feature names, không phải lỗi Regime.

---

## 8. Gate assessment

| Gate | Trạng thái | Nhận định |
|---|---|---|
| A — Code safety | PASS | Containment, mapping, ATR và ADX đã được sửa và test. |
| B — Contract readiness | PASS | Contract, config/hash, lifecycle snapshot và world state đã sẵn sàng. |
| C — Evidence readiness | PARTIAL | Code lineage đã có nhưng chưa đủ native post-remediation evidence. |
| D — Research readiness | PARTIAL | Feature/backtest/tuner đã sửa nhưng holdout chưa đủ. |
| E — Shadow readiness | BLOCKED | Chưa có control/shadow parity window và native outcomes đủ lớn. |
| F — Production enforcement | BLOCKED | Chưa có rollback drill và phê duyệt riêng từng effect. |

---

## 9. Rủi ro còn lại

### Cao

1. Chưa có native prediction → decision → position → outcome dataset đủ lớn sau remediation.
2. Chưa chạy control/shadow trên cùng input cutoff.
3. Chưa có promotion artifact được owner phê duyệt.
4. Chưa kiểm chứng rollback trong runtime production.

### Trung bình

1. Historical confidence không thể phục hồi đáng tin cậy từ legacy logs.
2. Slippage chưa được model riêng trong tuning artifact.
3. Lower-timeframe replay chưa có dữ liệu để giải quyết same-candle ambiguity.
4. Threshold v2 mới được xác nhận bằng distribution guardrail, chưa được chứng minh cải thiện economic outcome.

### Thấp

1. Warning sklearn về feature names.
2. Một số legacy taxonomy chỉ có mapping lossy/incomplete và phải tiếp tục được đánh dấu rõ.

---

## 10. Kế hoạch tiếp theo đề xuất

### Bước 1 — Native evidence collection

Giữ `observe`, thu thập tối thiểu:

- canonical prediction snapshot;
- proposed/applied decision;
- immutable entry snapshot;
- execution details;
- economic outcome;
- config, detector, taxonomy và model hashes.

### Bước 2 — Non-executing shadow

Chạy control và shadow trên:

- cùng candles;
- cùng timestamp cutoff;
- cùng model/config ngoài regime;
- không gửi shadow order.

Theo dõi:

- disagreement rate;
- proposed risk change;
- expected PnL;
- drawdown;
- turnover;
- regime null/unknown rate;
- lineage completeness.

### Bước 3 — Holdout research

Chỉ tune khi:

- timestamp coverage đầy đủ;
- đủ sample theo từng regime;
- có cost và slippage assumptions;
- bootstrap interval hợp lệ;
- holdout improvement dương và ổn định.

### Bước 4 — Controlled rollout

Thứ tự đề xuất:

```text
risk-reduction-only
→ rollback verification
→ limited decision weight
→ limited sizing
→ TP/SL review riêng
```

Không bật đồng thời nhiều effect trong rollout đầu.

---

## 11. Kết luận

Remediation đã đưa module Regime từ trạng thái semantic không đáng tin cậy sang trạng thái code-safe và research-capable:

- contract rõ ràng;
- detector có guardrail;
- config thống nhất;
- lifecycle attribution đúng;
- feature leakage được loại bỏ;
- backtest và tuner có semantics an toàn;
- containment ngăn việc bật effect ngoài quy trình promotion.

Tuy vậy, độ đúng của code không thay thế được bằng chứng kinh tế. Do thiếu native shadow evidence và holdout hợp lệ, module phải tiếp tục chạy ở:

```text
REGIME_RUNTIME_ENFORCEMENT_MODE=observe
```

Cho tới khi Gate E và Gate F được hoàn tất, không nên bật regime-aware decision weighting, position sizing hoặc TP/SL trong production.
