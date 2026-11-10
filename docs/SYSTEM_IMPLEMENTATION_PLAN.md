# Kế hoạch hiện thực tổng thể hệ thống `besttime-crypto`

> Cập nhật: 2026-11-09  
> Phạm vi: nghiên cứu chiến lược và paper/demo trading  
> Ngoài phạm vi: cấp quyền real trade, triển khai vốn thật và các hạng mục security chỉ phục vụ real trading

## 1. Mục tiêu tối cao

Mục tiêu của hệ thống không phải là chứng minh rằng một tiến trình có thể chạy liên tục nhiều ngày. Mục tiêu là xây được một quy trình nghiên cứu và paper trading có khả năng trả lời bằng dữ liệu:

1. Chiến lược nào tạo lợi thế kinh tế sau phí và trượt giá?
2. Lợi thế đó có tốt hơn chiến lược hiện tại và các baseline đơn giản không?
3. Lợi thế có ổn định theo thời gian, tài sản và trạng thái thị trường không?
4. Quyết định nghiên cứu có được truyền đúng qua risk, portfolio, sizing và paper execution không?
5. Kết quả có tái lập được từ dữ liệu, cấu hình, model artifact và code version đã khóa không?
6. Hệ thống có đạt throughput/latency phù hợp để chạy nhiều chiến lược và nhiều thí nghiệm với chi phí máy hợp lý không?

Đích cuối của giai đoạn này là một **research-to-paper platform** có thể:

- tải và chuẩn hóa dữ liệu lịch sử point-in-time;
- tạo lại dataset training mà không look-ahead;
- huấn luyện nhiều họ chiến lược/mô hình;
- so sánh công bằng với cùng dữ liệu và cùng mô hình chi phí;
- chọn hoặc loại ứng viên bằng walk-forward/OOS;
- replay ứng viên qua đúng decision/execution path hiện tại;
- chạy paper/demo có giới hạn để đo parity, latency và drift;
- tuyệt đối không suy diễn paper uptime thành trading edge.

## 2. Nguyên tắc triển khai

### 2.1. Kiến trúc hiện tại là nền tảng

Không xây một hệ thống song song thay thế `besttime-crypto`. Các thành phần mới phải gắn vào các contract hiện có:

```text
Historical/Realtime Data
  -> normalized point-in-time dataset
  -> feature snapshot
  -> raw strategy/model prediction
  -> final causal/risk/portfolio decision
  -> AutoTrader.build_entry_decision()
  -> immutable EntryDecision evidence
  -> ExecutionAgent
  -> ExecutionEngine.submit_paper()
  -> execution/fill/ledger/reconciliation
  -> outcome linkage
  -> evaluation and model/strategy comparison
```

Các module hiện có tiếp tục là owner của trách nhiệm tương ứng:

| Trách nhiệm | Thành phần hiện tại làm gốc |
| --- | --- |
| Phân tích 15m và MTF | `MarketAnalystAgent`, `analysis/core.py` |
| Signal score và meta confidence | `signal_score.py`, ML ensemble |
| Causal context | `CausalContextBridge`, `WorldState`, `CausalGate` |
| Risk/portfolio | `RiskManagerAgent`, `PortfolioManagerAgent` |
| Entry cuối | `AutoTrader.build_entry_decision()` và `EntryDecision` |
| Paper execution | `ExecutionAgent`, `ExecutionEngine.submit_paper()` |
| Evidence/lineage | `RuntimeEvidenceStore` |
| Position outcome | position tracker, ledger và reconciliation hiện có |
| Backtest/replay | các script backtest/HMR hiện có, được chuẩn hóa dần |

### 2.2. Dữ liệu lịch sử dùng để nghiên cứu; realtime dùng để kiểm chứng vận hành

- Dữ liệu giá có thể backfill thì phải backfill, không chờ nhiều ngày chỉ để tích lũy lại.
- Collector realtime chỉ cần cho dữ liệu không thể tái tạo trung thực từ quá khứ, đo latency/availability, và phát hiện drift.
- Milestone 24 giờ/7 ngày không được dùng để kết luận chiến lược có hiệu quả.
- Paper soak phải có thời hạn, câu hỏi đo lường và tiêu chí dừng cụ thể.

### 2.3. So sánh kinh tế trước khi tăng độ phức tạp

- Baseline đơn giản phải được chạy trước mô hình phức tạp.
- Mọi kết quả dùng **net return sau phí, spread, slippage và funding**.
- Không promote vì accuracy/AUC đơn lẻ.
- Không promote ứng viên chỉ thắng trên một symbol, một hướng lệnh hoặc một fold.
- RL Exit chỉ được ưu tiên khi entry strategy đã có edge OOS dương và simulator đủ trung thực.

### 2.4. Edge tổng hợp không phải bằng chứng thị trường

TimeGAN, bootstrap, perturbation và scenario generation được dùng để:

- stress test;
- kiểm tra độ nhạy;
- tạo rare-event scenarios;
- kiểm tra code path.

Chúng không được dùng làm bằng chứng duy nhất rằng một chiến lược có edge thật. Promotion bắt buộc dựa trên dữ liệu thị trường point-in-time và OOS chưa dùng để chọn chiến lược.

### 2.5. Tối ưu hiệu năng theo số đo

- Benchmark trước khi tối ưu.
- Tách CPU time, wall time, I/O, memory và contention.
- Ghi lại điều kiện máy khi benchmark vì máy không chạy riêng một process.
- Dùng median/p95 qua nhiều lần chạy; không kết luận từ một lần đo.
- Ưu tiên caching, vectorization, incremental computation và tránh đọc lại toàn bộ dữ liệu.

## 3. Phạm vi sản phẩm

### 3.1. Trong phạm vi

- Paper/demo trading.
- Historical OHLCV và market context.
- Multi-timeframe strategies.
- ML entry/meta-labeling/calibration.
- Rule-based và ML-based exits; RL exit ở shadow cho đến khi đủ bằng chứng.
- Risk, portfolio allocation, sizing và event-risk overlays.
- Historical news/event intelligence có point-in-time timestamps.
- Backtest, walk-forward, replay, experiment registry và evidence linkage.
- Benchmark hiệu năng và tối ưu research throughput/runtime latency.

### 3.2. Ngoài phạm vi

- Cấp API key có quyền real order.
- Mainnet execution bằng tiền thật.
- Những thay đổi security chỉ có ý nghĩa đối với real trading.
- Tối ưu UI không phục vụ nghiên cứu, paper operation hoặc đọc kết quả.
- Chạy collector vô thời hạn mà không gắn với một hypothesis hay acceptance gate.

## 4. Trạng thái xuất phát và khoảng trống

### 4.1. Năng lực đã có

- Pipeline multi-agent từ market analysis đến execution.
- Indicator và signal rules hiện tại.
- MTF 15m/1h/4h/1d.
- ML ensemble, meta confidence và artifact lineage.
- Causal world state/context framework.
- Risk/portfolio/sizing components.
- Paper execution, position tracking và outcome linkage framework.
- Historical/backtest scripts, HMR experiments và research artifacts.
- Alternative data collectors/features.
- Runtime evidence store và paper provenance.

### 4.2. Khoảng trống ưu tiên

1. P0 decision/evidence path chưa được nghiệm thu hoàn toàn.
2. Các backtest/script chưa dùng một experiment contract thống nhất.
3. Dataset chưa có một manifest point-in-time đầy đủ cho mọi feature.
4. Chưa có strategy registry chuẩn để so sánh nhiều chiến lược công bằng.
5. News/event historical data chưa được tích hợp theo availability timestamp.
6. Kết quả nghiên cứu cũ có nguy cơ selection bias và post-hoc tuning.
7. Paper uptime đang bị nhầm với bằng chứng hiệu quả kinh tế.
8. Benchmark runtime có thể bị nhiễu bởi workload khác trên máy.

## 5. Kiến trúc đích

```text
                        DATA PLANE
  Exchange history  Alternative data  News/events  Funding/OI/Macro
          \              |                |              /
           -> Raw immutable store + source/availability timestamps
                              |
                   Point-in-time normalizer
                              |
                  Multi-timeframe aligned store
                              |
                    Feature snapshot builder
                              |
        +---------------------+----------------------+
        |                     |                      |
  Rule strategies      ML/meta-labeling       Event-aware overlays
        |                     |                      |
        +---------------------+----------------------+
                              |
                    Candidate prediction
                              |
              Causal -> Risk -> Portfolio -> Sizing
                              |
                    Canonical EntryDecision
                              |
             Backtest simulator / deterministic replay
                              |
                     Paper execution parity
                              |
                 Fill -> ledger -> reconciliation
                              |
                    Linked economic outcome

                       CONTROL PLANE
  Dataset manifest -> Experiment registry -> Artifact registry
       -> Walk-forward/OOS gates -> Promotion/rejection record
       -> Performance benchmark -> Drift/health monitoring
```

## 6. Workstream A — Đóng P0: tính đúng của decision và paper execution

### Mục tiêu

Chứng minh risk, portfolio, sizing và event policy thật sự thay đổi paper order cuối; mọi decision và execution attempt có lineage đọc ngược được.

### Công việc

1. Hoàn tất migration `RuntimeEvidenceStore` và các test đang lỗi.
2. Bảo đảm evidence write atomic, idempotent và phát hiện tamper.
3. Hoàn tất P0-A risk/portfolio propagation.
4. Hoàn tất P0-B shared event-risk contract.
5. Thực hiện P0-C execution-time recheck tại `submit_paper()`:
   - reload decision/evidence;
   - kiểm tra TTL và policy/state version;
   - kiểm tra risk restriction mới;
   - kiểm tra remaining risk budget;
   - không chặn reduce/exit.
6. Thực hiện P0-D event snapshot producer nhưng chưa cần live news broker:
   - input fixture/historical event store;
   - deterministic snapshot generation;
   - versioned policy;
   - zero network trong replay test.
7. Test xuyên suốt:
   - risk block tạo 0 entry;
   - portfolio weight thay đổi quantity;
   - event block/reduce thay đổi decision;
   - stale decision bị execution từ chối;
   - exit/reduce luôn được phép;
   - fill/outcome liên kết đúng prediction/final/entry/execution IDs.

### Đầu ra

- Contract và schema version đã khóa.
- Full lineage readback.
- End-to-end invariant suite.
- Báo cáo những dynamic relationships chưa resolve.

### Gate A0 — P0 closure

- Không còn test P0 fail.
- Không silent-drop evidence.
- Không duplicate/conflicting final decision.
- Không paper entry khi risk/event gate block.
- Replay cùng input/timestamp cho cùng decision và hash.
- Chưa qua gate này thì không thêm chiến lược mới vào production paper path.

## 7. Workstream B — Baseline và experiment contract

### Mục tiêu

Tạo một chuẩn so sánh duy nhất để biết thay đổi mới có thực sự tốt hơn hệ thống cũ.

### Công việc

1. Đóng băng baseline hiện tại:
   - code commit;
   - strategy config;
   - symbol universe;
   - timeframe;
   - fee/slippage/funding model;
   - dataset manifest;
   - seed và artifact hashes.
2. Chuẩn hóa `ExperimentSpec`:
   - experiment ID;
   - strategy/model version;
   - feature set version;
   - train/validation/test windows;
   - symbols/timeframes;
   - cost model;
   - labeling contract;
   - hyperparameters;
   - random seed;
   - code/data hashes.
3. Chuẩn hóa `ExperimentResult`:
   - gross/net returns;
   - trade count và exposure time;
   - expectancy và profit factor;
   - drawdown, Sharpe, Sortino, Calmar;
   - turnover, fees, slippage, funding;
   - MFE/MAE, holding time, timeout ratio;
   - breakdown theo asset, side, regime, session và fold;
   - bootstrap confidence intervals.
4. Tạo strategy registry và runner chung.
5. Chuyển dần các HMR/backtest scripts sang adapter dùng runner chung; không xóa script cũ trước parity test.

### Baseline bắt buộc

- Buy-and-hold theo asset.
- Always-flat/no-trade.
- Random entry với cùng trade frequency/holding distribution.
- Simple trend: SMA/EMA.
- Simple mean reversion: RSI/Bollinger.
- Hệ thống 7-layer hiện tại.
- Candidate lịch sử tốt nhất nhưng đã khóa trước OOS mới.

### Gate B0 — Baseline reproducibility

- Chạy lại cùng spec cho cùng result trong tolerance đã định.
- Mọi metric truy ngược được tới trade/fill records.
- Baseline report được tạo tự động, không copy tay.

## 8. Workstream C — Historical data lake và dataset tái tạo được

### Mục tiêu

Thu thập tối đa dữ liệu có thể lấy từ quá khứ để nghiên cứu nhanh, thay vì chờ realtime không cần thiết.

### 8.1. Dữ liệu bắt buộc

#### Market data

- OHLCV: 1m, 5m, 15m, 1h, 4h, 1d nếu nguồn hỗ trợ.
- Spot/futures price basis.
- Funding rate.
- Open interest.
- Mark/index price.
- Bid/ask hoặc spread proxy nếu có lịch sử.
- Volume, taker buy/sell volume và liquidation nếu nguồn cho phép.

#### Context data

- BTC dominance và total crypto market cap.
- Fear & Greed.
- DXY, VIX, SPX/Nasdaq, yields và lịch macro.
- ETF flows.
- Stablecoin supply/flows.
- Exchange netflow, whale/on-chain proxies.

#### News/event data

- headline/body hoặc normalized summary;
- source và source ID;
- `published_at`;
- `first_seen_at`/`ingested_at`;
- `effective_at`;
- revision/update timestamps;
- affected symbols/sectors;
- event taxonomy;
- sentiment, relevance, novelty và surprise;
- deduplication cluster;
- source reliability/confidence;
- raw payload hash và parser version.

### 8.2. Point-in-time contract

Mỗi feature phải có:

```text
event_time       = thời điểm sự kiện xảy ra
published_at     = thời điểm nguồn công bố
available_at     = thời điểm hệ thống có thể biết dữ liệu
ingested_at      = thời điểm collector ghi nhận
revised_at       = thời điểm bản sửa xuất hiện
source_version   = phiên bản nguồn/parser
```

Training/replay chỉ được đọc record có `available_at <= decision_time`.

### 8.3. Storage và manifest

- Raw layer bất biến.
- Normalized layer theo schema version.
- Curated feature layer theo feature-set version.
- Ưu tiên format columnar/partitioned cho historical scans.
- Partition ít nhất theo source/symbol/timeframe/date.
- Manifest ghi coverage, gaps, duplicates, timezone, checksum và provenance.
- Không đưa generated artifacts lớn hoặc raw datasets vào Git nếu không phải fixture nhỏ.

### 8.4. Quy trình backfill

1. Inventory nguồn và giới hạn lịch sử.
2. Backfill theo symbol/time range có checkpoint.
3. Validate monotonic timestamps, duplicates và OHLC invariants.
4. Phát hiện gaps; retry có giới hạn.
5. Chuẩn hóa timezone UTC.
6. Align multi-timeframe bằng candle đã đóng.
7. Tạo availability timestamps cho từng source.
8. Sinh manifest và quality report.
9. Chỉ dùng live collector để nối phần đuôi hoặc nguồn không backfill được.

### Gate C0 — Dataset readiness

- Coverage và gap rate đạt threshold định trước.
- Zero future leakage trong automated tests.
- Dataset build từ raw + manifest cho hash giống nhau.
- Không dùng forward-fill qua khoảng mà dữ liệu chưa available nếu không có missingness flag.

## 9. Workstream D — Feature và label factory

### Mục tiêu

Tạo cùng một feature/label contract cho training, backtest và paper inference.

### Feature groups

1. Technical: returns, volatility, trend, momentum, volume, range, SFP.
2. MTF: 15m state kết hợp 1h/4h/1d đã đóng.
3. Cross-asset: BTC/ETH lead-lag, dominance, correlation, dispersion.
4. Derivatives: funding, basis, OI, liquidation pressure.
5. Alternative: ETF/on-chain/stablecoin/macro.
6. News/event: event type, sentiment, surprise, time-since-event, decay.
7. Regime: trend/mean-reversion, volatility, liquidity và risk regime.
8. Portfolio state: current exposure, correlation, drawdown, remaining budget.

### Label families

- Forward net return ở nhiều horizon.
- Triple barrier sau chi phí.
- Side-specific `P(win | proposed trade)` cho meta-labeling.
- MFE/MAE và time-to-barrier.
- Exit action/value labels.
- Ranking label giữa candidates cùng timestamp.

### Kiểm soát leakage

- Chỉ dùng closed candles.
- MTF dùng last fully closed higher-timeframe bar.
- Purge samples bị overlap label horizon.
- Embargo giữa train và validation folds.
- Fit scaler/imputer/calibrator chỉ trong train fold.
- Alternative/news dùng availability time, không dùng bản revised tương lai.

### Gate D0 — Feature parity

- Batch training và deterministic replay tạo cùng feature hash.
- Paper snapshot dùng đúng schema/artifact version.
- Missingness được biểu diễn rõ, không tự biến missing thành tín hiệu zero.

## 10. Workstream E — Strategy laboratory

### Mục tiêu

Huấn luyện và đánh giá nhiều họ chiến lược trên cùng experiment contract.

### Strategy families

1. **Current baseline**: 7-layer + meta confidence.
2. **Trend following**: EMA/SMA/ADX/Chandelier, long/short riêng.
3. **Momentum/breakout**: range break, volume confirmation, volatility expansion.
4. **Mean reversion**: RSI/BB/SFP trong regime phù hợp.
5. **MTF confluence**: entry timeframe và HTF regime tách contract.
6. **Directional specialists**: BUY-only, SELL-only và asset-specific diagnostic; không promote nếu chỉ là post-hoc discovery.
7. **Cross-sectional ranking**: chọn top candidates thay vì threshold độc lập.
8. **Event-aware**: block/reduce/decay quanh event, không để news model trực tiếp khuếch đại risk chưa kiểm soát.
9. **ML meta-labeling**: model quyết định accept/reject/size trên raw strategy proposal.
10. **Portfolio overlay**: correlation/risk-parity/MVO với constraints thực tế.
11. **Exit variants**: fixed barrier, trailing ATR, time stop, rule exit; RL shadow sau cùng.

### Trình tự thử nghiệm

1. Chạy rule baseline.
2. Thực hiện ablation từng feature/gate.
3. Chạy simple statistical/linear models.
4. Chạy tree/boosting ensembles.
5. Calibrate probability.
6. Chạy regime-specific hoặc mixture-of-experts nếu simple model không đủ.
7. Chạy event/news overlay.
8. Chỉ chạy RL exit sau khi simulator và entry edge đạt gate.

### Nguyên tắc chống overfit

- Pre-register hypothesis và primary metric.
- Giới hạn search budget.
- Lưu toàn bộ candidates, kể cả candidates thất bại.
- Điều chỉnh multiple comparisons khi thử nhiều biến thể.
- Không tái sử dụng OOS đã bị “burned” để promote.
- Kết quả post-hoc chỉ tạo hypothesis cho window mới.

## 11. Workstream F — Training và model governance

### Training pipeline

```text
DatasetManifest
  -> split plan
  -> fold-local preprocessing
  -> train
  -> calibration
  -> fold evaluation
  -> economic replay after costs
  -> artifact + model card
  -> registry candidate
```

### Mô hình ưu tiên

1. Logistic/linear baselines.
2. Random Forest/Extra Trees.
3. LightGBM/XGBoost/CatBoost nếu dependency hiện có.
4. Ensemble chỉ khi incremental OOS gain đủ lớn so với complexity/latency.
5. Sequence model chỉ khi chứng minh lợi ích hơn engineered lag features.
6. RL exit chỉ ở shadow cho đến khi net PnL tốt hơn rule exit qua nhiều folds.

### Model card bắt buộc

- Training dataset hash và coverage.
- Feature schema/hash.
- Label definition.
- Split/fold windows.
- Hyperparameters và seed.
- Calibration method.
- OOS metrics và confidence intervals.
- Failure regimes.
- Latency/memory benchmark.
- Artifact hash và compatible runtime schema.

### Gate F0 — Candidate model

- Tốt hơn baseline về primary net metric.
- Không giảm nghiêm trọng tail risk/drawdown.
- Calibration đủ dùng cho sizing.
- Improvement tồn tại trên nhiều folds và không do một symbol duy nhất.
- Inference latency nằm trong budget.

## 12. Workstream G — Honest validation và promotion

### Validation design

1. Anchored hoặc rolling walk-forward.
2. Purged/embargoed splits.
3. Final frozen OOS chưa dùng để chọn feature/hyperparameter.
4. Bootstrap confidence intervals theo trade/day block.
5. Sensitivity với fee, spread, slippage và latency.
6. Regime/asset/side/session breakdown.
7. Stress test gaps, stale data và missing features.

### Promotion scorecard

| Nhóm | Chỉ số chính |
| --- | --- |
| Lợi nhuận | net return, expectancy, profit factor |
| Risk | max drawdown, CVaR/tail loss, Calmar |
| Ổn định | fold dispersion, asset/side concentration |
| Chi phí | turnover, fees, slippage, funding |
| Khả thi | trade count, capacity proxy, latency |
| Xác suất | calibration/Brier/ECE nếu dùng probability |
| Lineage | 100% predictions/decisions/outcomes linked |

### Quyết định

- `REJECTED`: không vượt baseline hoặc không ổn định.
- `RESEARCH_ONLY`: có tín hiệu nhưng bằng chứng chưa đủ.
- `SHADOW`: chạy parity, không ảnh hưởng paper orders.
- `PAPER_CANDIDATE`: cho phép tạo paper decisions có giới hạn.
- `PAPER_CHAMPION`: thắng champion hiện tại qua gate định trước.

Không có trạng thái real-trade trong kế hoạch này.

## 13. Workstream H — News và Event Intelligence

### Mục tiêu

Dùng thông tin sự kiện như một feature/overlay point-in-time, không dùng LLM summary như ground truth.

### Pipeline

```text
Historical/live sources
  -> raw article/event record
  -> timestamp normalization
  -> deduplication/event clustering
  -> entity/symbol linking
  -> taxonomy + sentiment + surprise + relevance
  -> confidence and decay
  -> EventRiskDecision / model features
  -> replay and ablation
```

### Taxonomy tối thiểu

- Macro/Fed/inflation/jobs.
- Regulation/legal.
- ETF/institutional flows.
- Exchange/custody/stablecoin incidents.
- Protocol exploit/outage.
- Listing/delisting/token unlock.
- Company/project announcement.
- Geopolitical/risk-off.

### Thí nghiệm bắt buộc

1. Baseline không news.
2. News sentiment đơn giản.
3. Event taxonomy + decay.
4. Event risk block/reduce overlay.
5. Full model với news features.
6. Ablation theo source và event type.

### Gate H0 — News value

- Incremental OOS gain sau chi phí.
- Gain không chỉ đến từ một event hiếm.
- Không look-ahead từ article revision/late ingestion.
- Nếu news không cải thiện, giữ làm risk overlay hoặc loại bỏ khỏi entry model.

## 14. Workstream I — Deterministic replay và paper validation

### Replay trước paper soak

Replay phải chạy toàn bộ production decision path bằng historical snapshots:

- cùng feature builder;
- cùng artifact;
- cùng causal/risk/portfolio policy;
- cùng EntryDecision contract;
- cùng execution-time recheck;
- deterministic clock;
- simulated fill/cost model;
- full evidence readback.

### Paper/demo validation chỉ đo

- Data arrival và missingness thực tế.
- Feature/inference parity.
- End-to-end latency.
- Order/fill/ledger/reconciliation correctness.
- Fee/slippage model error.
- Prediction và calibration drift.
- Operational uptime/recovery.

### Không dùng paper soak để khẳng định

- Edge thống kê nếu sample quá nhỏ.
- Strategy superiority nếu không có benchmark/control.
- Generalization chỉ vì process chạy đủ 24 giờ/7 ngày.

### Thiết kế soak

- Bounded duration hoặc bounded sample count.
- Có checkpoint và stop condition.
- Có champion/challenger shadow song song trên cùng market snapshots.
- Không cần treo một agent/chat; dùng scheduler/supervisor rồi audit tại mốc.

### Gate I0 — Paper parity

- Zero unexplained decision mismatch với replay.
- Zero orphan fill/outcome.
- Latency và resource usage trong budget.
- Slippage/cost residual được đo và cập nhật vào backtest.
- Đủ sample mới đánh giá drift; không thay thế OOS economic gate.

## 15. Workstream J — Hiệu năng và hiệu quả tài nguyên

### Benchmark contract

Mỗi benchmark ghi:

- CPU/model máy và RAM;
- Python/library versions;
- số process khác và system load;
- dataset size/cache state;
- warm/cold run;
- wall time, CPU time, peak RSS, I/O bytes;
- median/p95 qua nhiều repetitions.

### Tối ưu theo thứ tự

1. Loại bỏ đọc/parse lặp lại.
2. Cache feature theo dataset/feature hash.
3. Incremental indicator/MTF updates.
4. Vectorize hot paths.
5. Partition pruning và columnar reads.
6. Parallelize theo fold/symbol/strategy khi không tranh chấp I/O.
7. Batch inference.
8. Profile rồi mới thay framework/thư viện.

### KPI đề xuất

- Historical dataset build throughput.
- Feature rows/second.
- Backtest candles/second và trades/second.
- Training time/fold.
- Inference p50/p95.
- Peak memory.
- Evidence write p50/p95 và lock wait.
- Full experiment cost/time.

### Gate J0 — Performance

- Không regression vượt budget so với baseline benchmark.
- Kết quả trước/sau tối ưu giống nhau về semantics/hash hoặc trong tolerance đã khóa.
- Benchmark report nêu rõ nhiễu do workload ngoài process.

## 16. Workstream K — Observability và research operations

### Dashboard tối thiểu

- Dataset freshness/coverage/gaps.
- Experiment queue/status.
- Champion/challenger metrics.
- Paper parity and drift.
- Latency/resource metrics.
- Evidence lineage completeness.
- Rejection reasons và gate counts.

### Runbooks

- Backfill/retry.
- Dataset rebuild.
- Experiment reproduction.
- Artifact promotion/rollback.
- Evidence migration/quarantine.
- Paper collector/supervisor recovery.
- Stop an experiment/collector without orphan processes.

## 17. Thứ tự milestone

| Milestone | Nội dung | Điều kiện bắt đầu | Điều kiện hoàn tất |
| --- | --- | --- | --- |
| M0 | Đóng P0 correctness | Ngay | P0 invariant suite xanh |
| M1 | Freeze baseline/experiment contract | M0 | Baseline tái lập được |
| M2 | Historical data inventory/backfill | Có thể chuẩn bị song song read-only | Dataset manifest đạt gate |
| M3 | Feature/label factory | M1 + M2 schema | Training/replay parity |
| M4 | Strategy laboratory | M3 | Candidate comparison report |
| M5 | Walk-forward/frozen OOS | M4 | Promotion dispositions |
| M6 | Historical news/event layer | M2 point-in-time contract | Incremental-value verdict |
| M7 | Production-path deterministic replay | M0 + promoted candidate | Zero unexplained mismatch |
| M8 | Bounded paper champion/challenger | M7 | Parity/cost/drift report |
| M9 | Performance optimization | Benchmark có từ M1-M8 | KPI đạt, zero semantic drift |
| M10 | Iterative research loop | M8 | Chu kỳ versioned, tái lập được |

M2 inventory/backfill có thể chuẩn bị song song với M0, nhưng dữ liệu đó không được đưa vào production decision path trước khi P0 đóng.

## 18. Backlog thực thi theo ưu tiên

### P0 — Làm ngay

- [ ] Sửa hai test/migration lỗi còn lại trong P0-B.
- [ ] Loại thay đổi ngoài phạm vi che lỗi fingerprint.
- [ ] Chứng minh migration không mất raw quarantined evidence.
- [ ] Chốt semantics corruption/quarantine/health.
- [ ] Hoàn tất P0-C execution-time recheck.
- [ ] Hoàn tất P0-D deterministic event snapshot producer.
- [ ] Chạy end-to-end risk-to-paper-outcome suite.

### P1 — Nền nghiên cứu

- [ ] Định nghĩa `ExperimentSpec`, `ExperimentResult`, strategy registry.
- [ ] Freeze current champion baseline.
- [ ] Inventory toàn bộ historical sources và coverage.
- [ ] Chọn canonical raw/normalized/curated storage layout.
- [ ] Viết point-in-time dataset manifest.
- [ ] Chuẩn hóa cost/slippage/funding model.

### P2 — Tạo và so sánh candidates

- [ ] Backfill market/derivatives/context data.
- [ ] Xây feature/label factory.
- [ ] Port baseline strategies vào common runner.
- [ ] Chạy ablations và strategy families.
- [ ] Train/calibrate simple models trước ensemble.
- [ ] Tạo walk-forward và frozen OOS reports.

### P3 — Event/news và paper parity

- [ ] Backfill historical events/news có availability timestamps.
- [ ] Xây event taxonomy/entity linking/deduplication.
- [ ] Chạy news ablations.
- [ ] Replay candidate qua production decision path.
- [ ] Chạy bounded champion/challenger paper soak.

### P4 — Tối ưu và vận hành lặp

- [ ] Profile/caching/vectorization/partition pruning.
- [ ] Experiment queue và reporting automation.
- [ ] Drift/cost residual monitoring.
- [ ] Versioned retraining/revalidation schedule.

## 19. Definition of Done cho toàn chương trình

Chương trình được xem là hoàn tất khi:

1. Có ít nhất một candidate vượt baseline hiện tại trên frozen OOS sau chi phí với uncertainty được báo cáo.
2. Kết quả không phụ thuộc quá mức vào một symbol, side, fold hoặc event.
3. Dataset, features, model và experiment có hashes/version đầy đủ.
4. Replay production path khớp research decision semantics.
5. Paper execution có zero unexplained lineage/reconciliation gaps.
6. Paper metrics xác nhận parity và cost assumptions, không bị dùng thay OOS evidence.
7. Full experiment có thể tái chạy từ manifest và tạo cùng disposition.
8. Runtime/research throughput đạt budget trên máy dùng chung, với benchmark đã kiểm soát nhiễu.
9. Hệ thống vẫn chỉ hoạt động ở paper/demo; không phát sinh real-trade enablement.

## 20. Báo cáo bắt buộc cho mỗi milestone

Mỗi milestone phải tạo một report gồm:

- mục tiêu/hypothesis;
- phạm vi và thay đổi;
- dữ liệu/artifact/code versions;
- commands đã chạy;
- test count và exit codes thực tế;
- economic metrics và confidence intervals;
- performance metrics và điều kiện benchmark;
- failed candidates/negative evidence;
- unresolved risks/dynamic relationships;
- quyết định `PASS`, `FAIL`, `RESEARCH_ONLY` hoặc `BLOCKED`;
- bước tiếp theo duy nhất có priority cao nhất.

Không dùng các câu như “hệ thống chạy ổn định” hoặc “test xanh” làm kết luận về hiệu quả chiến lược nếu không có so sánh kinh tế OOS tương ứng.

