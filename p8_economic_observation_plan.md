# P8 — Economic Effectiveness Observation & Review Plan

## 0. Điểm xuất phát

```text
P7_RUNTIME_PROOF              SUFFICIENT
P7_ENGINEERING                STOPPED

P8_IMPLEMENTATION             COMPLETE
P8_STATE                      ACCUMULATING

PRIMARY_POPULATION            CURRENT_CANARY
CURRENT_CANARY_N              2
DIAGNOSTIC_THRESHOLD          30
PRIMARY_REVIEW_THRESHOLD      100

DATA_INTEGRITY                PASS
POPULATION_RECONCILIATION     PASS
ACCOUNTING_RECONCILIATION     PASS

MODEL_CHANGE                  NOT_AUTHORIZED
POLICY_CHANGE                 NOT_AUTHORIZED
UNIVERSE_CHANGE               NOT_AUTHORIZED
RUNTIME_REMEDIATION           NOT_REQUIRED

PRIMARY_OBJECTIVE             ECONOMIC_EFFECTIVENESS
```

Mục tiêu từ đây không còn là:
```text
"runtime có chạy đúng không?"
```
mà là:
```text
"sealed runtime hiện tại có tạo ra positive economic value sau transaction costs hay không?"
```

---

# Phase P8-A — Natural Economic Evidence Accumulation

## A1. Giữ nguyên runtime
Runner tiếp tục chạy với đúng release hiện tại.
Không chủ động:
- retrain model
- thay threshold
- remove symbol
- thay routing
- sửa risk policy
- force trade
- synthetic fill/outcome
- restart runner để lấy evidence

Nếu runtime chạy bình thường thì **không động vào nó**.

## A2. Primary evaluation population
Chỉ population này được dùng cho primary verdict:
```text
CURRENT_CANARY
```
Historical/backfilled data:
```text
SECONDARY / EXPLORATORY ONLY
```
Không được dùng historical data để biến:
```text
CURRENT_CANARY N=2
```
thành:
```text
"sample effectively N=16"
```
Hai population phải tiếp tục tách biệt.

## A3. Unit of evidence
Đơn vị chính:
```text
1 natural closed trade
```
Một trade chỉ được tính vào primary sample khi đủ dữ liệu economic outcome:
- trade identity
- symbol
- route
- side
- entry
- exit
- quantity
- gross pnl
- fees where available
- net pnl
- gross return bps
- net return bps
- opened_at
- closed_at

Nếu slippage vẫn chưa có:
```text
slippage = NOT_AVAILABLE
```
không tự estimate rồi coi đó là observed value.

## A4. Không chạy report theo từng trade
Không làm:
```text
N=3 → run report
N=4 → run report
N=5 → run report
...
```
Điều đó không tạo thêm giá trị quyết định.

Canonical next scheduled analytical checkpoint:
```text
N_CANARY >= 30
```
Trước đó chỉ reopen nếu có **material defect hoặc material risk event**.

---

# Phase P8-B — Early-Reopen Exceptions

Có thể hành động trước N=30 trong đúng hai class.

## B1. Economic data validity defect
Ví dụ:
- duplicate closed trade
- wrong side sign
- fee counted twice
- gross/net arithmetic invalid
- wrong entry/exit linkage
- current vs historical population contamination
- one trade counted under wrong route

Điều kiện để sửa:
> Nếu không sửa lỗi này thì kết luận economic effectiveness sẽ sai.

Nếu lỗi chỉ là presentation, formatting, wording hoặc metadata không ảnh hưởng kết luận:
```text
DO NOT INTERRUPT ACCUMULATION
```

## B2. Material risk/runtime defect
Ví dụ:
- position sizing vượt risk contract
- duplicate real execution
- unexpected order side
- runaway execution loop
- unbounded position
- incorrect stop/exit causing material exposure

Đây là safety/economic defect nên không cần đợi N=30.

Nhưng các trường hợp sau **không đủ**:
- 3 trades thua
- 5 trades thua
- PF xấu ở N=8
- MC5 có 3 losses liên tiếp
- một symbol có PnL âm

Đó là economic observations, không phải runtime defect.

---

# Phase P8-C — N=30 Diagnostic Economic Review

## Trigger
```text
CURRENT_CANARY_CLOSED_TRADES >= 30
```
Lúc đó mới chạy:
```bash
./scripts/run_p8_evaluation.sh
```
và freeze một diagnostic snapshot.

Ví dụ:
```text
P8_DIAGNOSTIC_SAMPLE_ID
P8_DIAGNOSTIC_N = 30+
sample_start
sample_end
release_id
```
Không cần seal kiểu P7; chỉ cần đảm bảo report nói rõ sample nào đang được phân tích.

---

# Phase P8-D — Portfolio Economics at N=30

Primary metrics:

| Metric | Ý nghĩa |
| :--- | :--- |
| **Gross EV** | Alpha trước cost |
| **Net EV** | Giá trị sau observed costs |
| **Profit Factor** | Gross profit / gross loss |
| **Win Rate** | Tỷ lệ trade lời |
| **Avg Win** | Average positive outcome |
| **Avg Loss** | Average negative outcome |
| **Total Gross PnL** | Tổng before-cost PnL |
| **Total Fees** | Cost drag |
| **Total Net PnL** | Giá trị thực sau fees |
| **Max Drawdown** | Risk realized |
| **Median holding time** | Execution/holding behavior |

Điều cần nhìn đầu tiên:
```text
Gross EV
     ↓
cost drag
     ↓
Net EV
```
Không chỉ nhìn win rate.

Ví dụ:
```text
WR = 40%
PF = 1.4
Net EV > 0
```
có thể hoàn toàn tốt hơn:
```text
WR = 70%
PF = 0.8
Net EV < 0
```

---

# Phase P8-E — Route Attribution

Với kiến trúc hiện tại phải tách:
```text
LEGACY vs MC5_QUALIFIED
```
Tính riêng:
- N
- Gross EV
- Net EV
- PF
- Win Rate
- Avg win/loss
- PnL
- Drawdown

Các pattern đáng quan tâm:
- **CASE 1**: LEGACY positive, MC5 positive $\rightarrow$ good overall signal
- **CASE 2**: LEGACY positive, MC5 strongly negative $\rightarrow$ coverage expansion concern
- **CASE 3**: LEGACY negative, MC5 positive $\rightarrow$ legacy degradation / new route promising
- **CASE 4**: both negative $\rightarrow$ broader alpha concern

Nhưng ở N=30 route sample có thể vẫn nhỏ.

Ví dụ:
```text
30 total
LEGACY = 25
MC5 = 5
```
thì:
```text
PORTFOLIO_DIAGNOSTIC = AVAILABLE
MC5_ROUTE_VERDICT    = INSUFFICIENT_SAMPLE
```
Không ép verdict route khi N quá ít.

---

# Phase P8-F — Symbol Attribution

Tách theo 9 symbols:
```text
BTC, ETH, BNB, DOGE, IOTA, NEAR, SOL, TRX, ZEC
```
Cho mỗi symbol:
- trade_count
- net EV
- gross EV
- PF
- win rate
- net PnL
- drawdown

Nhưng tuyệt đối không:
```text
DOGE N=2 negative → remove DOGE
```
N nhỏ chỉ tạo hypothesis.

Một symbol chỉ nên trở thành candidate cho universe review khi:
```text
sample reasonable + negative economics persistent + loss not caused by one outlier
```

---

# Phase P8-G — Side Attribution

Tách:
```text
LONG vs SHORT
```
Mục tiêu trả lời:
```text
alpha nằm ở cả hai directions hay chỉ một side?
```
Ví dụ:
```text
LONG EV  -90 bps
SHORT EV +25 bps
```
sẽ tạo hypothesis rất khác so với cả hai cùng âm.

Nhưng ở N=30 vẫn chỉ là diagnostic.

---

# Phase P8-H — Confidence / Score Effectiveness

Đây là phần đặc biệt quan trọng với ML.

Chia model score thành quantiles:
```text
Q1 lowest, Q2, Q3, Q4, Q5 highest
```
Quan sát:
- mean Net EV
- median Net EV
- WR
- PF

Mục tiêu không phải bắt buộc perfect monotonicity.
Mục tiêu là xem có evidence kiểu:
```text
higher confidence → generally better outcome
```
Nếu:
```text
Q1-Q3 negative
Q4-Q5 positive
```
đây là signal rất hữu ích cho future policy research.

**Không tune threshold ngay trong P8.**
Ghi thành hypothesis `P8_HYPOTHESIS_CONFIDENCE_SELECTION` và chỉ mở threshold research sau khi current evaluation window kết thúc.

---

# Phase P8-I — Cost Analysis

Hiện report đã có fee nhưng chưa có full slippage accounting.

Ở N=30 cần tách:
- Gross EV
- Fees
- Known execution costs
- Net EV
- Unknown costs

Ví dụ:
```text
Gross EV       +30 bps
Fees           -20 bps
Net observed   +10 bps
Slippage       NOT_AVAILABLE
```
Verdict không được viết `ALL_IN_NET_EV = +10` mà phải là:
```text
OBSERVED_NET_EV = +10
FULL_ALL_IN_EV  = UNKNOWN
```
cho tới khi đủ cost data.

Không cần sửa runtime chỉ để có perfect cost accounting nếu current evidence vẫn đủ cho một diagnostic conclusion.

---

# Phase P8-J — N=30 Diagnostic Verdict

Không dùng verdict binary PASS/FAIL.
Dùng một trong các trạng thái:
```text
PROMISING, MIXED, CONCERNING, STRONGLY_NEGATIVE
```

### PROMISING
Ví dụ:
```text
Net EV > 0
PF > 1
drawdown acceptable
not dominated by one lucky trade
```
Action:
```text
CONTINUE TO N=100
```
Không promote, không tăng risk.

### MIXED
Ví dụ:
```text
aggregate around break-even
route disagreement
symbol concentration
large uncertainty
```
Action:
```text
CONTINUE TO N=100
```
Không tune.

### CONCERNING
Ví dụ:
```text
Net EV < 0 but gross EV > 0
```
Có thể là:
```text
execution/cost problem or sample noise
```
Action:
```text
continue if risk remains acceptable, collect to N=100
```
và tạo hypothesis cho future execution review.

### STRONGLY_NEGATIVE
Ví dụ:
```text
Gross EV materially negative
PF substantially below 1
broad losses across routes/symbols
not caused by one outlier
```
Ở N=30 chưa nhất thiết stop ngay.
Nhưng có thể authorize `EARLY ECONOMIC REVIEW` nếu evidence đủ cực đoan.

---

# Phase P8-K — Outlier/Concentration Check

Trước mọi conclusion phải kiểm tra:
- top winner contribution
- top loser contribution

Ví dụ:
```text
Total PnL = +$20
one trade = +$19
```
thì `positive aggregate` không đồng nghĩa với robust positive alpha.

Nên thêm diagnostic:
- PnL excluding best trade
- PnL excluding worst trade
Không phải để cherry-pick, mà để thấy concentration.

---

# Phase P8-L — Decision after N=30

Sau diagnostic review:
```text
PROMISING / MIXED / CONCERNING → continue same sealed runtime → target N=100
```
Không đổi model. Nếu thay model tại N=30 thì $N=30$ sample không còn cùng population với $N=31..100$ và P8 evaluation bị phá.

---

# Phase P8-M — Accumulation N=30 → N=100

Giai đoạn này cực kỳ đơn giản:
- same model
- same policy
- same universe
- same routing
- natural trades only

Không cần report mỗi 10 trades.
Canonical next checkpoint:
```text
N >= 100
```

---

# Phase P8-N — Primary Economic Review at N=100

Đây mới là review chính.
Ngoài các metric N=30, bổ sung:
- bootstrap confidence interval for Net EV
- bootstrap confidence interval for Gross EV
- PF stability
- route sample sufficiency
- symbol concentration
- side stability
- confidence monotonicity
- drawdown characteristics

Primary question:
> Does the evidence support a positive cost-adjusted economic edge?

---

# Phase P8-O — Primary Decision Matrix

## O1 — CONTINUE
Nếu:
- Net EV > 0
- PF > 1
- reasonable confidence around EV
- drawdown acceptable
- edge not single-trade dominated

Verdict:
```text
P8_ECONOMIC_VERDICT = CONTINUE
```
Có thể mở workstream tiếp theo về larger canary / sizing, nhưng **không tự động tăng risk**.

## O2 — EXECUTION_LIMITED
Nếu:
```text
Gross EV > 0 và Net EV <= 0
```
thì alpha có thể tồn tại nhưng bị costs giết.

Verdict:
```text
P8_ECONOMIC_VERDICT = ECONOMIC_INFEASIBILITY_UNDER_CURRENT_EXECUTION
```
Next workstream:
```text
execution/cost research
```
Không retrain model trước.

## O3 — ALPHA FAILURE
Nếu:
```text
Gross EV materially <= 0
```
thì giảm fees không cứu được underlying signal.

Verdict:
```text
P8_ECONOMIC_VERDICT = ALPHA_FAILURE
```
Next:
```text
new signal/model research
```
Không tiếp tục tuning cùng strategy chỉ để cố cứu.

## O4 — ROUTE FAILURE
Nếu:
```text
LEGACY economically viable
MC5 consistently negative
```
Verdict có thể là:
```text
MODEL_COVERAGE_ROUTE_FAILURE
```
Next:
```text
MC5 route/model research
```
Không gọi toàn bộ strategy là thất bại.

## O5 — SIGNAL STARVATION
Nếu sau một observation population lớn:
- final decisions rất nhiều
- actionable gần như không có

thì:
```text
SIGNAL_STARVATION
```
Next:
```text
decision-policy research
```
Nhưng funnel dùng cho verdict này phải là **current-canary scoped funnel**, không phải broader historical exploratory funnel.

---

# Anti-loop contract

1. P7 runtime correctness is already sufficient.
2. Do not rerun P7 unless a material runtime defect exists.
3. Do not rerun P8 report merely because another trade appeared.
4. No synthetic economic evidence.
5. Do not modify model/policy/universe during the active sample.
6. A technical task is authorized only if not doing it would materially invalidate an economic conclusion.
7. Presentation imperfections do not block accumulation.
8. N=30 is diagnostic, not an optimization checkpoint.
9. N=100 is the primary economic review.
10. P8's output is an economic decision, not another technical seal.

---

# Roadmap rút gọn

```text
NOW
│
│ P8 implementation complete
│ Current N = 2
│
▼
NATURAL ACCUMULATION
│
│ no code changes
│ no tuning
│
▼
N >= 30
│
├─ run P8 report once
├─ diagnostic economics
├─ route/symbol/side attribution
├─ confidence analysis
└─ PROMISING / MIXED / CONCERNING / STRONGLY_NEGATIVE
│
▼
KEEP SAME RUNTIME
│
▼
N >= 100
│
├─ primary economic review
├─ uncertainty/stability analysis
├─ route sufficiency
├─ cost decomposition
│
▼
ECONOMIC VERDICT
│
├─ CONTINUE
├─ EXECUTION_LIMITED
├─ ALPHA_FAILURE
├─ ROUTE_FAILURE
└─ SIGNAL_STARVATION
│
▼
AUTHORIZE THE CORRECT SUCCESSOR
```

## Checkpoint ngay lúc này

```text
P8_STATE                     ACCUMULATING
CURRENT_CANARY_N             2

NEXT_TRIGGER                 CURRENT_CANARY_N >= 30
NEXT_ACTION                  RUN P8 DIAGNOSTIC REPORT

UNTIL_THEN                   NO ACTIVE DEVELOPMENT

MODEL                        FROZEN
POLICY                       FROZEN
UNIVERSE                     FROZEN
ROUTING                      FROZEN

PRIMARY_GOAL                 REALIZED ECONOMIC VALUE
```
