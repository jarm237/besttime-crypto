
# Phase 12 — Portfolio Intelligence & Dynamic Capital Allocation

> **Dự án:** `besttime-crypto`  
> **Mục tiêu:** Xây dựng lớp quản trị rủi ro cấp danh mục, phân bổ vốn động và kiểm soát concentration/correlation trước khi lệnh đi vào `HardRiskLimits` và `LiveExecutionGuard`.  
> **Trạng thái khởi tạo:** Planned  
> **Chế độ mặc định:** `SHADOW`  
> **Nguyên tắc an toàn:** Phase 12 chỉ được phép giữ nguyên hoặc giảm size do Phase 11 đề xuất; không được tăng vượt `HardRiskLimits`, không được chặn EXIT/EMERGENCY_EXIT và không được mở live gate.

---

## 1. Executive Summary

Sau Phase 11, hệ thống có thể trả lời:

```text
Một giao dịch riêng lẻ nên chịu bao nhiêu risk?
```

Phase 12 bổ sung khả năng trả lời:

```text
Danh mục hiện tại có nên nhận thêm giao dịch này không?
Nếu có thì chỉ nên cấp bao nhiêu vốn?
```

Vấn đề Phase 12 giải quyết:

```text
Nhiều lệnh riêng lẻ đều hợp lệ
→ nhưng cùng hướng
→ cùng sector
→ tương quan cao
→ cùng factor risk
→ tổng danh mục trở nên tập trung và dễ drawdown lớn
```

Luồng mục tiêu:

```text
Approved Signal
    ↓
Phase 11 Adaptive Sizing
    ↓
Portfolio State Snapshot
    ↓
Correlation / Factor / Concentration
    ↓
Portfolio Stress Test
    ↓
Risk Budget & Capital Allocation
    ↓
Portfolio Risk Gate
    ↓
HardRiskLimits
    ↓
LiveExecutionGuard
    ↓
ExecutionEngine
```

Output Phase 12 chỉ được phép:

```text
ALLOW
REDUCE
DEFER
SKIP
```

Không được phép:

```text
INCREASE_ABOVE_PHASE11
BYPASS_HARD_RISK_LIMITS
BYPASS_LIVE_EXECUTION_GUARD
BLOCK_EXIT
AUTO_HEDGE_WITHOUT_VALIDATION
```

---

## 2. Mục tiêu chi tiết

- Tạo snapshot danh mục point-in-time safe.
- Đo correlation động và downside correlation.
- Nhận diện exposure theo sector, strategy và factor.
- Tính concentration score cấp danh mục.
- Stress-test danh mục trước entry.
- Quản lý tổng risk budget.
- Phân bổ vốn khi có nhiều signal đồng thời.
- Giảm hoặc từ chối size khi danh mục quá tập trung.
- Tự động demote risk khi correlation/drawdown tăng.
- Chạy historical replay và shadow trước enforcement.
- Cung cấp dashboard và audit trail đầy đủ.

---

## 3. Phạm vi

### Trong phạm vi

- Portfolio snapshot.
- Correlation engine.
- Factor/sector exposure.
- Concentration score.
- Portfolio stress testing.
- Risk budget.
- Capital allocation.
- Portfolio risk gate.
- Rebalancing cơ bản.
- Drawdown controller.
- Historical replay.
- Shadow mode.
- Dashboard và governance.

### Ngoài phạm vi

- Auto leverage optimization.
- Auto hedge production ngay phiên bản đầu.
- Cross-exchange arbitrage.
- Portfolio optimizer ML trực tiếp.
- Dùng replay để mở live gate.
- Tăng size vượt đề xuất Phase 11.

---

# Phase 12.1 — Portfolio State Store

## 12.1.1 Mục tiêu

Tạo snapshot bất biến về trạng thái danh mục tại thời điểm xét lệnh.

## 12.1.2 File đề xuất

```text
btc_scraper/portfolio/portfolio_state.py
```

## 12.1.3 Schema

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class PositionExposure:
    symbol: str
    direction: int
    notional_usdt: float
    unrealized_pnl: float
    beta_to_btc: Optional[float]
    sector: str
    strategy: str
    regime: str
    crowding_score: Optional[float]


@dataclass(frozen=True)
class PortfolioState:
    observed_at: datetime
    equity_usdt: float
    cash_usdt: float
    gross_exposure_usdt: float
    net_exposure_usdt: float
    long_exposure_usdt: float
    short_exposure_usdt: float
    realized_pnl_today: float
    unrealized_pnl: float
    open_positions: tuple[PositionExposure, ...]
```

## 12.1.4 Metrics

```text
Gross exposure
Net exposure
Long exposure
Short exposure
Symbol concentration
Sector concentration
Strategy concentration
Regime concentration
Portfolio beta
Portfolio unrealized PnL
Available capital
```

## 12.1.5 Yêu cầu triển khai

- Snapshot immutable.
- Dùng một `observed_at` chung.
- Không query equity và positions ở nhiều thời điểm không đồng bộ.
- Có source/version metadata.
- Có freshness.
- Position mismatch phải làm snapshot `invalid`.

## 12.1.6 Deliverables

```text
btc_scraper/portfolio/portfolio_state.py
tests/test_portfolio_state.py
```

## 12.1.7 Acceptance Criteria

- [ ] Snapshot point-in-time safe.
- [ ] Gross/net exposure chính xác.
- [ ] Position mismatch được phát hiện.
- [ ] Snapshot invalid không được phép mở entry mới.
- [ ] EXIT vẫn được phép nếu snapshot degraded nhưng position xác định được.

---

# Phase 12.2 — Dynamic Correlation Engine

## 12.2.1 Mục tiêu

Đo tương quan động giữa các symbol thay vì dùng correlation tĩnh.

## 12.2.2 File đề xuất

```text
btc_scraper/portfolio/correlation_engine.py
```

## 12.2.3 Các loại correlation

```text
Pearson correlation
Spearman correlation
EWMA correlation
Downside correlation
Tail correlation
Correlation stability
```

## 12.2.4 Time windows

| Loại | Window đề xuất |
|---|---:|
| Short-term | 1h–24h |
| Medium-term | 7–30 ngày |
| Stress | chỉ vùng volatility cao |
| Downside | chỉ market return âm |

## 12.2.5 Output

```python
{
    "BTCUSDT:ETHUSDT": {
        "short_term": 0.91,
        "medium_term": 0.84,
        "downside": 0.95,
        "tail": 0.93,
        "sample_count": 720,
        "confidence": 0.88,
        "is_stale": False,
    }
}
```

## 12.2.6 Missing semantics

```text
Không đủ dữ liệu → None
Không coi missing correlation = 0
Không đủ confidence → conservative fallback
```

## 12.2.7 Conservative fallback

```python
effective_corr = max(
    known_short_term_corr or 0.0,
    known_medium_term_corr or 0.0,
    fallback_corr_by_sector,
)
```

## 12.2.8 Deliverables

```text
btc_scraper/portfolio/correlation_engine.py
tests/test_correlation_engine.py
```

## 12.2.9 Acceptance Criteria

- [ ] Correlation nằm trong `[-1, 1]`.
- [ ] Missing không bị chuyển thành zero giả.
- [ ] Downside correlation được tính riêng.
- [ ] Có confidence và sample count.
- [ ] Không look-ahead.
- [ ] Stale correlation giảm confidence.

---

# Phase 12.3 — Factor & Sector Exposure

## 12.3.1 Mục tiêu

Nhận diện nhiều symbol nhưng cùng chịu một nguồn rủi ro.

## 12.3.2 File đề xuất

```text
btc_scraper/portfolio/factor_exposure.py
```

## 12.3.3 Sector mapping

```text
BTC Ecosystem
Layer 1
Layer 2
DeFi
Exchange Tokens
Meme
AI
Gaming
Stablecoin Ecosystem
Other
```

## 12.3.4 Factor mapping

```text
BTC beta
ETH beta
Market risk-on
Momentum
High volatility
Funding/crowding
Liquidity
Small-cap
Regime-specific factor
```

## 12.3.5 Output

```python
{
    "market_beta_exposure": 0.82,
    "btc_beta_exposure": 0.74,
    "eth_beta_exposure": 0.31,
    "defi_sector_exposure": 0.28,
    "high_volatility_exposure": 0.41,
    "crowded_long_exposure": 0.37,
}
```

## 12.3.6 Rules

```text
max 2 highly correlated positions
max sector exposure
max strategy exposure
max market beta
max crowded-same-side exposure
```

## 12.3.7 Deliverables

```text
btc_scraper/portfolio/factor_exposure.py
btc_scraper/portfolio/sector_registry.py
tests/test_factor_exposure.py
```

## 12.3.8 Acceptance Criteria

- [ ] Mọi symbol có sector mặc định.
- [ ] Unknown sector không được coi là low-risk.
- [ ] Factor exposure có confidence.
- [ ] Mapping thay đổi phải có version.
- [ ] Same-side crowded exposure được tính.

---

# Phase 12.4 — Portfolio Concentration Score

## 12.4.1 Mục tiêu

Tổng hợp mức tập trung của danh mục thành score giải thích được.

## 12.4.2 File đề xuất

```text
btc_scraper/portfolio/concentration.py
```

## 12.4.3 Thành phần

```text
Symbol concentration
Sector concentration
Direction concentration
Correlation concentration
Strategy concentration
Crowding concentration
Factor concentration
```

## 12.4.4 Công thức gợi ý

```python
concentration_score = (
    0.20 * symbol_concentration
    + 0.18 * sector_concentration
    + 0.20 * correlation_concentration
    + 0.15 * direction_concentration
    + 0.10 * strategy_concentration
    + 0.08 * crowding_concentration
    + 0.09 * factor_concentration
)
```

## 12.4.5 HHI

```text
HHI = Σ(w_i²)
```

Ví dụ:

```text
1 position chiếm 100% → HHI = 1.0
4 position bằng nhau → HHI = 0.25
```

## 12.4.6 Phân loại

```text
0.00–0.30 → LOW
0.30–0.55 → MODERATE
0.55–0.75 → HIGH
> 0.75    → EXTREME
```

## 12.4.7 Output

```python
{
    "score": 0.68,
    "regime": "HIGH",
    "components": {
        "symbol": 0.40,
        "sector": 0.72,
        "correlation": 0.81,
        "direction": 0.90,
    },
    "reason_codes": [
        "high_long_concentration",
        "high_btc_cluster_exposure",
    ],
}
```

## 12.4.8 Deliverables

```text
btc_scraper/portfolio/concentration.py
tests/test_concentration.py
```

## 12.4.9 Acceptance Criteria

- [ ] Score trong `[0, 1]`.
- [ ] Có component breakdown.
- [ ] Missing data giảm confidence.
- [ ] Unknown sector/factor không làm giảm score giả.
- [ ] Concentration after candidate được tính trước khi submit.

---

# Phase 12.5 — Portfolio Stress Testing

## 12.5.1 Mục tiêu

Mô phỏng tác động của lệnh mới lên danh mục trong các kịch bản xấu.

## 12.5.2 File đề xuất

```text
btc_scraper/portfolio/stress_engine.py
```

## 12.5.3 Kịch bản

```text
BTC -5%
BTC -10%
ETH -10%
Altcoins -15%
Correlation → 0.95
Funding shock
Liquidity -80%
Spread ×5
Volatility ×2
Exchange outage
Stablecoin depeg
```

## 12.5.4 Pre-trade comparison

```python
before = stress_test(current_positions)
after = stress_test(current_positions + candidate_position)
incremental_stress = after.worst_case_loss - before.worst_case_loss
```

## 12.5.5 Output

```python
{
    "base_equity": 1000.0,
    "stress_losses": {
        "btc_down_10pct": -82.4,
        "altcoin_crash": -125.7,
        "correlation_spike": -96.3,
    },
    "worst_case_loss_pct": 0.126,
    "incremental_loss_pct": 0.041,
    "stress_gate_passed": False,
}
```

## 12.5.6 Decision rules

```text
Stress loss <= threshold → ALLOW
Vượt nhẹ → REDUCE
Vượt rõ → SKIP
```

## 12.5.7 Deliverables

```text
btc_scraper/portfolio/stress_engine.py
tests/test_portfolio_stress.py
```

## 12.5.8 Acceptance Criteria

- [ ] Stress test chạy trước ENTRY.
- [ ] EXIT không bị stress gate chặn.
- [ ] Có before/after comparison.
- [ ] Scenario config versioned.
- [ ] Worst-case loss không âm thầm bỏ qua missing data.

---

# Phase 12.6 — Portfolio Risk Budget

## 12.6.1 Mục tiêu

Quản lý tổng risk budget và phân bổ giữa symbol/strategy/sector.

## 12.6.2 File đề xuất

```text
btc_scraper/portfolio/risk_budget.py
```

## 12.6.3 Công thức

```python
available_risk_budget = (
    total_portfolio_risk_limit
    - currently_used_risk
    - reserved_order_risk
)
```

Candidate nhận:

```python
approved_risk = min(
    phase11_risk_budget,
    strategy_budget_remaining,
    sector_budget_remaining,
    symbol_budget_remaining,
    portfolio_budget_remaining,
)
```

## 12.6.4 Budget dimensions

```text
Portfolio
Symbol
Sector
Strategy
Direction
Crowding regime
Experimental models
```

## 12.6.5 Reservation

Dùng reservation để tránh race:

```python
reservation = risk_budget.reserve(candidate)
try:
    submit()
    reservation.commit()
except Exception:
    reservation.release()
    raise
```

## 12.6.6 Deliverables

```text
btc_scraper/portfolio/risk_budget.py
tests/test_risk_budget.py
```

## 12.6.7 Acceptance Criteria

- [ ] Risk budget không âm.
- [ ] Reservation atomic.
- [ ] Concurrent signals không vượt budget.
- [ ] Reject/retry không làm leak reservation.
- [ ] Exit không cần thêm risk budget.

---

# Phase 12.7 — Capital Allocation Optimizer

## 12.7.1 Mục tiêu

Khi nhiều signal xuất hiện cùng lúc, phân bổ vốn theo edge/risk thay vì xử lý đơn thuần theo thứ tự.

## 12.7.2 File đề xuất

```text
btc_scraper/portfolio/capital_allocator.py
```

## 12.7.3 Input

```text
Expected return
Calibrated probability
Phase 11 risk budget
Expected volatility
Correlation
Crowding
Liquidity
Transaction cost
Strategy priority
Regime confidence
```

## 12.7.4 Objective

```text
Expected portfolio return
- risk penalty
- concentration penalty
- transaction cost penalty
```

Dạng tổng quát:

```text
maximize μᵀw - λwᵀΣw - γC(w)
```

## 12.7.5 V1 heuristic

```python
allocation_score = (
    expected_edge
    * calibration_quality
    * liquidity_score
    * diversification_multiplier
    * regime_confidence
) / max(expected_volatility, epsilon)
```

## 12.7.6 Constraints

```text
sum allocation <= available capital
per-symbol max
per-sector max
gross exposure max
net exposure max
risk budget max
liquidity-safe size
rollout-stage limits
```

## 12.7.7 Rule quan trọng

```python
approved_size = min(
    phase11_size,
    allocator_size,
    portfolio_gate_size,
    hard_limit_size,
)
```

## 12.7.8 Deliverables

```text
btc_scraper/portfolio/capital_allocator.py
tests/test_capital_allocator.py
```

## 12.7.9 Acceptance Criteria

- [ ] Không tăng size vượt Phase 11.
- [ ] Allocation deterministic với cùng input.
- [ ] Có explanation/reason codes.
- [ ] Không phụ thuộc optimizer external không kiểm soát ở v1.
- [ ] Có fallback heuristic khi covariance unavailable.

---

# Phase 12.8 — Portfolio Risk Gate

## 12.8.1 Mục tiêu

Tạo checkpoint trung tâm cấp danh mục trước `HardRiskLimits`.

## 12.8.2 File đề xuất

```text
btc_scraper/portfolio/portfolio_risk_gate.py
```

## 12.8.3 Rule order

```text
1. Portfolio snapshot valid
2. Available risk budget
3. Symbol exposure
4. Sector exposure
5. Direction exposure
6. Correlation cluster
7. Factor exposure
8. Stress test impact
9. Concentration score
10. Liquidity-safe size
11. Final approved size
```

## 12.8.4 Decision output

```python
{
    "allowed": True,
    "decision": "ALLOW | REDUCE | DEFER | SKIP",
    "requested_notional": 200.0,
    "approved_notional": 80.0,
    "portfolio_risk_before": 0.021,
    "portfolio_risk_after": 0.028,
    "concentration_before": 0.48,
    "concentration_after": 0.66,
    "reason_codes": [
        "high_btc_correlation",
        "sector_budget_near_limit",
        "stress_loss_cap",
    ],
}
```

## 12.8.5 Intent behavior

```text
ENTRY:
  full checks

ADD_POSITION:
  stricter concentration checks

REDUCE_POSITION:
  allow if valid

EXIT:
  allow

EMERGENCY_EXIT:
  bypass optional portfolio restrictions
```

## 12.8.6 Deliverables

```text
btc_scraper/portfolio/portfolio_risk_gate.py
tests/test_portfolio_risk_gate.py
```

## 12.8.7 Acceptance Criteria

- [ ] Centralized gate.
- [ ] Không direct portfolio sizing bypass.
- [ ] EXIT/EMERGENCY_EXIT không bị block.
- [ ] Output audit đầy đủ.
- [ ] Final size không vượt Phase 11.

---

# Phase 12.9 — Decision & Execution Integration

## 12.9.1 Target flow

```text
Signal
→ MetaDecisionEngine
→ Phase 11 Adaptive Sizing
→ Phase 12 Portfolio Risk Gate
→ HardRiskLimits
→ LiveExecutionGuard
→ ExecutionEngine
```

## 12.9.2 Integration files

```text
btc_scraper/portfolio/integration.py
btc_scraper/execution/execution_engine.py
btc_scraper/ml_engine/multi_agent.py
```

## 12.9.3 Shadow behavior

```text
SHADOW:
  compute recommendation
  do not modify production size
  log difference

ENFORCED:
  final size = min(production, Phase11, Phase12, HardRiskLimits)
```

## 12.9.4 Concurrency

Dùng lock/reservation theo account để tránh hai candidate cùng pass trên một state cũ.

## 12.9.5 Deliverables

```text
btc_scraper/portfolio/integration.py
tests/test_phase12_integration.py
```

## 12.9.6 Acceptance Criteria

- [ ] Shadow không đổi lệnh thật.
- [ ] Enforced mode giảm size đúng.
- [ ] HardRiskLimits luôn là trần cuối.
- [ ] Không bypass LiveExecutionGuard.
- [ ] Concurrent candidate không vượt risk budget.

---

# Phase 12.10 — Portfolio Rebalancer

## 12.10.1 Mục tiêu

Giảm rủi ro khi correlation/concentration thay đổi sau khi vị thế đã mở.

## 12.10.2 File đề xuất

```text
btc_scraper/portfolio/rebalancer.py
```

## 12.10.3 Trigger

```text
Concentration > threshold
Correlation spike
Drawdown breach
Regime change
Crowding reversal
Liquidity deterioration
Volatility spike
```

## 12.10.4 Action v1

```text
NO_ACTION
BLOCK_NEW_ENTRIES
REDUCE_LARGEST_POSITION
REDUCE_CORRELATED_CLUSTER
CLOSE_LOWEST_EDGE_POSITION
```

Không bật auto hedge ở v1.

## 12.10.5 Priority

```text
1. Reduce lowest expected edge
2. Reduce highest concentration contributor
3. Preserve exits
4. Avoid unnecessary turnover
```

## 12.10.6 Deliverables

```text
btc_scraper/portfolio/rebalancer.py
tests/test_rebalancer.py
```

## 12.10.7 Acceptance Criteria

- [ ] Không auto hedge.
- [ ] Action có reason codes.
- [ ] Rebalancing tôn trọng execution cost.
- [ ] Không đóng vị thế trái với emergency policy.
- [ ] Có cooldown tránh churn.

---

# Phase 12.11 — Portfolio Drawdown Controller

## 12.11.1 File đề xuất

```text
btc_scraper/portfolio/drawdown_controller.py
```

## 12.11.2 Drawdown tiers

```python
DRAWDOWN_TIERS = {
    "NORMAL": 0.00,
    "CAUTION": 0.05,
    "DEFENSIVE": 0.08,
    "HALT_NEW_ENTRIES": 0.12,
}
```

## 12.11.3 Actions

| Tier | Hành động |
|---|---|
| NORMAL | 100% risk budget |
| CAUTION | giảm 25% |
| DEFENSIVE | giảm 50%, chỉ signal mạnh |
| HALT | chặn entry, cho phép exit |

## 12.11.4 Hysteresis

```text
Enter DEFENSIVE tại -8%
Exit DEFENSIVE khi drawdown hồi về dưới -5%
```

## 12.11.5 Deliverables

```text
btc_scraper/portfolio/drawdown_controller.py
tests/test_drawdown_controller.py
```

## 12.11.6 Acceptance Criteria

- [ ] Drawdown tính theo equity.
- [ ] Có hysteresis.
- [ ] Không reset ngay khi hồi nhẹ.
- [ ] HALT chỉ chặn entry.
- [ ] EXIT vẫn được phép.

---

# Phase 12.12 — Historical Replay

## 12.12.1 Mục tiêu

Đánh giá hiệu quả quản lý danh mục trên dữ liệu cũ mà không mở live gate.

## 12.12.2 Variants

```text
Baseline
Phase 11 only
Phase 12 only
Phase 11 + Phase 12
```

## 12.12.3 Metrics

```text
Net PnL
Max Drawdown
Portfolio volatility
Calmar
Sharpe
Sortino
Tail loss
Gross/net exposure
Average correlation
Concentration score
Turnover
Transaction cost
Worst stress loss
```

## 12.12.4 Regime breakdown

```text
Bull
Bear
Range
High volatility
Correlation spike
Liquidity crisis
```

## 12.12.5 Replay rules

- Không look-ahead.
- Entry tại T+1.
- Correlation/covariance chỉ dùng dữ liệu quá khứ.
- Alternative data backward as-of join.
- Replay fills dùng `historical_replay`.
- Không tính replay vào Phase 5 live gate.

## 12.12.6 Deliverables

```text
scripts/run_portfolio_replay.py
scripts/generate_portfolio_report.py
data/portfolio/reports/
```

## 12.12.7 Acceptance Criteria

- [ ] Không look-ahead.
- [ ] MaxDD không tăng.
- [ ] Tail loss giảm hoặc không xấu hơn 5%.
- [ ] Concentration giảm.
- [ ] Transaction cost được tính.
- [ ] Ổn định trên ít nhất 3 regime.

---

# Phase 12.13 — Shadow Mode

## 12.13.1 Mode

```env
PORTFOLIO_INTELLIGENCE_MODE=OFF|SHADOW|ENFORCED
```

Mặc định:

```env
PORTFOLIO_INTELLIGENCE_MODE=SHADOW
```

## 12.13.2 Shadow record

```python
{
    "signal_id": "...",
    "symbol": "BTCUSDT",
    "phase11_size": 200.0,
    "portfolio_approved_size": 80.0,
    "production_size": 200.0,
    "concentration_before": 0.48,
    "concentration_after": 0.69,
    "stress_loss_before": 0.07,
    "stress_loss_after": 0.12,
    "decision": "REDUCE",
}
```

## 12.13.3 Minimum sample

```text
>= 100 closed trades
>= 30 ngày
>= 3 symbols
>= 3 regimes
```

## 12.13.4 Promotion gate

```text
MaxDD không tăng
Tail loss giảm hoặc không xấu hơn 5%
Net PnL sau phí không giảm quá 10%
Concentration không tăng
Không có risk-limit violation
Không tăng reject rate đáng kể
```

## 12.13.5 Deliverables

```text
btc_scraper/portfolio/shadow_tracker.py
data/portfolio/shadow/
docs/remediation/Phase12_Shadow_Report.md
```

---

# Phase 12.14 — Dashboard & Monitoring

## 12.14.1 Dashboard tab

```text
Portfolio Intelligence
```

## 12.14.2 Metrics

```text
Gross exposure
Net exposure
Long/short exposure
Portfolio beta
Correlation heatmap
Sector allocation
Strategy allocation
Concentration score
Risk budget used
Stress test result
Drawdown tier
Reduced/rejected signals
```

## 12.14.3 Alerts

```text
CORRELATION_SPIKE
CONCENTRATION_HIGH
STRESS_LOSS_LIMIT
PORTFOLIO_DRAWDOWN
SECTOR_LIMIT
RISK_BUDGET_EXHAUSTED
PORTFOLIO_STATE_INVALID
```

## 12.14.4 Deliverables

```text
btc_scraper/portfolio/monitor.py
api/portfolio endpoints
dashboard Portfolio Intelligence tab
```

---

## 4. Cấu trúc file đề xuất

```text
btc_scraper/portfolio/
├── __init__.py
├── config.py
├── portfolio_state.py
├── sector_registry.py
├── correlation_engine.py
├── factor_exposure.py
├── concentration.py
├── stress_engine.py
├── risk_budget.py
├── capital_allocator.py
├── portfolio_risk_gate.py
├── integration.py
├── rebalancer.py
├── drawdown_controller.py
├── shadow_tracker.py
└── monitor.py

scripts/
├── run_portfolio_replay.py
├── generate_portfolio_report.py
└── run_portfolio_stress_test.py

tests/
├── test_portfolio_state.py
├── test_correlation_engine.py
├── test_factor_exposure.py
├── test_concentration.py
├── test_portfolio_stress.py
├── test_risk_budget.py
├── test_capital_allocator.py
├── test_portfolio_risk_gate.py
├── test_rebalancer.py
├── test_drawdown_controller.py
└── test_phase12_integration.py

docs/remediation/
├── Phase12_Portfolio_Intelligence_Implementation_Plan.md
├── Phase12_Shadow_Report.md
└── Phase12_Completion_Report.md
```

---

## 5. Environment Configuration

```env
PORTFOLIO_INTELLIGENCE_ENABLED=true
PORTFOLIO_INTELLIGENCE_MODE=SHADOW

PORTFOLIO_MAX_GROSS_EXPOSURE_PCT=1.50
PORTFOLIO_MAX_NET_EXPOSURE_PCT=1.00
PORTFOLIO_MAX_SYMBOL_EXPOSURE_PCT=0.25
PORTFOLIO_MAX_SECTOR_EXPOSURE_PCT=0.40
PORTFOLIO_MAX_CORRELATED_CLUSTER_PCT=0.50

PORTFOLIO_MAX_CONCENTRATION_SCORE=0.70
PORTFOLIO_MAX_STRESS_LOSS_PCT=0.12
PORTFOLIO_MAX_DRAWDOWN_PCT=0.12

PORTFOLIO_CORRELATION_SHORT_WINDOW=96
PORTFOLIO_CORRELATION_MEDIUM_WINDOW=720

PORTFOLIO_SHADOW_MIN_TRADES=100
PORTFOLIO_SHADOW_MIN_DAYS=30
```

Các giới hạn trên vẫn phải chịu:

```text
Phase 11 size
Rollout stage
HardRiskLimits
LiveExecutionGuard
```

---

## 6. Test Plan

### Unit tests

```text
Immutable portfolio snapshot
Gross/net exposure
Correlation bounds
Missing correlation
Downside correlation
HHI concentration
Sector concentration
Risk budget exhaustion
Stress loss
Drawdown tiers
Exit bypass
```

### Integration tests

```text
Phase 11 size → Phase 12 reduction
Two concurrent correlated signals
Portfolio gate cannot increase size
HardRiskLimits overrides Phase 12
EXIT remains allowed
Rollout stage remains active
Shadow mode does not modify execution
```

### Chaos/data tests

```text
Correlation stale
Position reconciliation mismatch
Equity unavailable
Sudden correlation spike
Volatility doubles
Market falls 10%
Liquidity collapses
```

---

## 7. Acceptance Gates

### Functional Gate

- [ ] Portfolio snapshot point-in-time safe.
- [ ] Correlation trong `[-1, 1]`.
- [ ] Missing correlation không coi là zero.
- [ ] Phase 12 không tăng size vượt Phase 11.
- [ ] HardRiskLimits là trần cuối cùng.
- [ ] EXIT/EMERGENCY_EXIT không bị chặn.
- [ ] Stress test chạy trước entry.
- [ ] Reason codes được audit đầy đủ.

### Replay Gate

- [ ] Không look-ahead.
- [ ] MaxDD không tăng.
- [ ] Tail loss giảm hoặc không xấu hơn 5%.
- [ ] Concentration giảm.
- [ ] Performance ổn định trên ít nhất 3 regime.
- [ ] Transaction-cost impact được tính.

### Shadow Gate

- [ ] Tối thiểu 100 closed trades.
- [ ] Tối thiểu 30 ngày.
- [ ] Ít nhất 3 symbols.
- [ ] Không có risk-limit violation.
- [ ] Portfolio drawdown không xấu hơn baseline.
- [ ] Net PnL sau phí không giảm quá 10%.

### Enforcement Gate

- [ ] Chạy `SHADOW` trước.
- [ ] Phase 5 live gate phải PASS.
- [ ] Phase 11 enforcement ổn định hoặc vẫn ở shadow.
- [ ] Full regression xanh.
- [ ] Rollback config đã kiểm thử.
- [ ] HardRiskLimits và LiveExecutionGuard vẫn hoạt động.

---

## 8. Rollout Plan

### Stage A — Offline

```text
Portfolio State
Correlation
Factor/Sector Exposure
Concentration
Stress Test
Risk Budget
Capital Allocation
Historical Replay
```

### Stage B — Shadow

```text
PORTFOLIO_INTELLIGENCE_MODE=SHADOW
100+ trades
30+ days
```

### Stage C — Partial Enforcement

```text
Chỉ REDUCE size
Không SKIP signal
Không auto rebalance
```

### Stage D — Full Enforcement

```text
ALLOW / REDUCE / DEFER / SKIP
Drawdown controller active
Rebalancer v1 active
No auto hedge
```

---

## 9. Risks

| Rủi ro | Mức độ | Giảm thiểu |
|---|---:|---|
| Correlation thay đổi nhanh | Cao | Short-term + downside corr |
| Missing corr bị hiểu sai | Cao | None + conservative fallback |
| Double-count factor | Trung bình | Factor registry/versioning |
| Optimizer quá phức tạp | Cao | Heuristic v1 |
| Rebalance gây churn | Cao | Cooldown + cost penalty |
| Stress scenario quá nhẹ | Cao | Versioned scenario library |
| Race trên risk budget | Rất cao | Atomic reservation |
| Portfolio gate tăng size | Rất cao | `min()` invariant |
| Shadow sample thiếu | Trung bình | Minimum sample gate |

---

## 10. Definition of Done

Phase 12 được xem là hoàn thành khi:

```text
Portfolio State pass
Correlation Engine pass
Factor/Sector Exposure pass
Concentration Score pass
Stress Engine pass
Risk Budget pass
Capital Allocation pass
Portfolio Risk Gate pass
Historical Replay pass
Shadow Validation pass
Dashboard/Audit hoạt động
Enforcement gate được phê duyệt
```

Mục tiêu cuối cùng:

```text
Không để nhiều giao dịch riêng lẻ hợp lệ
kết hợp thành một danh mục tập trung và rủi ro cao.
```
