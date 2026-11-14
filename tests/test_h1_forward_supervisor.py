"""Targeted tests for H-1 Forward Recorder Supervisor and Scorecard Generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_h1_forward_supervisor import (
    generate_forward_economic_scorecard,
    get_checkpoint_status,
    get_recorder_status,
    pause_recorder,
    resume_recorder,
)


def test_supervisor_status_query():
    """Verify get_recorder_status returns valid structure without requiring running daemon."""
    status = get_recorder_status()
    assert "operational_status" in status
    assert status["operational_status"] in ("RUNNING", "PAUSED", "STOPPED")
    assert "is_single_writer_active" in status
    assert "streams" in status


def test_checkpoint_status_query():
    """Verify get_checkpoint_status accurately reports canonical checkpoint status."""
    ckpt_status = get_checkpoint_status()
    assert ckpt_status["checkpoint_exists"] is True
    assert ckpt_status["active_positions_count"] >= 1
    assert ckpt_status["closed_positions_count"] == 0
    assert ckpt_status["last_observation_watermark_ms"] > 0


def test_forward_economic_scorecard_generation(tmp_path):
    """Verify scorecard generator produces valid schema and enforces read-only guardrails."""
    test_scorecard = tmp_path / "h1_forward_economic_scorecard.json"
    card = generate_forward_economic_scorecard(output_path=test_scorecard)

    assert test_scorecard.exists()
    assert card["metadata"]["production_candidate"] is False
    assert card["metadata"]["real_trading"] == "DISABLED"
    assert card["metadata"]["live_exchange_order_permission"] is False

    meas = card["forward_economic_measurements"]
    assert meas["forward_natural_closed_lifecycles"] == 0
    assert meas["net_realized_virtual_pnl_usd"] == 0.0
    assert meas["forward_net_economic_value"] == "INCONCLUSIVE"
    assert meas["forward_economic_evidence_status"] == "ACCUMULATING"

    cats = card["evidence_categories"]
    assert "COLLECTED_AND_VERIFIED" in cats["authentic_forward_market_observation"]
    assert "ZERO_CLOSURES_OBSERVED" in cats["naturally_matured_forward_outcome"]
    assert "ABSENT" in cats["actual_exchange_fill"]


def test_pause_and_resume_control_cycle(tmp_path, monkeypatch):
    """Verify pause and resume safely set and remove control files."""
    test_control = tmp_path / "control"
    test_pause = test_control / "PAUSE"
    monkeypatch.setattr("scripts.run_h1_forward_supervisor.CONTROL_DIR", test_control)
    monkeypatch.setattr("scripts.run_h1_forward_supervisor.PAUSE_FILE", test_pause)

    # Pause
    pause_recorder("Automated unit test pause")
    assert test_pause.exists()
    payload = json.loads(test_pause.read_text(encoding="utf-8"))
    assert payload["reason"] == "Automated unit test pause"

    # Resume
    resume_recorder()
    assert not test_pause.exists()
