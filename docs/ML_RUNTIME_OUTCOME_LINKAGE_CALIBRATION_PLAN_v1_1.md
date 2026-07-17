# ML Runtime Outcome Linkage & Calibration Remediation Plan v1.1

- Ngay lap: 2026-07-16
- Cap nhat van hanh: 2026-07-17
- Bao cao trang thai tong hop: `docs/remediation/System_Status_Report_2026-07-17.md`
- He thong: besttime-crypto
- Trang thai: rollout-ready (giu nguyen safety conditions)

## 1) Muc tieu

Khep vong du lieu runtime:

prediction_id -> signal_id -> entry_decision_id -> reservation_id -> order_id/fill_id -> position_id -> outcome_id -> calibration sample

Muc tieu cuoi:
- Do calibration tu runtime outcomes thuc
- Tach biet ro offline learning va runtime calibration
- Khong auto-promote neu thieu linkage/evidence
- Truy vet day du model/artifact/schema/outcome moi trade
- Phan biet ro lenh system paper voi lenh user qua Telegram/UI/CLI
- Giu tail sizing clamp den khi du evidence runtime

## 2) Nguyen tac bat buoc

1. Stable IDs xuyen suot lifecycle
2. Audit append-only, khong overwrite
3. Metadata model/schema/artifact dung tai thoi diem prediction
4. Thieu linkage hoac schema mismatch thi fail-closed
5. Loai synthetic/debug khoi runtime calibration/promotion
6. Prediction record khong mutate; event sau tham chieu bang ID
7. Candidate recalibration khong duoc thay production truc tiep

## 3) WS0 (P0) - Data Contract Registry

Muc tieu: khoa semantics truoc khi rollout stable IDs.

Moi contract toi thieu:
- event_type
- schema_version
- event_id
- event_time
- ingest_time
- producer
- required_fields
- business_key
- idempotency_scope

Vi du:

```json
{
  "event_type": "position_closed",
  "schema_version": "position-closed-v1",
  "event_id": "uuid",
  "event_time": "timestamp",
  "ingest_time": "timestamp",
  "producer": "position_tracker",
  "required_fields": ["position_id", "closed_at", "net_pnl_pct"],
  "business_key": "position_id",
  "idempotency_scope": "position_id+close_revision"
}
```

Source of truth:
- Prediction: prediction audit log
- Signal/Decision: decision audit log
- Reservation: reservation store
- Order/Fill: execution ledger
- Position: position ledger
- Outcome: outcome ledger
- Calibration sample: runtime calibration store (derived, khong thay truth goc)

Acceptance:
- Registry co versioning va reject reason code chuan hoa
- Contract validation co unit tests
- Schema drift bi phat hien som (fail-closed)

## 4) WS1-WS5 (P0) - Stable IDs den Runtime Linker

### WS1 - Stable IDs & Lifecycle Contract
IDs bat buoc:
- prediction_id, signal_id, entry_decision_id
- reservation_id, idempotency_key
- client_order_id, exchange_order_id, fill_id
- position_id, outcome_id
- trade_origin, order_creator, order_channel

Them `TradeLifecycleContext` canonical va schema version cho contract IDs.

Order provenance canonical:

```text
order_creator = system | user | test
order_channel = paper_runner | live_runner | telegram | ui | cli | manual | test | unknown
```

Ghi chu quan trong:
- system paper order: `order_creator=system`, `order_channel=paper_runner`
- Telegram/manual user order: `order_creator=user`, `order_channel=telegram`
- UI/manual user order: `order_creator=user`, `order_channel=ui`
- CLI/manual user order: `order_creator=user`, `order_channel=cli`
- manual trade theo signal van la user-created trade, dung `manual_decision_basis=system_signal`

### WS2 - Prediction -> Signal -> Decision Linkage
- Prediction envelope bat buoc linkage IDs
- Signal reject van phai giu prediction linkage
- Cam join production bang nearest timestamp
- Legacy path thieu context: warning/fail ro rang

### WS3 - Execution/Fill/Position Linkage
- Order metadata mang du lifecycle IDs
- Fill metadata day du qty/notional/price/fee/time + position_id
- Partial fill: cung position_id, weighted-average entry
- Reservation commit/release dung theo phan da fill/chua fill

### WS4 - Closed Outcome Recorder
- Outcome schema append-only, khong duplicate theo position_id
- Label dua tren net PnL sau fee/slippage
- Correction qua amendment event, khong overwrite
- Exclude synthetic/debug/emergency-test khoi evidence runtime

### WS5 - Runtime Outcome Linker
File module:
- `btc_scraper/ml_engine/runtime_outcome_linker.py`

Join priority:
1. prediction_id
2. signal_id
3. position_id

Khong duoc production-join bang timestamp heuristic.

Calibration sample immutable, unique key:
- prediction_id + position_id + outcome_revision

## 5) Orphan taxonomy + state machine

Orphan categories:
- prediction khong co signal
- signal khong co decision
- eligible decision khong co order
- submitted order khong co fill
- fill khong co position
- closed position khong co outcome
- outcome khong co prediction

State machine:
- pending
- retrying
- resolved
- expired
- quarantined

Fields toi thieu:
- first_seen
- last_seen
- retry_count
- reason_code
- severity

Khuyen nghi grace period theo event type de tranh false alert cho out-of-order hop le.

## 6) Out-of-order & revision policy

Pending-link flow:
- Outcome den truoc prediction audit flush -> tao pending linkage
- Chua tao calibration sample hoan chinh
- Retry lien ket khi prediction xuat hien
- Finalize sample khi du du lieu

Link states:
- WAITING_FOR_PREDICTION
- WAITING_FOR_OUTCOME
- READY
- LINKED
- QUARANTINED

Event revision policy (append-only):

```json
{
  "event_id": "...",
  "business_key": "position-123",
  "revision": 2,
  "supersedes_event_id": "...",
  "event_type": "outcome_amended"
}
```

Calibration pipeline chi dung latest finalized revision.

## 7) WS6 (P1) - Runtime Calibration Pipeline

Rolling windows: 7/14/30/90 ngay
Metrics:
- Brier
- ROC-AUC
- PR-AUC
- ECE
- Maximum calibration error
- Reliability buckets
- Win rate / net PnL theo bucket
- Breakdown theo symbol/regime/side
- Prediction distribution drift

Bucket evidence:
- <30: insufficient
- 30-99: provisional
- >=100: usable

Output:
- `logs/runtime_calibration/runtime_calibration_YYYY-MM-DD.json`

## 8) WS7 (P1) - Recalibration Promotion Governance

Candidate-only bat buoc:

```json
{
  "status": "candidate",
  "auto_promote": false
}
```

Flow:
- candidate -> shadow -> production

Cam candidate -> production truc tiep.

Statistical gates (paired comparison cung sample window):
- Brier delta (candidate - production) < 0
- Bootstrap 95% CI upper bound <= +0.002
- ECE candidate <= production + 0.01
- ROC-AUC candidate >= production - 0.01
- Tail khong xau hon >0.03 calibration error tren bucket du evidence
- Coverage theo symbol/regime khong suy giam nghiem trong

Neu CI khong ket luan:
- status = insufficient_evidence
- action = remain_shadow

## 9) WS8-WS10 (P1/P2)

### WS8 - Adaptive RF Traceability
- Ban ghi moi bat buoc IDs + model version + schema + dataset manifest/hash
- Du lieu cu thieu IDs chi dung offline analysis

### WS9 - Observability & Health
Metrics chinh:
- prediction_with_signal_rate
- signal_with_decision_rate
- eligible_to_order_rate
- order_to_fill_rate
- fill_to_position_rate
- position_to_outcome_rate
- prediction_to_outcome_link_rate
- orphan_prediction_count
- orphan_outcome_count
- duplicate_outcome_count
- calibration_sample_count
- excluded_debug_count
- excluded_synthetic_count

Health states:
- HEALTHY
- DEGRADED_LINKAGE
- INSUFFICIENT_OUTCOMES
- SCHEMA_MISMATCH
- ARTIFACT_MISMATCH
- CALIBRATION_STALE

### WS10 - Naming & Documentation
Naming chuan:
- Meta Prediction Audit
- Meta Outcome Linkage
- Runtime Calibration
- Offline Continuous Learning
- Periodic Recalibration Candidate
- RL Exit Shadow

Khong goi weekly backtest retraining la online/live continuous learning.

## 10) Phased gates (thuc dung)

Muc 1 - Shadow hardening:
- Linkage >= 90%
- Outcome coverage >= 90%

Muc 2 - Calibration ready:
- Linkage >= 95% trong 7 ngay lien tiep
- Outcome coverage >= 98%

Muc 3 - Production mature:
- Linkage 98-100%
- Outcome coverage muc tieu 100%

Dieu kien cung tu ngay dau:
- duplicate outcome = 0
- mixed model/schema/artifact sample = 0
- synthetic/debug promotion sample = 0
- artifact hash mismatch = 0

Dinh nghia denominator linkage:
- prediction_to_outcome_link_rate = linked closed traded predictions / all closed traded predictions

## 11) Migration lane (tach khoi production linker)

Nhom du lieu:
- runtime_linked
- legacy_exact_link
- legacy_probabilistic_link
- legacy_unlinked

Chi `runtime_linked` duoc dung cho promotion.

Migration report toi thieu:
- tong records
- exact linked
- heuristic linked
- unlinked
- excluded
- phan bo theo thoi gian/symbol/side/outcome
- estimated selection bias

## 12) Operational cadence

- Runtime linkage health: lien tuc hoac moi gio
- Calibration report (paper): daily
- Calibration report (live): toi da moi 6 gio
- Promotion review: weekly
- Drift/incident alerts: gan real-time

Freeze matrix:
- Linkage <90% -> freeze promotion
- Duplicate outcome >0 -> freeze calibration va promotion
- Mixed schema/artifact >0 -> quarantine sample + freeze promotion

Calibration stale:
- Khong chan scoring
- Chan promotion
- Giu sizing clamp

## 13) PR order (official)

1. PR0: WS0 Data Contract Registry + reject reason codes
2. PR1: WS1 Stable IDs + TradeLifecycleContext
3. PR2: WS2 Prediction/Signal/Decision linkage + orphan metrics
4. PR3: WS3 Execution/Fill/Position linkage + partial-fill invariants
5. PR4: WS4 Closed Outcome Recorder + source classification + amendment events
6. PR5: WS5 Runtime Outcome Linker + immutable calibration sample
7. PR6: WS6 Runtime Calibration reports + coverage/staleness warnings
8. PR7: WS7 Candidate-only governance + shadow gate + rollback atomicity
9. PR8: WS8 Adaptive RF traceability
10. PR9: WS9 Observability + WS10 Naming/runbook cleanup

Operational update 2026-07-17:
- Trade provenance taxonomy implemented.
- System paper mode vs user Telegram/UI/CLI distinction implemented.
- WLD duplicate open correction and manual system-signal correction applied.
- Shadow evidence window remains not started.

## 14) Definition of done (giu nguyen safety)

1. Prediction truy vet den closed outcome bang stable IDs
2. 100% closed real-paper/live positions co outcome (muc tieu mature)
3. Linker khong dung timestamp heuristic cho production join
4. Calibration tach model version/hash/schema
5. Tail thieu sample danh dau insufficient evidence
6. Recalibration chi tao candidate
7. Promotion yeu cau shadow + report + rollback pass
8. Adaptive outcomes moi co stable IDs
9. Offline retraining duoc goi dung ten
10. Health hien thi linkage coverage + calibration freshness
11. Synthetic/debug records bi loai khoi promotion
12. Tail sizing clamp chi thao khi runtime evidence du manh

## 15) Ket luan

Thu tu uu tien thuc thi:
- WS0 contracts
- stable IDs
- lifecycle ledgers
- pending/out-of-order linker
- shadow linkage >= 90%
- calibration-ready linkage >= 95%
- statistical candidate comparison
- shadow promotion gate

Khong retrain Meta Model truoc khi runtime linkage va outcome dataset dat do sach, coverage va contract on dinh.
