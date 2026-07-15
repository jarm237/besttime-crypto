# Live Entry Safety Remediation Plan — 2026-07-15

## Mục tiêu

Kế hoạch này xử lý khoảng trống còn lại trước khi cho phép hệ thống tự động vào lệnh live. Trọng tâm không phải retrain model ngay, mà là chứng minh pipeline đang truyền đúng dữ liệu, tính đúng edge/sizing, reject đúng các trường hợp biên và không bị race condition khi nhiều entry xuất hiện cùng lúc.

Kết luận vận hành hiện tại:

- Live gate Phase 5 đang fail-closed và phải tiếp tục đóng.
- Paper/shadow trading có thể tiếp tục.
- Live entry chưa được phép cho đến khi toàn bộ acceptance criteria bên dưới đạt.

## Nguyên tắc remediation

- `meta_probability`, Kelly, RR và final notional phải được tính từ cùng một `analysis` object xuyên suốt pipeline.
- Statistical edge có quyền phủ quyết cuối cùng đối với heuristic signal strength, dựa trên một công thức EV canonical duy nhất.
- Mọi reject phải có `decision_breakdown` đủ dữ liệu để replay.
- Guard phải được test độc lập, không chỉ dựa vào case bị chặn sớm bởi Phase 5 gate.
- Pre-trade check cho open positions/risk state phải có cơ chế atomic reservation trước khi submit order.
- Tách rõ signal eligibility và live authorization: một signal có thể đủ edge để ghi nhận paper/shadow nhưng vẫn không được gửi live vì Phase 5 gate, live flag hoặc kill switch.

## Phạm vi module

| Nhóm | Module chính |
| --- | --- |
| Signal/scoring | `btc_scraper/ml_engine/signal_score.py` |
| Auto-trade decision | `btc_scraper/trading/auto_trader.py` |
| Live guard | `btc_scraper/execution/live_execution_guard.py` |
| Hard risk limits | `btc_scraper/execution/hard_risk_limits.py` |
| Execution path | `btc_scraper/execution/execution_engine.py` |
| Position/exposure state | `btc_scraper/trading/position_tracker.py`, `btc_scraper/trading/exposure_manager.py` |
| Tests | `tests/test_auto_trader.py`, new execution guard/risk tests |

## Phase 0 — Freeze Live Entry And Capture Baseline

Priority: P0

Actions:

- Giữ `phase5_live_gate_closed` và live mode disabled cho entry orders.
- Chạy baseline paper/shadow hiện tại và lưu các mẫu signal có xung đột `STRONG BUY/SELL` nhưng `meta_confidence` thấp hoặc Kelly <= 0.
- Tạo fixture regression từ ít nhất 5 signal thật gần nhất, bao gồm case ngày 2026-07-15 có meta confidence khoảng 49%.

Acceptance criteria:

- Không có đường nào submit live entry khi Phase 5 gate đóng.
- Có artifact baseline gồm input analysis, `signal_score`, TP/SL, computed size và reject/pass result.
- Baseline không dùng confidence truyền thủ công tách rời pipeline.

## Phase 1 — End-To-End Decision Integrity

Priority: P0

Actions:

- Viết E2E test gọi cùng đường đi `evaluate_signal_score()` hoặc analysis đã có `signal_score` rồi đi qua `AutoTrader._process_signal()`.
- Không dùng test kiểu truyền trực tiếp `meta_confidence=0.9` vào `should_trade()` để kết luận toàn pipeline an toàn.
- Thêm fixture cho các case:
  - score/strength cao nhưng `meta_confidence` thấp;
  - Kelly <= 0;
  - RR <= minimum;
  - technical action khác action từ multi-agent/decision engine;
  - technical direction bị causal/regime hard veto;
  - feature schema hoặc direction encoding không nhất quán;
  - SELL và STRONG SELL với raw score thấp nhưng strength cao.

Required tests:

| Case | Expected |
| --- | --- |
| `STRONG BUY`, strength >= threshold, meta_probability < gate | skipped |
| `STRONG SELL`, strength >= threshold, action SELL | direction SHORT |
| action NEUTRAL dù raw text là BUY | skipped |
| Kelly <= 0 từ `signal_score` | skipped, không khởi tạo execution engine |
| RR <= minimum | skipped |
| confidence cao nhưng RR âm/zero | skipped |

Acceptance criteria:

- E2E tests dùng một analysis object duy nhất từ scoring đến sizing.
- Không có test an toàn nào dựa trên confidence synthetic trái với confidence thực tế.
- SELL/STRONG SELL pass/fail đối xứng với BUY theo strength, không theo raw score.
- Direction phải được suy ra từ signed directional score/action canonical, không từ `display_score`.

Signed score normalization target:

| Directional score | Strength | Action |
| ---: | ---: | --- |
| `+90` | `90` | BUY |
| `-90` | `90` | SELL |
| `+40` | `40` | NEUTRAL |
| `-40` | `40` | NEUTRAL |

## Phase 2 — Explicit Veto Rules

Priority: P0

Actions:

- Tạo quyết định canonical trước khi sizing/live guard:
  - `analysis -> build_entry_decision() -> live guard -> reservation -> submit`.
  - `should_trade()` chỉ là wrapper tương thích ngược, không chứa policy riêng tách khỏi quyết định canonical.
- Định nghĩa dataclass hoặc object tương đương:

```python
@dataclass(frozen=True)
class EntryDecision:
    eligible: bool
    action: TradeAction
    rejection_reason: str | None
    breakdown: DecisionBreakdown
    sizing: SizingDecision | None
```

- Chuẩn hóa enum cho action, status và reason; không dùng chuỗi tự do trong log/test/dashboard:

```python
class EntryRejectionReason(str, Enum):
    LOW_META_CONFIDENCE = "low_meta_confidence"
    INSUFFICIENT_STATISTICAL_EDGE = "insufficient_statistical_edge"
    RR_BELOW_MINIMUM = "rr_below_minimum"
    NON_POSITIVE_KELLY = "non_positive_kelly"
    ACTION_DISAGREEMENT = "action_disagreement"
    CAUSAL_REGIME_VETO = "causal_regime_veto"
    DIRECTION_ENCODING_INCONSISTENT = "direction_encoding_inconsistent"
    INVALID_SIZING_INPUT = "invalid_sizing_input"
```

- Tạo enum tương tự cho `AuthorizationReason`, `ReservationStatus`, `FinalDecisionStatus`, `TradeAction` và dùng chung `OrderIntent`.
- Chuẩn hóa policy phủ quyết trong `build_entry_decision()`:
  - `kelly_fraction <= 0` -> reject.
  - `meta_confidence < AUTO_TRADE_META_THRESHOLD` -> reject.
  - `rr1 <= AUTO_TRADE_MIN_RR` -> reject.
  - `signal_score.action not in {BUY, SELL}` -> reject.
  - technical action khác action từ multi-agent/decision engine -> reject hoặc shadow-only theo config.
  - technical direction bị causal/regime hard veto -> reject hoặc shadow-only theo config.
  - feature schema hoặc direction encoding không nhất quán -> reject.
- Thêm `AUTO_TRADE_MIN_RR`, mặc định đề xuất `1.0` hoặc cao hơn nếu cost/slippage yêu cầu.
- Thêm `AUTO_TRADE_MIN_EXPECTED_EDGE`, mặc định đề xuất `0.0` hoặc cao hơn nếu muốn margin an toàn.
- Dùng một công thức expected edge canonical:

```text
gross_ev = p_win * reward_ratio - (1 - p_win)

net_ev = gross_ev
         - estimated_fee_ratio
         - estimated_slippage_ratio
         - estimated_funding_cost
```

- Veto dựa trên `net_ev <= AUTO_TRADE_MIN_EXPECTED_EDGE`; Kelly được log riêng và không phải nguồn EV duy nhất.
- Định nghĩa rõ precedence: hard safety > live gate > kill switch > state/risk > statistical edge > heuristic strength > execution quality.

Acceptance criteria:

- Mọi veto trả về lý do ổn định, ví dụ `insufficient_statistical_edge`, `low_meta_confidence`, `rr_below_minimum`, `action_disagreement`, `causal_regime_veto`, `direction_encoding_inconsistent`.
- Nếu meta model chỉ dự báo `P(win | proposed trade)`, confidence thấp dùng reason `insufficient_statistical_edge`, không gọi là directional disagreement.
- Không có order nào được tạo nếu `net_expected_value <= AUTO_TRADE_MIN_EXPECTED_EDGE`.
- Log/test/dashboard chỉ dùng enum values từ canonical decision types.

## Phase 3 — Decision Breakdown Logging

Priority: P1

Actions:

- Thêm `decision_breakdown` vào skip log và order log trong `AutoTrader._process_signal()`.
- Log từng bước sizing theo thứ tự:
  - `technical_score`
  - `directional_score`
  - `signal_strength`
  - `signal_action`
  - `meta_probability`
  - `rr_ratio`
  - `gross_expected_value`
  - `estimated_cost`
  - `net_expected_value`
  - `kelly_raw`
  - `kelly_applied`
  - `risk_pct_applied`
  - `risk_notional`
  - `size_before_caps`
  - `var_cap`
  - `exposure_cap`
  - `max_trade_cap`
  - `min_notional`
  - `final_notional`
  - `rejection_reason`

Example target shape:

```json
{
  "technical_score": 96,
  "signal_strength": 96,
  "signal_action": "BUY",
  "meta_probability": 0.49,
  "rr_ratio": 1.55,
  "gross_expected_value": -0.02,
  "estimated_cost": 0.001,
  "net_expected_value": -0.021,
  "kelly_raw": -0.01,
  "kelly_applied": 0.0,
  "final_notional": 0.0,
  "rejection_reason": "insufficient_statistical_edge"
}
```

Acceptance criteria:

- Với mọi skipped/rejected/filled decision đều replay được từ log.
- Log phân biệt rõ `raw directional score`, `side-agnostic strength`, `display score` và `action`.
- Không còn trường hợp skip chỉ có reason text nhưng thiếu số liệu quyết định.
- Decision log phân biệt được:
  - `signal_eligible`;
  - `live_authorized`;
  - `final_status`;
  - `eligibility_reason`;
  - `authorization_reason`.

Authorization log target:

```json
{
  "signal_eligible": true,
  "live_authorized": false,
  "final_status": "rejected",
  "eligibility_reason": null,
  "authorization_reason": "phase5_gate_closed"
}
```

## Phase 4 — Guard Matrix Boundary Tests

Priority: P1

Actions:

- Tạo test riêng cho `LiveExecutionGuard` với Phase 5 mở giả lập để các guard phía sau được chạy.
- Tạo test riêng cho `HardRiskLimits` ở boundary exact limit, just below, just above.
- Mock live mode flag, kill switch, rollout stage, system health và execution risk.

Required matrix:

| Case | Expected |
| --- | --- |
| Phase 5 closed | reject `phase5_gate` |
| Phase 5 open, live flag missing/disabled | reject `live_mode_flag` |
| kill switch active/tripped for entry | reject `kill_switch` |
| kill switch inactive for entry | continue to next guard |
| rollout stage 1 already has open position | reject `rollout_stage` |
| daily loss breach | reject `hard_risk_limits` |
| rolling 24h loss breach | reject `hard_risk_limits` |
| max orders per day reached | reject `hard_risk_limits` |
| open positions >= max | reject `hard_risk_limits` |
| notional > max single order | reject `hard_risk_limits` |
| notional > max position | reject `hard_risk_limits` |
| stale/unready system health | reject `system_health` |
| stale account/market/model/orderbook state | reject specific freshness reason |
| excessive spread/slippage/latency | reject `execution_risk` |
| EXIT/REDUCE/EMERGENCY_EXIT while kill switch blocks entries | allowed to reduce or close risk, except forced global halt policy |

Acceptance criteria:

- Mỗi guard có ít nhất một unit test chứng minh reject reason và `blocked_by`.
- Tests không bị che bởi Phase 5 gate chạy sớm.
- EXIT/REDUCE/EMERGENCY_EXIT behavior được test riêng để tránh block đóng vị thế.
- Freshness guard có reason riêng, ví dụ `stale_account_state`, `stale_market_data`, `stale_model_features`, `stale_orderbook`.

## Phase 5 — Atomic State And Reservation

Priority: P1

Actions:

- Thiết kế pre-trade reservation cho entry orders:
  - acquire lock;
  - refresh equity/open positions/daily order count;
  - calculate entry decision and size;
  - validate all limits;
  - reserve pending order slot, pending notional, symbol exposure, portfolio exposure, daily order quota, risk budget và rollout-stage slot;
  - release lock;
  - submit order;
  - release/commit reservation theo kết quả fill/reject.
- Không dựa chỉ vào snapshot `open_positions_count` truyền vào `OrderContext`.
- Reservation có TTL để tự giải phóng nếu process crash.
- Thêm idempotency key ổn định cho reservation và exchange submit:
  - `entry_decision_id`;
  - `signal_id`;
  - `symbol`;
  - `side`;
  - `strategy`;
  - `decision_timestamp_bucket`.
- Dùng idempotency key làm `client_order_id` hoặc mapping tương đương để retry không tạo lệnh thứ hai.
- Partial fill phải commit theo phần đã fill, không commit toàn bộ hoặc rollback toàn bộ:

```text
reserved_notional = 100
filled_notional = 40
remaining_reservation = 60
```

- Phần `remaining_reservation` được giữ cho đến khi order hoàn tất, bị cancel hoặc TTL/reconciliation xác nhận order không còn tồn tại trên exchange.
- Thêm concurrency test với 3 entry song song khi `max_open_positions = 3` và đang có 2 vị thế.
- Thêm test cho submit timeout, retry, process restart/recovery và signal replay.

Idempotent submit flow:

```text
EntryDecision
→ reservation
→ client_order_id/idempotency_key
→ exchange submit
→ reconcile result
```

Reservation target shape:

```json
{
  "reservation_id": "...",
  "entry_decision_id": "...",
  "idempotency_key": "...",
  "symbol": "BTC/USDT",
  "reserved_notional": 20,
  "reserved_position_slots": 1,
  "expires_at": "...",
  "status": "pending"
}
```

Acceptance criteria:

- Trong test cạnh tranh, chỉ một trong ba entry được reserve/submit.
- Reservation được rollback nếu submit bị reject hoặc lỗi.
- Reservation hết hạn được cleanup và không giữ quota vĩnh viễn sau crash/timeout.
- Retry sau timeout hoặc restart không tạo duplicate order nếu exchange đã nhận order trước đó.
- Nếu reservation expired nhưng order thực tế vẫn tồn tại trên exchange, reconciliation phải commit hoặc close out theo runbook thay vì tạo order mới.
- Partial fill cập nhật local state, reserved notional và remaining reservation đúng với exchange fill state.
- Audit log có `reservation_id` hoặc equivalent trace id.

## Phase 6 — Sizing Edge Cases

Priority: P1

Actions:

- Refactor sizing để trả về object chi tiết thay vì chỉ `float`, ví dụ `SizingDecision`.
- Reject thay vì fallback nguy hiểm cho:
  - `entry_price <= 0`;
  - `sl_price <= 0`;
  - `stop_distance` quá nhỏ;
  - `rr_ratio <= 0`;
  - `ATR` hoặc volatility input missing nếu strategy yêu cầu;
  - `min_notional > risk_based_notional` mà việc nâng size làm vượt risk cap.
- Kiểm tra thứ tự cap: risk-based size -> Kelly/fractional Kelly -> VaR -> exposure -> hard max -> exchange rounding -> min notional validation.

Acceptance criteria:

- Không có path nào biến dữ liệu thiếu SL thành lệnh min notional mặc định.
- Nếu size sau cap < min notional thì reject, không tự nâng size vượt risk cap.
- Unit tests bao phủ `stop_distance ~= 0`, `price = 0`, `sl = entry`, `min_notional` lớn hơn size hợp lệ.

## Phase 7 — Paper Fill Evidence Before Live

Priority: P2

Actions:

- Chạy shadow/paper liên tục và dùng mốc 7 ngày hoặc 50 paper fills chỉ làm intermediate checkpoint, không dùng để mở live gate.
- Để mở Phase 5 live gate, phải đồng thời đạt:
  - tối thiểu 14 ngày validation;
  - tối thiểu 10 trading days có phát sinh giao dịch;
  - ít nhất 100 real paper fills hợp lệ;
  - có phân bố symbol, regime và order type;
  - synthetic/debug fills không được tính.
- So sánh predicted vs actual:
  - win rate theo calibration bucket;
  - realized RR;
  - slippage;
  - rejected reason distribution;
  - model confidence tail behavior.
- Tạo promotion report cho Phase 5 gate.

Acceptance criteria:

- Calibration bucket không có tail lệch nghiêm trọng.
- Không có rejected reason bất thường do schema/missing fields.
- Paper fills chứng minh final notional, guard result và post-trade state nhất quán.
- Promotion report loại trừ synthetic/debug fills và ghi rõ coverage theo symbol/regime/order type.

## Definition Of Done

Live entry chỉ được xem xét mở khi tất cả điều kiện sau đạt:

- P0 và P1 hoàn tất, test xanh.
- `decision_breakdown` có mặt trong mọi decision.
- Guard matrix và sizing edge tests pass.
- Concurrency/reservation test pass.
- Paper evidence đạt threshold Phase 5.
- Có rollback procedure: tắt live flag, arm kill switch, disable auto-trade env.
- Mọi live entry có `decision_id`, `reservation_id`, `idempotency_key`, `model_version`, `artifact_hash` và `feature_schema_version`.
- Có reconciliation test chứng minh local state khớp exchange state sau timeout, restart và partial fill.
- Không có policy entry bị duplicate giữa `signal_score.py`, `auto_trader.py` và execution guard.

## Trạng Thái Vận Hành Trong Remediation

Giữ cấu hình vận hành ở trạng thái fail-closed trong suốt quá trình triển khai:

```env
LIVE_TRADING_ENABLED=false
PHASE5_LIVE_READINESS_GATE=false
RL_EXIT_MODE=shadow
RL_EXIT_ALLOW_LIVE_ACTION=false
```

Paper/shadow có thể tiếp tục để thu baseline và regression fixtures, nhưng chưa mở live entry. Không cần retrain model trước khi hoàn tất P0/P1; chỉ cân nhắc retrain sau khi decision log đủ tin cậy.

## Gợi ý thứ tự PR

1. Canonical decision types: `EntryDecision`, `DecisionBreakdown`, `SizingDecision`, enum reject/authorization/status reasons, signed score normalization và unit tests.
2. Decision integrity: `build_entry_decision()`, EV canonical, explicit veto rules, bỏ duplicate policy khỏi `should_trade()` và E2E tests.
3. Traceability: decision logging, model/schema/artifact metadata, eligibility vs authorization và replay fixtures.
4. Guard verification: guard matrix, freshness guards, entry versus exit intent và boundary tests.
5. Atomic reservation: reservation store, lock, TTL cleanup, idempotent submit, concurrency/restart/replay tests.
6. Paper evidence gate: real-paper classification, coverage report, calibration/rejection metrics và Phase 5 promotion report.
