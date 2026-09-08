"""Tests for P8 Economic Effectiveness Evaluation Extractor & Governance Tooling."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
import pytest

from btc_scraper.ml_engine.p8_governance import (
    ABSOLUTE_USD_TOLERANCE,
    MIN_COST_COVERAGE_RATIO,
    MIN_RATE_COVERAGE_RATIO,
    EXPECTED_DEPLOYMENT_ID,
    EXPECTED_EPOCH_ID,
    EXPECTED_PAPER_RUN_ID,
    EXPECTED_UNIVERSE_HASH,
    EXPECTED_MODEL_VERSION,
    EXPECTED_FEATURE_SCHEMA_VERSION,
    EXPECTED_EVIDENCE_POLICY_VERSION,
    EXPECTED_RISK_POLICY_VERSION,
    EXPECTED_RUNTIME_SCHEMA_VERSION,
    EXPECTED_RELEASE_MANIFEST_SHA256,
    SEALED_ARTIFACT_SHA,
    SEALED_COMMIT_SHA,
    REQUIRED_RESERVATION_COLUMNS,
    GovernanceError,
    P8AttestationPolicy,
    P8CostPolicy,
    _load_active_epoch_rows,
    _load_raw_partition_records,
    calculate_store_content_hash,
    calculate_store_manifest_hash,
    check_runtime_lock_owner,
    get_cost_policy_metadata,
    validate_reservation_db_schema,
)
from btc_scraper.execution.reservation_store import ReservationStore
from btc_scraper.ml_engine.p8_economic_extractor import (
    extract_closed_trades,
    run_funnel_analysis,
)
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore
from scripts.p8_economic_report import (
    MIN_CANARY_N,
    calculate_accounting_reconciliation,
    calculate_metrics,
    calculate_population_reconciliation,
    determine_verdict,
    generate_report,
    is_economic_verdict_authorized,
    validate_canonical_store_identity,
)
from scripts.run_manual_runner import SEALED_WORKTREE_PATH, validate_governed_preflight


def _seed_basic_evidence(store: RuntimeEvidenceStore, epoch_id="p8-readiness-r2-20260902-01", dep_id="paper-canary-win-tsfix-20260901-01"):
    with store._global_transaction() as db:
        db.execute(
            "INSERT OR REPLACE INTO evidence_epochs("
            "epoch_id,deployment_id,started_at,activated_at,code_commit_sha,model_version,"
            "artifact_sha256,feature_schema_version,analysis_universe,"
            "analysis_universe_hash,evidence_policy_version,risk_policy_version,"
            "runtime_schema_version,status,paper_run_id,release_manifest,release_manifest_sha256,runtime_pause_policy,updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                epoch_id, dep_id, "2026-08-26T00:00:00Z",
                "2026-08-26T00:00:00Z", SEALED_COMMIT_SHA, EXPECTED_MODEL_VERSION,
                SEALED_ARTIFACT_SHA, EXPECTED_FEATURE_SCHEMA_VERSION, '["BTC","ETH","BNB"]',
                EXPECTED_UNIVERSE_HASH, EXPECTED_EVIDENCE_POLICY_VERSION, EXPECTED_RISK_POLICY_VERSION,
                EXPECTED_RUNTIME_SCHEMA_VERSION, "ACTIVE", dep_id, "{}", EXPECTED_RELEASE_MANIFEST_SHA256, "{}", "2026-08-26T00:00:00Z"
            )
        )

    target_path = store.current_path
    with store._connect(target_path) as db:
        pred_payload = json.dumps({
            "prediction_id": "pred-001",
            "timestamp": "2026-08-26T12:00:00Z",
            "symbol": "BTC/USDT",
            "predicted_probability": 0.75,
            "calibrated_prediction": 0.75,
            "raw_prediction": 0.75,
            "decision": "BUY",
            "model_version": EXPECTED_MODEL_VERSION,
            "artifact_sha256": SEALED_ARTIFACT_SHA,
            "feature_schema_version": EXPECTED_FEATURE_SCHEMA_VERSION,
            "evidence_eligible": True,
            "source_partition": dep_id,
            "historical_backfill": False,
            "epoch_id": epoch_id,
            "deployment_id": dep_id,
            "paper_run_id": dep_id,
        })
        db.execute(
            "INSERT OR REPLACE INTO predictions (prediction_id, payload, payload_sha256, written_at) VALUES (?, ?, ?, ?)",
            ("pred-001", pred_payload, "sha-pred-001", "2026-08-26T12:00:00Z")
        )

        dec_payload = json.dumps({
            "prediction_id": "pred-001",
            "decision_id": "dec-001",
            "action": "BUY",
            "symbol": "BTC/USDT",
            "route": "MC5_QUALIFIED",
            "evidence_eligible": True,
            "deployment_id": dep_id,
            "paper_run_id": dep_id,
            "epoch_id": epoch_id,
        })
        db.execute(
            "INSERT OR REPLACE INTO final_decisions (decision_id, prediction_id, payload, payload_sha256, written_at) VALUES (?, ?, ?, ?, ?)",
            ("dec-001", "pred-001", dec_payload, "sha-dec-001", "2026-08-26T12:00:00Z")
        )

        out_payload = json.dumps({
            "position_id": "pos-001",
            "prediction_id": "pred-001",
            "symbol": "BTC/USDT",
            "direction": "BUY",
            "entry_price": 50000.0,
            "sell_price": 51000.0,
            "pnl_usd_actual": 20.0,
            "fee_usd": 2.02,
            "invested_usdt": 1000.0,
            "net_return_bps": 180.0,
            "net_pnl_pct": 1.8,
            "model_version": EXPECTED_MODEL_VERSION,
            "artifact_sha256": SEALED_ARTIFACT_SHA,
            "feature_schema_version": EXPECTED_FEATURE_SCHEMA_VERSION,
            "evidence_eligible": True,
            "deployment_id": dep_id,
            "paper_run_id": dep_id,
            "epoch_id": epoch_id,
            "outcome_revision": 1,
        })
        db.execute(
            "INSERT OR REPLACE INTO outcome_links (outcome_id, prediction_id, payload, payload_sha256, written_at) VALUES (?, ?, ?, ?, ?)",
            ("out-001", "pred-001", out_payload, "sha-out-001", "2026-08-26T12:00:00Z")
        )


def test_inherited_epoch_lineage(tmp_path):
    evidence_path = tmp_path / "runtime_evidence.sqlite"
    reservation_path = tmp_path / "reservations.db"
    store = RuntimeEvidenceStore(evidence_path)

    _seed_basic_evidence(store)

    trades = extract_closed_trades(
        store,
        reservation_path,
        target_epoch_id="p8-readiness-r2-20260902-01",
        require_evidence_eligible=True,
    )
    assert len(trades) == 1
    t = trades[0]
    assert t["prediction_id"] == "pred-001"
    assert t["actual_gross_pnl_usd"] == 20.0
    assert t["actual_fee_usd"] == 2.02
    assert t["actual_net_pnl_usd"] == 17.98
    assert t["invested_usdt"] == 1000.0
    assert t["cost_coverage_complete"] is True
    assert calculate_accounting_reconciliation(trades)["status"] == "PASS"


def test_explicit_child_epoch_mismatch_rejected(tmp_path):
    evidence_path = tmp_path / "runtime_evidence.sqlite"
    reservation_path = tmp_path / "reservations.db"
    store = RuntimeEvidenceStore(evidence_path)

    _seed_basic_evidence(store)

    target_path = store.current_path
    with store._connect(target_path) as db:
        dec_payload = json.dumps({
            "prediction_id": "pred-001",
            "decision_id": "dec-001",
            "action": "BUY",
            "symbol": "BTC/USDT",
            "route": "MC5_QUALIFIED",
            "evidence_eligible": True,
            "deployment_id": EXPECTED_DEPLOYMENT_ID,
            "paper_run_id": EXPECTED_PAPER_RUN_ID,
            "epoch_id": "wrong-epoch",
        })
        db.execute("UPDATE final_decisions SET payload=? WHERE decision_id='dec-001'", (dec_payload,))

    trades, info = extract_closed_trades(
        store,
        reservation_path,
        target_epoch_id="p8-readiness-r2-20260902-01",
        require_evidence_eligible=True,
        include_rejections=True,
    )
    assert len(trades) == 0
    assert info["counts"]["epoch_mismatch"] == 1


def test_governance_error_on_missing_active_epoch(tmp_path):
    evidence_path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(evidence_path)

    with pytest.raises(GovernanceError):
        extract_closed_trades(store, target_epoch_id="p8-readiness-r2-20260902-01", require_evidence_eligible=True)


def test_multiple_active_epochs_raises_governance_error(tmp_path):
    evidence_path = tmp_path / "runtime_evidence.sqlite"
    global_index = tmp_path / "global_evidence_index.sqlite"

    conn = sqlite3.connect(global_index)
    conn.execute(
        "CREATE TABLE evidence_epochs (epoch_id TEXT PRIMARY KEY, status TEXT, code_commit_sha TEXT, artifact_sha256 TEXT, deployment_id TEXT, paper_run_id TEXT, analysis_universe_hash TEXT)"
    )
    conn.execute("INSERT INTO evidence_epochs VALUES ('e1', 'ACTIVE', 'sha', 'art', 'dep', 'pr', 'hash')")
    conn.execute("INSERT INTO evidence_epochs VALUES ('e2', 'ACTIVE', 'sha', 'art', 'dep', 'pr', 'hash')")
    conn.commit()
    conn.close()

    with pytest.raises(GovernanceError) as exc_info:
        _load_active_epoch_rows(global_index)
    assert "Expected exactly 1 ACTIVE epoch" in str(exc_info.value)


def test_unmixed_rate_vs_accounting_metrics():
    trades = [
        {
            "net_return_bps": 100.0,
            "gross_return_bps": 120.0,
            "actual_net_pnl_usd": 18.0,
            "actual_gross_pnl_usd": 20.0,
            "actual_fee_usd": 2.0,
            "cost_coverage_complete": True,
        },
        {
            "net_return_bps": -50.0,
            "gross_return_bps": -40.0,
            "actual_net_pnl_usd": -9.0,
            "actual_gross_pnl_usd": -8.0,
            "actual_fee_usd": 1.0,
            "cost_coverage_complete": True,
        },
    ]

    metrics = calculate_metrics(trades)
    assert metrics["sample_size"] == 2
    assert metrics["rate_coverage_n"] == 2
    assert metrics["cost_coverage_n"] == 2
    assert metrics["mean_net_return_bps"] == 25.0
    assert metrics["win_rate"] == 0.5
    assert metrics["total_net_pnl_usd"] == 9.0
    assert metrics["total_gross_pnl_usd"] == 12.0
    assert metrics["total_fees_usd"] == 3.0


def test_cent_rounding_accounting_tolerance():
    invested = Decimal("1000.00")
    gross = Decimal("20.00")
    fee = Decimal("2.01")
    received = Decimal("1017.99")

    calc_received = invested + gross - fee
    assert abs(calc_received - received) <= ABSOLUTE_USD_TOLERANCE


def test_report_canonicality_and_verdict_authorization(tmp_path):
    evidence_path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(evidence_path)

    is_canonical = validate_canonical_store_identity(evidence_path, store)
    assert is_canonical is False


def test_p8_economic_report_governed_cli_dev_db_exits_nonzero(tmp_path):
    evidence_path = tmp_path / "runtime_evidence.sqlite"
    reservation_path = tmp_path / "reservations.db"
    store = RuntimeEvidenceStore(evidence_path)

    cmd = [
        sys.executable,
        "scripts/p8_economic_report.py",
        "--governed",
        "--evidence-db", str(evidence_path),
        "--reservation-db", str(reservation_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode != 0
    assert "Governed P8 execution failure" in res.stderr or "ERROR" in res.stderr


def test_portable_mock_preflight(tmp_path):
    mock_sealed = tmp_path / "mock_sealed"
    mock_sealed.mkdir(parents=True)

    subprocess.check_call(["git", "init"], cwd=str(mock_sealed))
    subprocess.check_call(["git", "config", "user.name", "test"], cwd=str(mock_sealed))
    subprocess.check_call(["git", "config", "user.email", "test@example.com"], cwd=str(mock_sealed))

    gitignore = mock_sealed / ".gitignore"
    gitignore.write_text("runtime/\nlogs/\n")
    dummy_file = mock_sealed / "dummy.txt"
    dummy_file.write_text("dummy")
    subprocess.check_call(["git", "add", ".gitignore", "dummy.txt"], cwd=str(mock_sealed))
    subprocess.check_call(["git", "commit", "-m", "init"], cwd=str(mock_sealed))

    current_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(mock_sealed), text=True).strip()

    sealed_logs = mock_sealed / "runtime" / "paper" / EXPECTED_DEPLOYMENT_ID / "logs"
    sealed_logs.mkdir(parents=True)
    evidence_path = sealed_logs / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(evidence_path)
    global_index = store.global_index_path
    reservation_path = (
        mock_sealed
        / "runtime"
        / "paper"
        / EXPECTED_DEPLOYMENT_ID
        / "data"
        / "execution"
        / "reservations.db"
    )
    ReservationStore(reservation_path)

    with store._global_transaction() as db:
        db.execute(
            "INSERT OR REPLACE INTO evidence_epochs("
            "epoch_id,deployment_id,started_at,activated_at,code_commit_sha,model_version,"
            "artifact_sha256,feature_schema_version,analysis_universe,"
            "analysis_universe_hash,evidence_policy_version,risk_policy_version,"
            "runtime_schema_version,status,paper_run_id,release_manifest,release_manifest_sha256,runtime_pause_policy,updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                EXPECTED_EPOCH_ID, EXPECTED_DEPLOYMENT_ID, "2026-08-26T00:00:00Z",
                "2026-08-26T00:00:00Z", current_commit, EXPECTED_MODEL_VERSION,
                SEALED_ARTIFACT_SHA, EXPECTED_FEATURE_SCHEMA_VERSION, '["BTC","ETH","BNB"]',
                EXPECTED_UNIVERSE_HASH, EXPECTED_EVIDENCE_POLICY_VERSION, EXPECTED_RISK_POLICY_VERSION,
                EXPECTED_RUNTIME_SCHEMA_VERSION, "ACTIVE", EXPECTED_PAPER_RUN_ID, "{}", EXPECTED_RELEASE_MANIFEST_SHA256, "{}", "2026-08-26T00:00:00Z"
            )
        )

    mock_logs = mock_sealed / "logs"
    mock_logs.mkdir(parents=True, exist_ok=True)
    mock_model_file = mock_logs / "meta_model.joblib"
    mock_model_file.write_bytes(b"mock_meta_model_artifact")

    import scripts.run_manual_runner as runner_module
    import btc_scraper.ml_engine.p8_governance as gov_module
    old_path = runner_module.SEALED_WORKTREE_PATH
    old_sha = runner_module.SEALED_COMMIT_SHA
    old_gov_sha = gov_module.SEALED_COMMIT_SHA
    old_compute_sha = gov_module.compute_file_sha256
    try:
        runner_module.SEALED_WORKTREE_PATH = mock_sealed
        runner_module.SEALED_COMMIT_SHA = current_commit
        gov_module.SEALED_COMMIT_SHA = current_commit
        gov_module.compute_file_sha256 = lambda p: SEALED_ARTIFACT_SHA
        checks = runner_module.validate_governed_preflight()
        assert checks["preflight_status"] == "PASS"
        assert checks["active_epoch_id"] == EXPECTED_EPOCH_ID
    finally:
        runner_module.SEALED_WORKTREE_PATH = old_path
        runner_module.SEALED_COMMIT_SHA = old_sha
        gov_module.SEALED_COMMIT_SHA = old_gov_sha
        gov_module.compute_file_sha256 = old_compute_sha


@pytest.mark.skipif(not SEALED_WORKTREE_PATH.exists(), reason="Requires local sealed worktree checkout")
def test_governed_runner_preflight_only():
    cmd = [sys.executable, "scripts/run_manual_runner.py", "--governed", "--preflight-only"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "[PREFLIGHT PASS]" in res.stdout
    assert "Sealed Worktree:" in res.stdout
    assert SEALED_COMMIT_SHA in res.stdout


def test_cross_partition_same_id_same_hash_deduplicates(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    p1 = logs_dir / "runtime_evidence_2026-08-26.sqlite"
    p2 = logs_dir / "runtime_evidence_2026-08-27.sqlite"

    payload_text = json.dumps({"prediction_id": "pred-dup-001", "symbol": "BTC/USDT"})
    payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()

    for p in (p1, p2):
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE predictions (prediction_id TEXT PRIMARY KEY, payload TEXT, payload_sha256 TEXT, written_at TEXT)")
        conn.execute(
            "INSERT INTO predictions VALUES (?, ?, ?, ?)",
            ("pred-dup-001", payload_text, payload_hash, "2026-08-26T12:00:00Z")
        )
        conn.commit()
        conn.close()

    raw_recs = _load_raw_partition_records(logs_dir)
    assert len(raw_recs) == 1
    assert raw_recs[0]["prediction_id"] == "pred-dup-001"


def test_snapshot_same_size_content_mutation(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    p1 = logs_dir / "runtime_evidence_2026-08-26.sqlite"
    p1.write_bytes(b"1234567890abcdef")

    h1 = calculate_store_content_hash(logs_dir)
    p1.write_bytes(b"1234567890FEDCBA")  # Same length (16 bytes), different content
    h2 = calculate_store_content_hash(logs_dir)

    assert h1 != h2


def test_active_runner_lock_rejection(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    lock_file = logs_dir / "runtime.lock"
    lock_file.write_text("ACTIVE_OWNER=pid12345", encoding="utf-8")

    with pytest.raises(GovernanceError, match="LIVE_RUNNER_ACTIVE_CONFLICT"):
        check_runtime_lock_owner(logs_dir)


def test_cost_policy_metadata_v1():
    from btc_scraper.ml_engine.p8_governance import get_cost_policy_metadata, P8CostPolicy
    meta = get_cost_policy_metadata(P8CostPolicy.V1_PAPER_ROUNDTRIP_FEE)
    assert meta["cost_basis"] == "MODELED_PAPER"
    assert meta["fee_coverage_complete"] is True
    assert meta["economic_verdict_scope"] == "PAPER_MODELED_COSTS"
    assert meta["policy_cost_coverage_ratio"] == 1.0
    assert meta["component_status"]["entry_fee"] == "MODELED"
    assert meta["component_status"]["exit_fee"] == "MODELED"
    assert meta["component_status"]["funding"] == "NOT_APPLICABLE"
    assert meta["component_status"]["slippage"] == "UNMODELED_FOR_LIVE"


def test_state_runtime_lock_rejection_probe(tmp_path):
    logs_dir = tmp_path / "logs"
    state_dir = tmp_path / "state"
    logs_dir.mkdir()
    state_dir.mkdir()
    lock_file = state_dir / "runtime.lock"
    # Write lock file with current process PID
    lock_file.write_text(json.dumps({"process_id": os.getpid(), "status": "ACTIVE"}), encoding="utf-8")

    with pytest.raises(GovernanceError, match="LIVE_RUNNER_ACTIVE_CONFLICT"):
        check_runtime_lock_owner(logs_dir)


def test_raw_loader_duplicate_without_sha256_probe(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    p1 = logs_dir / "runtime_evidence_2026-08-26.sqlite"
    p2 = logs_dir / "runtime_evidence_2026-08-27.sqlite"

    payload1 = json.dumps({"prediction_id": "dup-probe-01", "symbol": "BTC/USDT", "value": 100})
    payload2 = json.dumps({"prediction_id": "dup-probe-01", "symbol": "BTC/USDT", "value": 200})

    # Leave payload_sha256 empty or missing
    for p, payload in ((p1, payload1), (p2, payload2)):
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE predictions (prediction_id TEXT PRIMARY KEY, payload TEXT, payload_sha256 TEXT, written_at TEXT)")
        conn.execute("INSERT INTO predictions VALUES (?, ?, ?, ?)", ("dup-probe-01", payload, "", "2026-08-26T12:00:00Z"))
        conn.commit()
        conn.close()

    with pytest.raises(GovernanceError, match="duplicate_conflict"):
        _load_raw_partition_records(logs_dir)


def test_determine_verdict_allow_non_eligible_false():
    promising_metrics = {"mean_net_return_bps": 15.0, "win_rate": 0.55}
    v_type, v_reason = determine_verdict(120, promising_metrics, {}, {}, allow_non_eligible=False)
    assert v_type == "DIAGNOSTIC"
    assert v_reason == "UNAUTHORIZED_POPULATION_VERDICT_NOT_PERMITTED"


def test_mandatory_attestation_version_missing(tmp_path):
    sealed_root = tmp_path / "sealed"
    logs_dir = sealed_root / "runtime" / "paper" / EXPECTED_DEPLOYMENT_ID / "logs"
    logs_dir.mkdir(parents=True)
    global_index = logs_dir / "global_evidence_index.sqlite"

    conn = sqlite3.connect(global_index)
    conn.execute(
        "CREATE TABLE evidence_epochs (epoch_id TEXT, status TEXT, code_commit_sha TEXT, "
        "artifact_sha256 TEXT, deployment_id TEXT, paper_run_id TEXT, analysis_universe_hash TEXT, "
        "model_version TEXT)"
    )
    # Insert row missing model_version and other required versions
    conn.execute(
        "INSERT INTO evidence_epochs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (EXPECTED_EPOCH_ID, "ACTIVE", SEALED_COMMIT_SHA, SEALED_ARTIFACT_SHA, EXPECTED_DEPLOYMENT_ID, EXPECTED_PAPER_RUN_ID, EXPECTED_UNIVERSE_HASH, "")
    )
    conn.commit()
    conn.close()

    policy = P8AttestationPolicy(sealed_root=sealed_root)
    att = policy.attest_store(logs_dir / "runtime_evidence.sqlite")
    assert att.is_valid is False
    assert any("missing or empty" in err for err in att.attestation_errors)


# ---------------------------------------------------------------------------
# V7 Remediation Tests: hash boundary and N=29/30 authorization boundary
# ---------------------------------------------------------------------------

def test_store_content_hash_includes_reservation_db(tmp_path):
    """Mutations to reservations.db MUST change the boundary hash when path is supplied."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    db_file = logs_dir / "runtime_evidence_2026-08-26.sqlite"
    db_file.write_bytes(b"evidence_payload_v1")

    res_db = tmp_path / "reservations.db"
    res_db.write_bytes(b"initial_reservation_state")

    h1 = calculate_store_content_hash(logs_dir, reservation_db_path=res_db)

    # Mutate reservations.db — same size, different content
    res_db.write_bytes(b"mutated_reservation_stX")

    h2 = calculate_store_content_hash(logs_dir, reservation_db_path=res_db)

    assert h1 != h2, (
        "calculate_store_content_hash must detect mutations in reservations.db "
        "when reservation_db_path is supplied."
    )


def test_store_content_hash_without_reservation_db_unchanged_by_res(tmp_path):
    """Without reservation_db_path the hash must NOT change when only reservations.db is mutated.
    This preserves backward-compat for callers that don't extend the boundary."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    db_file = logs_dir / "runtime_evidence_2026-08-26.sqlite"
    db_file.write_bytes(b"evidence_payload_v1")

    res_db = tmp_path / "reservations.db"
    res_db.write_bytes(b"initial_reservation_state")

    h1 = calculate_store_content_hash(logs_dir)  # no reservation_db_path
    res_db.write_bytes(b"mutated_reservation_stX")
    h2 = calculate_store_content_hash(logs_dir)  # still no reservation_db_path

    assert h1 == h2, (
        "Without reservation_db_path the hash must not change when only reservations.db mutates "
        "(backward-compat guarantee)."
    )


def test_store_content_hash_fails_closed_on_missing_reservation_db(tmp_path):
    """Supplying a non-existent path for reservation_db_path MUST raise GovernanceError."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    db_file = logs_dir / "runtime_evidence_2026-08-26.sqlite"
    db_file.write_bytes(b"evidence_payload_v1")

    missing_res_db = tmp_path / "nonexistent" / "reservations.db"

    with pytest.raises(GovernanceError, match="reservation_db_path supplied"):
        calculate_store_content_hash(logs_dir, reservation_db_path=missing_res_db)


def _authorized_gate(canary_n: int) -> bool:
    return is_economic_verdict_authorized(
        canary_n,
        "CONTINUE",
        "ECONOMICALLY_PROMISING",
        is_canonical=True,
        require_evidence_eligible=True,
        data_integrity_status="PASS",
        population_reconciliation_status="PASS",
        accounting_reconciliation_status="PASS",
        rate_coverage_ratio=1.0,
        cost_coverage_ratio=1.0,
    )


def test_verdict_not_authorized_at_n29():
    """The complete authorization gate must remain closed at N=29."""
    assert MIN_CANARY_N == 30
    assert _authorized_gate(29) is False


def test_verdict_authorized_exactly_at_n30():
    """The complete authorization gate may open exactly at N=30."""
    assert _authorized_gate(30) is True


def test_reservation_schema_validation_accepts_runtime_schema(tmp_path):
    reservation_path = tmp_path / "reservations.db"
    ReservationStore(reservation_path)

    columns = validate_reservation_db_schema(reservation_path)

    assert REQUIRED_RESERVATION_COLUMNS <= set(columns)


def test_reservation_schema_validation_rejects_placeholder_schema(tmp_path):
    reservation_path = tmp_path / "reservations.db"
    with sqlite3.connect(reservation_path) as db:
        db.execute(
            "CREATE TABLE reservations ("
            "reservation_id TEXT PRIMARY KEY, entry_decision_id TEXT, symbol TEXT, "
            "side TEXT, allocated_usd REAL, status TEXT, created_at TEXT)"
        )

    with pytest.raises(GovernanceError, match="missing required columns"):
        validate_reservation_db_schema(reservation_path)


def _decision(prediction_id: str, action: str) -> dict[str, object]:
    return {
        "prediction_id": prediction_id,
        "action": action,
        "evidence_eligible": True,
        "epoch_id": EXPECTED_EPOCH_ID,
        "deployment_id": EXPECTED_DEPLOYMENT_ID,
        "paper_run_id": EXPECTED_PAPER_RUN_ID,
        "historical_backfill": False,
    }


def test_non_empty_population_reconciliation_is_disjoint_and_exhaustive():
    decisions = [
        _decision("pred-closed", "BUY"),
        _decision("pred-ignore", "IGNORE"),
        _decision("pred-open", "SELL"),
    ]
    trades = [{"prediction_id": "pred-closed"}]

    reconciliation = calculate_population_reconciliation(
        trades,
        decisions,
        epoch_id=EXPECTED_EPOCH_ID,
        deployment_id=EXPECTED_DEPLOYMENT_ID,
        paper_run_id=EXPECTED_PAPER_RUN_ID,
        require_evidence_eligible=True,
        funnel_closed_trades=1,
    )

    assert reconciliation["status"] == "PASS"
    assert reconciliation["decision_universe_count"] == 3
    assert reconciliation["closed_prediction_count"] == 1
    assert reconciliation["non_actionable_count"] == 1
    assert reconciliation["not_closed_actionable_count"] == 1
    assert reconciliation["disjoint_sets"] is True
    assert reconciliation["union_exhaustive"] is True


def test_population_reconciliation_rejects_closed_non_actionable_overlap():
    reconciliation = calculate_population_reconciliation(
        [{"prediction_id": "pred-ignore"}],
        [_decision("pred-ignore", "IGNORE")],
        epoch_id=EXPECTED_EPOCH_ID,
        deployment_id=EXPECTED_DEPLOYMENT_ID,
        paper_run_id=EXPECTED_PAPER_RUN_ID,
        require_evidence_eligible=True,
        funnel_closed_trades=1,
    )

    assert reconciliation["status"] == "FAIL"
    assert reconciliation["overlap_counts"]["closed_vs_non_actionable"] == 1


def test_non_empty_decimal_accounting_reconciliation_passes():
    reconciliation = calculate_accounting_reconciliation([
        {
            "trade_id": "trade-001",
            "invested_usdt": "1000.00",
            "actual_gross_pnl_usd": "20.00",
            "actual_fee_usd": "2.02",
            "actual_net_pnl_usd": "17.98",
        }
    ])

    assert reconciliation["status"] == "PASS"
    assert reconciliation["vacuous"] is False
    assert reconciliation["recomputed_total_fee_usd"] == "2.02000000"
    assert reconciliation["net_pnl_diff"] == "0.00000000"


def test_decimal_accounting_reconciliation_rejects_fee_mismatch():
    reconciliation = calculate_accounting_reconciliation([
        {
            "trade_id": "trade-001",
            "invested_usdt": "1000.00",
            "actual_gross_pnl_usd": "20.00",
            "actual_fee_usd": "1.00",
            "actual_net_pnl_usd": "19.00",
        }
    ])

    assert reconciliation["status"] == "FAIL"
    assert reconciliation["fee_mismatch_ids"] == ["trade-001"]
