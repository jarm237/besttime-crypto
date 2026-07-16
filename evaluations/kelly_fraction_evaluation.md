# Báo Cáo Đánh Giá Module Kelly Fraction

Ngày đánh giá: 2026-07-16

## Tóm Tắt Điều Hành

Module Kelly fraction hiện **có giá trị như một risk gate và edge diagnostic**, nhưng **chưa nên được xem là module position sizing optimizer**.

Vấn đề chính không nằm ở công thức Kelly. Công thức cơ bản đang đúng, nhưng pipeline phía sau làm Kelly gần như không thay đổi exposure của các lệnh đã vượt qua gate:

```text
Kelly được tính
    -> Kelly dùng để chặn lệnh âm
    -> Sizing lại ưu tiên meta_prob
    -> Regime multiplier áp dụng
    -> Floor position_size = 0.25
    -> Hầu hết lệnh có cùng size
```

Do đó kết quả backtest/sweep kiểu `Kelly enabled == Kelly disabled` không bất ngờ. Với implementation hiện tại, bật/tắt Kelly chủ yếu ảnh hưởng **trade selection**, chưa ảnh hưởng rõ đến **capital allocation**.

## Kết Luận Kỹ Thuật

Nên phân loại Kelly hiện tại là:

| Vai trò | Đánh giá |
|---|---|
| Risk gate | Có tác động rõ ràng |
| Edge diagnostic | Có giá trị để log và phân tích |
| Capital sizing | Chưa thực sự hoạt động |
| PnL optimizer | Chưa có bằng chứng |

Số liệu hiện có cho thấy Kelly chặn nhiều lệnh, nhưng chưa chứng minh chắc các lệnh bị chặn thật sự có EV âm. Backtest representative còn cho thấy nhóm `Kelly = 0` tạo phần lớn PnL, dù mẫu chỉ có 18 trade nên chưa đủ để kết luận gate đang gây hại.

Rủi ro chính:

> Kelly có thể đang dùng probability hoặc payoff estimate chưa phù hợp, dẫn đến chặn lệnh tốt thay vì chỉ chặn lệnh EV âm.

## Bằng Chứng Hiện Có

Từ `logs/meta_prob_entry_2026-07-*.log`:

- Tổng dòng phân tích: `78.247`
- Có `meta_prob`: `59.603`
- Kelly dương: `22.941` dòng, khoảng `38,49%`
- Kelly bằng 0: `36.662` dòng, khoảng `61,51%`
- Kelly trung bình: `0,0734`
- Median Kelly: `0,0`
- P90 Kelly: `0,2651`
- Max Kelly: `0,5`
- `position_size == 0.25`: `98,78%`

Từ `btc_scraper/logs/auto_trade_log.json`:

- Tổng entry: `666`
- Skipped: `433`
- Skip do Kelly âm/0: `342`
- Kelly là lý do skip lớn nhất trong log hiện tại.

Từ `logs/backtest_trades_baseline_20260621T125920.csv`:

- Tổng trade: `18`
- Win rate: `77,78%`
- Tổng PnL: `235,816`
- Trade Kelly dương: `8`, PnL `10,2511`
- Trade Kelly bằng 0: `10`, PnL `225,565`
- `position_size` toàn bộ backtest: `0,25`

Từ `logs/regime_sweep_kelly_by_strategy_tuned_latest.json`:

- `total_enabled = -13.063`
- `total_disabled = -13.063`
- `delta_total = 0.0`

## Hiện Trạng Implementation

### Công thức Kelly

`compute_kelly_fraction()` đang dùng công thức chuẩn:

```python
k = (p * b - (1 - p)) / b
```

Tham chiếu: `btc_scraper/ml_engine/signal_score.py`.

### Sizing trong signal score

Sau khi Kelly được tính, sizing hiện lại ưu tiên `meta_prob`:

```python
prob_factor = meta_prob if meta_prob is not None else (kelly if kelly is not None else 1.0)
```

Điều này làm `kelly_fraction` chủ yếu trở thành gate/diagnostic, không phải driver sizing chính.

### Floor position size

Regime sizing đang ép floor:

```python
pos_size = round(max(0.25, min(1.0, pos_size * float(mult))), 2)
```

Floor này làm hầu hết signal yếu, uncertainty cao hoặc Kelly nhỏ đều bị kéo về cùng mức `0.25`. Kết quả là sizing distribution bị bóp méo và A/B sizing khó có ý nghĩa.

### AutoTrader Kelly gate

`AutoTrader` reject khi `kelly_fraction <= 0`:

```python
if self.use_kelly and kelly_raw_val is not None and kelly_raw_val <= 0.0:
    return _reject(...)
```

Gate này có tác động thực tế mạnh, nhưng cần kiểm chứng thêm bằng counterfactual replay trước khi xem là production-grade EV gate.

## Vấn Đề Chính

### P0 - Kelly chưa phải sizing engine

Không nên nói Kelly đang tối ưu position size khi exposure sau cùng gần như không thay đổi. Với `position_size == 0.25` ở `98,78%` log, module chưa tạo được phân bổ vốn theo edge.

### P0 - Semantic của `position_size` chưa rõ

`position_size` đang vừa giống multiplier, vừa được hiểu như size/risk signal. Nên tách field:

```text
kelly_fraction_raw
kelly_fraction_scaled
risk_fraction
position_multiplier
recommended_notional_usdt
final_notional_usdt
```

### P0 - Config path có nguy cơ sai và fallback im lặng

File config thật nằm ở:

```text
btc_scraper/regime/regime_config.json
```

Trong khi loader hiện tìm các path khác. Nếu không tìm thấy config, code fallback về default mà không log rõ. Điều này khiến backtest và production có thể dùng tham số khác kỳ vọng.

Loader nên fail rõ hoặc fail-closed:

```python
{
    "kelly_enabled": False,
    "kelly_status": "CONFIG_NOT_FOUND",
    "kelly_fraction": None,
}
```

Mỗi decision nên log config metadata:

```python
"kelly_config": {
    "path": ".../btc_scraper/regime/regime_config.json",
    "version": "2026-07-16",
    "hash": "...",
    "max_fraction": 0.7,
    "scale": 0.2
}
```

### P1 - Kelly gate đang thay thế EV gate

`kelly_fraction <= 0` chỉ là bằng chứng EV âm nếu:

- `p(win)` đã calibration tốt;
- `b = AvgWin / AvgLoss` phản ánh realized payoff;
- phí, slippage và funding đã tính;
- probability và payoff đến từ cùng context;
- uncertainty được xử lý.

Gate chính nên là EV lower-bound:

```python
if ev_lower_bound_bps <= required_margin_bps:
    block("EV_BELOW_MARGIN")

if safe_kelly <= 0:
    block("NO_POSITIVE_CAPITAL_ALLOCATION")
```

Kelly nên là output sizing sau khi EV đã được audit rõ.

### P1 - Payoff ratio có thể chưa đúng

Nếu `b` hoặc `rr_ratio` đến từ TP/SL lý thuyết, nó không tương đương realized payoff. Thực tế bị ảnh hưởng bởi:

- partial take-profit;
- trailing stop;
- time stop;
- reversal exit;
- slippage;
- gap qua stop;
- fee và funding.

Kelly nên dùng realized net payoff theo context:

```text
symbol x side x regime x signal_type
```

với shrinkage/fallback khi thiếu mẫu.

## Thiết Kế Lại Luồng Kelly

Không nên thay `meta_prob` bằng Kelly trực tiếp. Hai đại lượng khác nhau:

- `meta_prob`: xác suất thắng đã calibration.
- `kelly_fraction`: tỷ lệ vốn suy ra từ probability và payoff.
- `position_size`: exposure cuối cùng sau risk cap và adjustment.

Luồng đúng hơn:

```text
p = calibrated meta_prob
b = AvgRealizedWinNet / AvgRealizedLossNet
raw_kelly = p - (1 - p) / b
safe_kelly = raw_kelly
    * kelly_scale
    * uncertainty_multiplier
    * regime_multiplier
final_risk_fraction = min(safe_kelly, hard_max_risk_fraction)
recommended_notional = account_equity * final_risk_fraction / stop_distance_pct
```

Không nên còn fallback kiểu:

```python
prob_factor = meta_prob if meta_prob else kelly_fraction
```

## Fractional Kelly

Ngay cả sau khi sửa wiring, không nên dùng full Kelly. Đề xuất:

```python
kelly_scale = 0.10 đến 0.25
```

Ví dụ:

```text
raw_kelly = 0.265
kelly_scale = 0.20
scaled_kelly = 0.053
hard_max_risk = 0.01
final_risk = 0.01
```

Kelly nên quyết định tương quan size giữa các trade, còn hard risk cap bảo vệ vốn.

## Thiết Kế A/B Đúng

### Baseline - Kelly off

```text
Entry gate: hiện tại, không dùng Kelly
Sizing: fixed sizing hiện tại
```

Mục tiêu: baseline tương thích production cũ.

### Kelly gate-only

```text
Entry gate: block khi EV/Kelly không dương
Sizing: fixed sizing giống baseline
```

Mục tiêu: đo riêng tác động trade selection.

### Kelly sizing-only

```text
Entry gate: giống baseline
Sizing: fractional Kelly
```

Với Kelly âm, để mode này đúng nghĩa sizing-only:

```python
size = minimum_size if raw_kelly <= 0 else kelly_based_size
```

Mode này chủ yếu dùng cho nghiên cứu, không nên production.

### Hybrid

```text
Entry gate: EV lower-bound
Sizing: fractional Kelly có uncertainty adjustment
```

Đây là candidate production chính.

## Metric Cần Đo

Không nên chỉ so sánh `total PnL`.

| Nhóm | Metric |
|---|---|
| Return | Net PnL, return on capital, CAGR |
| Risk | Max drawdown, downside deviation, probability of ruin |
| Efficiency | Profit Factor, expectancy/trade, Sharpe/Sortino |
| Exposure | Average capital used, max exposure, time in market |
| Trade selection | Trades accepted/rejected, PnL của nhóm bị reject |
| Sizing quality | Correlation giữa size và realized return |
| Stability | Kết quả theo coin, side, regime và window |
| Cost | Fee, slippage, funding, turnover |

Metric đặc biệt quan trọng:

```text
CapitalEfficiency = NetPnL / AverageCapitalDeployed
```

Kelly có thể tạo PnL thấp hơn nhưng dùng ít vốn hơn; khi đó nó vẫn có thể là sizing tốt. Ngược lại, Kelly có thể tăng PnL chỉ vì tăng exposure, nên cần so sánh dưới cùng risk budget.

## Counterfactual Cho Lệnh Bị Chặn

Trước khi giữ Kelly làm gate production, cần replay nhóm lệnh bị chặn:

```text
Các lệnh Kelly <= 0 đã bị skip
    -> Replay outcome giả định nếu được vào
    -> Tính net PnL sau fee/slippage/funding
    -> Phân nhóm theo symbol/side/regime/signal type
```

Output mục tiêu:

```python
{
    "blocked_trade_count": 342,
    "would_have_won": ...,
    "would_have_lost": ...,
    "counterfactual_net_pnl": ...,
    "counterfactual_profit_factor": ...,
    "by_regime": {...},
    "by_signal_type": {...}
}
```

Đây là phép kiểm tra trực tiếp nhất để biết Kelly gate đang bảo vệ vốn, không có tác dụng, hay đang loại bỏ alpha.

## Remediation Plan

### P0 - Sửa tính đúng và observability

1. Sửa config path về `btc_scraper/regime/regime_config.json`.
2. Fail rõ hoặc fail-closed khi config không load.
3. Tách field Kelly, risk fraction, multiplier và notional.
4. Log config version/hash và input của công thức.
5. Loại bỏ hoặc giảm floor `0.25`.
6. Bảo đảm backtest và AutoTrader dùng cùng sizing function.

### P1 - Kiểm chứng Kelly gate

1. Replay `342` lệnh bị chặn.
2. Đo counterfactual PnL.
3. Kiểm tra calibration theo Kelly bucket.
4. Kiểm tra planned RR so với realized payoff.
5. Tách kết quả theo symbol, side, regime, signal type.

### P2 - A/B sizing

Chạy bốn mode với cùng signal set, cùng execution assumptions và cùng risk budget:

- Kelly off
- Kelly gate-only
- Kelly sizing-only
- Hybrid

### P3 - Tích hợp EV Decision Layer

Kelly không còn là gate độc lập từ heuristic RR, mà trở thành output của:

```text
calibrated probability
+ contextual realized payoff
+ cost model
+ uncertainty
= EV + safe Kelly allocation
```

## Acceptance Criteria

Chỉ nên công nhận Kelly là module sizing hiệu quả khi:

- `position_size` có phân bố thực sự, không tập trung gần như toàn bộ ở floor.
- Size tăng theo EV, không tăng đơn thuần theo probability.
- Nhóm size lớn có realized expectancy cao hơn nhóm size nhỏ.
- Hybrid Kelly cải thiện capital efficiency.
- Max drawdown không xấu hơn giới hạn.
- Kết quả ổn định qua walk-forward.
- Kết quả không phụ thuộc vào một symbol hoặc regime.
- Replay dùng production execution logic vẫn giữ kết quả.
- Enabled/disabled không còn cho delta `0.0`.
- Config được load đúng và có thể audit.
- Payoff sử dụng realized net outcomes hoặc estimate có shrinkage.

## Kết Luận Cuối

Kelly hiện tại nên được giữ lại, nhưng đổi nhãn thành:

> **Experimental edge gate / diagnostic**

Chưa nên gọi nó là position-sizing optimizer.

Ưu tiên hiện tại không phải tune `max_fraction` hay `decay_rate`, mà là:

1. Loại bỏ hoặc giảm sizing floor.
2. Thống nhất semantic của size.
3. Xác minh payoff input.
4. Replay nhóm lệnh Kelly đã chặn.

Sau các bước này mới nên chạy A/B `off / gate-only / sizing-only / hybrid`. Nếu không sửa wiring trước, sweep tiếp theo vẫn có nguy cơ cho delta gần `0`, nhưng nguyên nhân là implementation chưa cho Kelly tác động đúng chỗ, không phải Kelly vô giá trị.
