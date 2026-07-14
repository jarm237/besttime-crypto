# Meta Model Retraining Data Inventory

Ngay 14/07/2026, bao cao nay tong hop cac nguon du lieu, artifact model, script train va khuyen nghi khi train lai meta score/model tu dau.

## Ket Luan Nhanh

He thong hien co du lieu tot de train lai, nhung can phan biet hai muc tieu:

- Train nhanh lai production model: dung `logs/adaptive_signals_v2.json`.
- Train lai tu dau dung nghia: rebuild dataset tu `data/fresh_training_data_2023_2026`, sau do moi train model.

Khong nen merge lai tu cac file `logs/adaptive_signals_v2_<COIN>.json` hien tai, vi cac file per-coin dang rong.

## Script Train Production Hien Tai

Production meta confidence hien duoc train boi:

```bash
python -m btc_scraper.ml_engine.meta_model --train --n 200
```

File lien quan:

- `btc_scraper/ml_engine/meta_model.py`
  - Input: `logs/adaptive_signals_v2.json`
  - Model output: `logs/meta_model.joblib`
  - Candidate output: `logs/meta_model_candidate.joblib`
  - Metrics: `logs/meta_model.json`
  - Feature importance: `logs/meta_feature_importance.json`
- `scripts/train_model_fast.py`
  - Wrapper train nhanh tren dataset da co.
- `scripts/build_and_train.py`
  - Pipeline build dataset + train, nhung can kiem tra lai loader truoc khi dung de rebuild tu raw OHLCV.

## Dataset Train Chinh

### `logs/adaptive_signals_v2.json`

Day la dataset chinh dang duoc production meta model dung.

Thong tin:

- Size: khoang 56.33 MB
- Samples: 24,070
- Coins: 21
- Time range: `2023-01-01 01:15` den `2026-06-15 10:30`
- Label distribution:
  - `WIN`: 11,413
  - `LOSS`: 12,657

Nhan xet:

- Nen dung lam baseline hoac train nhanh.
- Co schema phu hop voi `FEATURE_SCHEMA_V2`.
- Khong phai rebuild sach tu raw sau cac thay doi logic gan day, nen neu muc tieu la "from scratch" thi chi nen dung de doi chieu.

### `logs/adaptive_signals.json`

Dataset cu hon.

Thong tin:

- Samples: 19,018
- Time range: `2025-01-01 00:00` den `2026-06-13 04:45`
- Label distribution:
  - `LOSS`: 10,456
  - `WIN`: 8,552
  - `BREAKEVEN`: 10

Nhan xet:

- Chi nen dung de audit/doi chieu.
- Khong nen dung lam input train chinh cho production hien tai vi schema cu hon va co `BREAKEVEN`.

### `logs/adaptive_signals_backup.json`

Backup cua dataset cu.

Thong tin:

- Samples: 18,874
- Time range: `2025-01-01 00:00` den `2026-06-13 04:45`
- Label distribution:
  - `LOSS`: 10,390
  - `WIN`: 8,478
  - `BREAKEVEN`: 6

Khuyen nghi: giu de doi chieu, khong train production moi tu file nay.

### `data/ml_training_data.csv`

Dataset giao dich thu cong/small export.

Thong tin:

- Samples: 5
- Coins: `ZEC`, `BNB`, `NEAR`, `XLM`, `BTC`
- Time range: `2026-06-08 18:38` den `2026-06-09 12:33`
- Label distribution:
  - `LOSS`: 3
  - `WIN`: 2

Khuyen nghi: khong du de train meta model. Chi dung lam vi du schema hoac RAG/context nho.

## Raw OHLCV Co The Rebuild Tu Dau

Nguon raw tot nhat hien co:

```text
data/fresh_training_data_2023_2026/<COIN>/<COIN>_15m.csv
```

Thong tin:

- 21 coins
- Moi coin co 122,592 candles
- Moi file co cot: `time`, `open`, `high`, `low`, `close`, `volume`
- Time range moi coin: `2023-01-01 00:00` den `2026-06-30 23:45`
- Tong so candles: 2,574,432

Coins co du lieu:

```text
AEVO, AR, AVAX, BNB, BTC, DOGE, ENA, ETH, IOTA, NEAR,
SOL, SOPH, TAO, TRB, TRUMP, TRX, WLD, XLM, XPL, XRP, ZEC
```

Khuyen nghi:

- Day la nguon nen dung neu train lai tu dau dung nghia.
- Can rebuild lai labeled trades/signals tu raw OHLCV de dataset phan anh logic hien tai.
- Can kiem tra multi-timeframe. Thu muc hien tai chi thay file `15m`; neu builder can `1h`, `4h`, `1d` thi phai resample tu `15m` hoac fetch them.

## Feature Store / Phase 8-10

### `data/feature_store/training/ml_dataset_v3.parquet`

Dataset nang cao cho nhanh v3.

Thong tin:

- Rows: 24,070
- Columns: 205
- Timeframe: `15m`
- Label type: `triple_barrier_meta`
- Lookahead bars: 48
- Time range: `2023-01-01 01:15:00+00:00` den `2026-06-15 10:30:00+00:00`
- `meta_label` distribution:
  - `0`: 15,940
  - `1`: 8,130
- `triple_barrier_label` distribution:
  - `0`: 12,146
  - `-1`: 8,868
  - `1`: 3,056

File lien quan:

- `data/feature_store/labels/meta_labels.parquet`
- `data/feature_store/labels/triple_barrier_labels.parquet`
- `data/feature_store/labels/trade_quality_labels.parquet`
- `data/feature_store/derived/fracdiff_features.parquet`
- `data/feature_store/derived/cross_sectional_features.parquet`
- `data/feature_store/regime/regime_features.parquet`
- `data/feature_store/causal/causal_features.parquet`

Khuyen nghi:

- Nen tai su dung neu muon train nhanh v3/parquet.
- Chua phai production path mac dinh, vi production hien load `logs/meta_model.joblib` tu `meta_model.py`.
- Neu chon nhanh v3, can wire inference production sang model v3 hoac tao adapter tu output v3 ve `predict_meta_confidence()`.

## Model Artifacts Dang Co

Production va candidate:

- `logs/meta_model.joblib`
- `logs/meta_model_candidate.joblib`
- `logs/meta_model_backup.joblib`

Calibration/experiment:

- `logs/meta_model_baseline.joblib`
- `logs/meta_model_smote_sigmoid.joblib`
- `logs/meta_model_calibrated_70_20_10.joblib`
- `logs/meta_model_calibrated_periodic_20260711T190155Z.joblib`
- `logs/meta_model_calibrated_periodic_20260712T190010Z.joblib`
- `logs/meta_model_calibrated_periodic_20260713T190014Z.joblib`

Nhanh v3/parquet:

- `logs/meta_model_v3.joblib`

Adaptive model cu:

- `logs/adaptive_model.joblib`
- `btc_scraper/logs/adaptive_model.joblib`
- `logs/challenger/adaptive_model_20260707.joblib`
- `logs/challenger/adaptive_model_20260712.joblib`

Khuyen nghi:

- Giu `logs/meta_model.joblib` lam production baseline.
- Train model moi vao candidate/run folder truoc, khong overwrite production ngay.
- `adaptive_model.joblib` khong phai meta confidence production hien tai.

## Metrics Va Bao Cao Hien Co

File chinh:

- `logs/meta_model.json`
- `logs/meta_model_eval_results.json`
- `logs/meta_feature_importance.json`
- `logs/meta_model_agg_calibration.json`
- `logs/calibration_70_20_10.json`
- `logs/calibration_report_v3.json`
- `logs/recalibration_latest.json`

`logs/meta_model.json` hien ghi:

- Version: `v3.1`
- Samples: 24,070
- Features: 43
- CV AUC mean: khoang 0.616
- Ensemble CV AUC mean: khoang 0.625
- Calibration: isotonic
- Split:
  - Train: 16,849
  - Calibration: 3,610
  - Test: 3,611
- Label:
  - `WIN`: 11,413
  - `LOSS`: 12,657

`logs/meta_model_eval_results.json` hien ghi:

- ROC-AUC: 0.7868
- PR-AUC: 0.7468
- Brier: 0.1997
- Accuracy: 0.7133
- Features used: 41
- Samples: 23,959

Khuyen nghi:

- Dung cac file nay lam benchmark truoc/sau.
- Khong dung prediction logs/calibration logs lam supervised labels neu chua join voi ket qua that sau do.

## Prediction, Monitoring, Execution Logs

Co cac file:

- `logs/predictions_YYYY-MM-DD.log`
- `logs/meta_prob_entry_YYYY-MM-DD.log`
- `logs/daily/meta_prob_entry_YYYY-MM-DD.log`
- `data/execution/fills/*.jsonl`
- `logs/execution/*.jsonl`
- `logs/execution/paper/*.jsonl`

Khuyen nghi:

- Dung cho monitoring, drift analysis, calibration audit.
- Co the dung de build slippage/execution model.
- Khong nen dung truc tiep lam label meta score neu chua co outcome label ro rang.

## Rủi Ro Khi Rebuild Tu Dau

### File per-coin hien rong

Cac file dang rong:

```text
logs/adaptive_signals_v2_ADA.json
logs/adaptive_signals_v2_AEVO.json
logs/adaptive_signals_v2_AR.json
logs/adaptive_signals_v2_AVAX.json
logs/adaptive_signals_v2_BNB.json
logs/adaptive_signals_v2_BTC.json
logs/adaptive_signals_v2_DOGE.json
logs/adaptive_signals_v2_ENA.json
logs/adaptive_signals_v2_ETH.json
logs/adaptive_signals_v2_IOTA.json
logs/adaptive_signals_v2_LTC.json
logs/adaptive_signals_v2_NEAR.json
logs/adaptive_signals_v2_SOL.json
logs/adaptive_signals_v2_SOPH.json
logs/adaptive_signals_v2_TAO.json
logs/adaptive_signals_v2_TRB.json
logs/adaptive_signals_v2_TRUMP.json
logs/adaptive_signals_v2_TRX.json
logs/adaptive_signals_v2_WLD.json
logs/adaptive_signals_v2_XAUT.json
logs/adaptive_signals_v2_XLM.json
logs/adaptive_signals_v2_XPL.json
logs/adaptive_signals_v2_XRP.json
logs/adaptive_signals_v2_ZEC.json
```

Khong nen chay merge tu cac file nay neu chua rebuild lai, vi co nguy co tao dataset merged rong.

### Format raw data khac loader cu

Du lieu hien co:

```text
data/fresh_training_data_2023_2026/COIN/COIN_15m.csv
```

Mot so builder cu lai tim:

```text
data/fresh_training_data_2023_2026/YYYY_MM_COIN_15m.csv
```

Can sua loader hoac tao builder moi truoc khi rebuild from scratch.

### Logic score vua thay doi

He thong vua tach ro:

- `score`: directional score tren truc SELL-BUY
- `strength`: do manh tin hieu doc lap voi BUY/SELL

Neu rebuild dataset, nen dam bao record moi co field `strength` hoac feature extraction khong phu thuoc nham vao raw score cho threshold BUY/SELL.

## De Xuat Pipeline Train Lai

### Phuong an A: Train nhanh, it rui ro

Dung dataset production hien co:

```bash
python -m btc_scraper.ml_engine.meta_model --train --n 200
```

Phu hop khi:

- Can co model moi nhanh.
- Chua muon sua builder.
- Chap nhan dataset van la snapshot cu den `2026-06-15`.

Can lam:

- Backup `logs/meta_model.joblib`.
- Train ra candidate truoc neu co the.
- Chay eval/backtest so sanh voi production cu.

### Phuong an B: Rebuild tu dau dung nghia

De xuat:

1. Sua builder de doc duoc:

```text
data/fresh_training_data_2023_2026/COIN/COIN_15m.csv
```

2. Neu can MTF, resample/fetch:

```text
1h, 4h, 1d
```

3. Rebuild `logs/adaptive_signals_v2.json` tu raw OHLCV.

4. Luu dataset va manifest vao:

```text
logs/training_runs/<timestamp>/
```

5. Train candidate:

```bash
python -m btc_scraper.ml_engine.meta_model --train --n 200
```

6. Eval:

- Time split 70/15/15
- Walk-forward
- Calibration buckets
- Backtest threshold theo `strength`
- Compare candidate vs `logs/meta_model.joblib`

7. Chi promote neu candidate tot hon hoac khong regression qua nguong chap nhan.

### Phuong an C: Train nhanh v3/parquet

Dung:

```bash
python scripts/train_meta_model_v3.py \
  --dataset data/feature_store/training/ml_dataset_v3.parquet \
  --output-dir logs
```

Phu hop khi:

- Muon tan dung 205 features.
- Chap nhan wire lai inference production.

Can lam them:

- Kiem tra production co load dung model v3 hay khong.
- Tao adapter `predict_meta_confidence()` neu can.
- So sanh voi production v3.1 hien tai.

## Khuyen Nghi Cuoi

Nen di theo thu tu:

1. Dung `logs/adaptive_signals_v2.json` de train/eval baseline moi sau fix score-strength.
2. Sua builder raw OHLCV de rebuild dataset sach tu `data/fresh_training_data_2023_2026`.
3. Tao run folder co manifest/hash de moi lan train co the reproduce.
4. Sau khi candidate pass walk-forward + calibration + backtest, moi promote thanh `logs/meta_model.joblib`.

