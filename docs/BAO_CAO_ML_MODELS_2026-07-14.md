# Báo cáo các mô hình ML trong hệ thống

**Ngày rà soát ban đầu:** 14/07/2026
**Cập nhật tài liệu:** 17/07/2026
**Phạm vi:** mã nguồn, cấu hình và artifact có trong workspace. Báo cáo phân biệt rõ mô hình đang được gọi lúc chạy với mô hình thử nghiệm/huấn luyện để không nhầm kết quả nghiên cứu là production.

## Tóm tắt điều hành

Hệ thống hiện có ba mô hình học máy có artifact production/shadow:

| Nhóm | Mô hình | Trạng thái sử dụng | Vai trò |
|---|---|---|---|
| Quyết định vào lệnh | Ensemble Meta Model v3.1 | **Đang gọi ở runtime** | Ước lượng xác suất tín hiệu thắng và các chỉ số EV/TP/SL |
| Chấm điểm bổ trợ | Adaptive Random Forest | **Production, canonical artifact path đã thống nhất** | Bổ sung xác suất/position sizing cho `signal_score` |
| Quản lý thoát lệnh | Recurrent PPO (LSTM) | **Shadow/advisory**; active action vẫn bị guard | Gợi ý giữ/thoát/chốt một phần/dời SL |

Ngoài ra có TimeGAN để tạo dữ liệu OHLCV tổng hợp phục vụ huấn luyện RL; các checkpoint của nó tồn tại nhưng không nằm trên luồng ra quyết định live. Các artifact DQN, A2C và Meta Model v3 cũng tồn tại, nhưng hiện không được loader production dùng. Mô hình LightGBM dự báo slippage được thiết kế nhưng artifact chưa có, nên hệ thống đang fallback công thức rule-based.

Trạng thái vận hành cập nhật 17/07/2026:

```text
Runtime linkage/calibration framework: IMPLEMENTED
Gate A evidence from fresh paper runtime: PENDING
Shadow evidence window: NOT STARTED
Runtime calibration readiness: BLOCKED
Meta promotion readiness: BLOCKED
Live trading: DISABLED
```

## 1. Ensemble Meta Model v3.1 — mô hình xác suất thắng chính

- **Mã nguồn / artifact:** `btc_scraper/ml_engine/meta_model.py`; `logs/meta_model.joblib`; metadata tại `logs/meta_model.json`.
- **Điểm gọi runtime:** `btc_scraper/ml_engine/decision_engine.py`, `btc_scraper/ml_engine/signal_score.py`, `btc_scraper/trading/position_tracker.py`, dashboard và backtest đều gọi `predict_meta_confidence()`.
- **Bài toán:** phân loại nhị phân `WIN`/`LOSS` cho một tín hiệu. Output chính là `probability` (xác suất thắng); code còn suy ra expected return, drawdown, thời gian giữ, xác suất TP1/TP2/SL và EV từ cấu hình TP/SL.
- **Dữ liệu:** `logs/adaptive_signals_v2.json`, sắp xếp theo thời gian. Artifact hiện có **24.070** mẫu, **43** biến; nhãn gồm 11.413 WIN và 12.657 LOSS.
- **Đặc trưng:** nhóm score kỹ thuật (RSI, MACD, cấu trúc), volatility/ATR, Fear & Greed, đồng thuận đa khung thời gian, returns 15m–1d, slope EMA/SMA, support/resistance, market structure, volume-flow (OBV/CMF/MFI), ROC/HV và sentiment trend. Danh sách đầy đủ được lưu trong `logs/meta_model.json`.
- **Kiến trúc:** voting ensemble xác suất của LightGBM, CatBoost và XGBoost. RandomForest không có trong artifact v3.1 hiện tại. Tuning dùng Optuna; hyperparameter mặc định 200 trees/iterations, depth khoảng 5, learning rate 0,03 trước tuning.
- **Trọng số artifact hiện tại:** XGBoost **54,84%**, CatBoost **43,60%**, LightGBM **1,56%**. Cả ba backend đều đã khả dụng khi train artifact này.
- **Calibration:** Isotonic, tách theo thời gian 70% train / 15% calibration / 15% test (16.849 / 3.610 / 3.611 mẫu). Isotonic được chọn với mean bucket error 7,36 điểm %.
- **Đánh giá lưu kèm artifact:** base CV ROC-AUC **0,6160 ± 0,0192**; ensemble CV ROC-AUC **0,6253**, accuracy **0,5880**. Hai cửa sổ walk-forward cho AUC **0,6179** và **0,6382**.

**Cảnh báo chất lượng.** Calibration tốt ở vùng 0,4–0,8, nhưng hai tail chưa tốt: bucket 0,0–0,4 lệch +14,6 điểm % và 0,8–1,0 lệch −15,7 điểm %, với số mẫu chỉ 35 ở tail cao. Không nên hiểu xác suất cực trị là xác suất đã được hiệu chuẩn tốt. Đây là mô hình production cần ưu tiên giám sát drift và calibration theo bucket.

## 2. Adaptive Random Forest — scorer/position sizing bổ trợ

- **Mã nguồn:** `btc_scraper/ml_engine/adaptive_scoring.py`; runtime loader nằm trong `btc_scraper/ml_engine/signal_score.py`.
- **Artifact canonical:** `logs/adaptive_model.joblib`, khai báo trong `config/model_artifacts.yaml`; metadata tại `logs/adaptive_model.metadata.json`.
- **Bài toán:** phân loại xác suất thắng từ dữ liệu giao dịch đã đóng; được dùng như lớp bổ trợ khi chấm tín hiệu và position sizing, rồi Meta Model vẫn được gọi tiếp.
- **Kiến trúc code hiện hành:** `RandomForestClassifier(n_estimators=200, max_depth=6, class_weight="balanced", random_state=42)`. Validation trong hàm trainer là `StratifiedKFold(5)` và chỉ lưu model khi CV ROC-AUC >= **0,55**.
- **Input:** `records_to_dataset()` từ feature extractor; phiên bản train 18 tháng có 14 biến: signal score, RSI, MACD histogram, ATR%, volume ratio, Fear & Greed, EMA distance, BB width, ADX, MTF alignment và bốn trạng thái regime.
- **Kết quả train có lưu (`logs/train_report.json`, 13/06/2026):** 18.800 mẫu, 15.040 train, 3.760 holdout; CV ROC-AUC **0,6165 ± 0,0101**, holdout ROC-AUC **0,6461**, accuracy train 63,02%.
- **Artifact:** `logs/adaptive_model.joblib` (artifact production canonical). Legacy duplicate under `btc_scraper/logs/` đã được loại khỏi candidate runtime theo remediation report.

**Cập nhật tích hợp 17/07/2026.** Rủi ro loader đọc nhầm artifact đã được xử lý bằng `config/model_artifacts.yaml` và `ArtifactResolver`. Adaptive RF hiện dùng chung canonical path `logs/adaptive_model.joblib` cho training/runtime, validate metadata/SHA/schema và fail-closed nếu artifact không hợp lệ.

Artifact JSON `logs/adaptive_model.json` chỉ là mapping bucket score→win rate (không phải một model học máy hoàn chỉnh); số liệu hiện có rất thưa, ví dụ bucket score 60 chỉ có win rate 0. Nó chỉ nên được xem là fallback thống kê.

## 3. RL Exit Manager — Recurrent PPO (LSTM)

- **Mã nguồn / loader:** `scripts/train_rl_exit_manager.py`; `btc_scraper/trading/position_tracker.py`.
- **Artifact runtime được chọn:** không còn chọn bằng filename glob mới nhất. Runtime dùng canonical PPO được hash-pin trong registry/config; trạng thái vận hành là `shadow`.
- **Kiến trúc:** `sb3_contrib.RecurrentPPO` (policy LSTM), khác với PPO feed-forward. State LSTM được cache theo coin tại `logs/rl_lstm_cache.pkl`.
- **Mục tiêu / output:** tối ưu quyết định thoát vị thế với 6 action: `HOLD`, `PARTIAL_CLOSE_50`, `MOVE_SL_TO_BREAKEVEN`, `TAKE_PROFIT`, `EXIT`, `TRAILING_SL_ATR`.
- **Observation lúc runtime:** code tạo vector **20** chiều gồm RSI, MACD histogram, ATR%, ADX, confidence vào lệnh, 8 one-hot regime, PnL, thời gian giữ, Fear & Greed, volume ratio, BB width, max drawdown và market correlation. Tài liệu evaluation cũ ghi state space 18, nên có drift giữa cấu hình đánh giá và runtime hiện hành; cần re-evaluate bằng observation 20 chiều trước khi promotion.
- **Dữ liệu huấn luyện:** nến lịch sử; trainer còn có thể nạp `data/rl_synthetic_candles.pkl` do TimeGAN tạo để curriculum learning. Giá trị reward là thay đổi PnL ròng sau commission/slippage.
- **Cấu hình run gần nhất:** 100.000 timesteps, learning rate 0,0003. Training mean reward **−2,3665 ± 0,8980**.
- **Đánh giá 100 episodes (`logs/phase_4_rl_report.json`):** PPO mean reward **−2,1499**, mean PnL **0,0643**. Baseline rule-based tốt hơn: mean reward **−1,8638**, mean PnL **0,1577**; delta PPO là **−0,2861** reward.

**Kết luận vận hành.** PPO hiện được load để đưa khuyến nghị ở shadow/advisory mode; action active vẫn bị guard và cần authorization riêng. Theo kết quả evaluation đã lưu, không có bằng chứng PPO vượt rule-based; tiếp tục giữ ở shadow/advisory mode thay vì cho phép nó tự thực thi lệnh thoát.

## 4. TimeGAN — sinh dữ liệu OHLCV cho RL

- **Mã nguồn:** `btc_scraper/ml_engine/timegan_model.py`, `timegan_trainer.py`, `timegan_generate.py`.
- **Artifact:** `models/autoencoder.pt`, `models/supervisor.pt`, `models/adversarial.pt`, cùng thời điểm 07/07/2026.
- **Mục tiêu:** tạo chuỗi OHLCV tổng hợp, không dự báo giá hoặc quyết định trade trực tiếp. Dữ liệu tạo ra dùng làm curriculum/augmentation cho huấn luyện RL.
- **Input / output:** sequence OHLCV 5 cột. Các module GRU mặc định: input 5, hidden 64, latent/noise 32.
- **Kiến trúc gồm 5 mạng:** Embedder + Recovery (autoencoder), Generator, Supervisor dự báo latent kế tiếp và Discriminator. Train 3 giai đoạn: autoencoder pre-training, supervisor supervised pre-training, rồi adversarial joint training.
- **Trạng thái runtime:** không có luồng main/position tracker tự động gọi generator. Trainer RL chỉ dùng dữ liệu TimeGAN nếu file pickle synthetic được nạp. Vì vậy đây là **training asset**, không phải model production live.

## 5. Các model/artifact tồn tại nhưng không phải production runtime

| Item | Trạng thái | Nhận xét |
|---|---|---|
| `logs/meta_model_v3.joblib` | Candidate/thử nghiệm | 99 features; test AUC 0,8382, accuracy 0,7607, Brier 0,1690. Script runtime vẫn import `meta_model.py` v3.1, không import `meta_model_v3.py`. Kết quả v3 cao bất thường so với v3.1 nên cần audit leakage/feature availability trước promotion. |
| DQN artifacts | Archive evaluation | Có `rl_exit_dqn_*.zip`; không có loader runtime. Evaluation: reward −2,2656, PnL 0,0641, kém baseline. |
| A2C artifacts | Archive evaluation | Có `rl_exit_a2c_*.zip`; không có loader runtime. Evaluation: reward −2,3118, PnL −0,0987, kém baseline. |
| LightGBM Slippage Model v2 | Chưa active | Code hỗ trợ 12 feature execution và sẽ load `slippage_model_v2.joblib`, nhưng artifact không tồn tại. `SlippagePredictor` đang fallback sang công thức v1, không phải ML. |
| Baseline Logistic Regression của Meta Model v3 | Chỉ benchmark | Được train trong `meta_model_v3.py` để so sánh, không được export/load làm runtime model. |

## 6. Các thành phần không nên gọi là ML model local

- **Gemini 2.5 Flash:** đây là LLM bên thứ ba được gọi qua `google-genai` để viết báo cáo phân tích tiếng Việt; mã gọi `client.models.generate_content(model="gemini-2.5-flash")`. Nó có trong luồng background của `main.py`, nhưng không phải artifact huấn luyện/lưu trong repo và không tham gia trực tiếp vào scoring/execution.
- **Causal World Model / anomaly detector:** `WorldModelPredictor` hiện áp dụng quan hệ từ causal graph và các heuristic cố định (ví dụ biến động BTC→ETH, funding, Fear & Greed). Nó không load trọng số hoặc fit estimator trong runtime; nên phân loại là engine rule/causal graph, không phải trained ML model.
- **Slippage v1, latency/cost models, Monte Carlo, technical indicators và portfolio allocation:** đều là công thức, mô phỏng hoặc tối ưu hoá định lượng; không phải supervised/RL model đã train.

## 7. Luồng dữ liệu và quyền quyết định

```text
OHLCV + MTF + sentiment + market structure
                 |
                 v
     Adaptive RF (nếu loader tìm thấy artifact) ──────┐
                 |                                    |
                 v                                    v
       Meta Ensemble v3.1 -> P(win), EV, TP/SL -> signal / sizing
                                                        |
                                                 vị thế đang mở
                                                        v
                                            Recurrent PPO -> exit suggestion
                                                        |
                                           rule guard / shadow mode / execution

TimeGAN -> synthetic OHLCV -> RL training only
Gemini 2.5 Flash -> narrative report only
```

## 8. Khuyến nghị ưu tiên

1. **Thu thập Gate A runtime evidence từ paper runner mới**: producer coverage report phải chứng minh linkage đủ trước khi start shadow evidence window.
2. **Giữ RL PPO ở shadow mode**: promotion chỉ sau khi đánh giá walk-forward/out-of-sample chứng minh vượt baseline rule-based, đặc biệt khi runtime observation đã đổi từ 18 sang 20 chiều.
3. **Giám sát Meta Model v3.1 theo bucket**: log Brier/calibration error, sample count, ROC-AUC rolling và PSI/drift; đặt guard đối với bucket <0,4 và >0,8 vì calibration hiện chưa đạt.
4. **Không promotion Meta Model v3 chỉ theo AUC hiện tại**: kiểm tra leakage theo thời gian, feature availability đúng thời điểm entry và split theo coin/time trước khi thay artifact `meta_model.joblib`.
5. **Duy trì traceability trong prediction log**: model path, artifact hash, feature schema version và calibration method phải đi cùng mỗi quyết định.

## Nguồn kiểm chứng trong repo

- `logs/meta_model.json`, `logs/meta_model_v3.json`, `logs/train_report.json`, `logs/rl_training_results.json`, `logs/phase_4_rl_report.json`.
- `config/model_artifacts.yaml`, `docs/remediation/System_Status_Report_2026-07-17.md`, `docs/remediation/System_Operational_Update_2026-07-17.md`.
- `btc_scraper/ml_engine/meta_model.py`, `adaptive_scoring.py`, `signal_score.py`, `timegan_model.py`, `timegan_trainer.py`.
- `btc_scraper/trading/position_tracker.py`, `btc_scraper/execution/slippage_predictor.py`, `scripts/train_rl_exit_manager.py`, `btc_scraper/ai_analyst/api.py`.
