from __future__ import annotations

from btc_scraper.trading import position_tracker
from scripts.backfill_trade_provenance import classify_record


class _DummyCollection:
    def __init__(self):
        self.inserted = []

    def insert_one(self, doc):
        self.inserted.append(doc)


def test_add_position_marks_pytest_records_as_test_function(monkeypatch):
    dummy = _DummyCollection()
    monkeypatch.setattr(position_tracker, "positions_col", dummy)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_trade_provenance.py::test_case (call)")

    pos = position_tracker.add_position("BTC", 100.0)

    assert pos["trade_origin"] == "test_function"
    assert pos["execution_mode"] == "test"
    assert pos["created_by"] == "pytest"
    assert pos["order_creator"] == "test"
    assert pos["order_channel"] == "test"
    assert pos["is_test_record"] is True
    assert pos["is_manual"] is False
    assert dummy.inserted[0]["trade_origin"] == "test_function"


def test_add_position_can_explicitly_mark_manual(monkeypatch):
    dummy = _DummyCollection()
    monkeypatch.setattr(position_tracker, "positions_col", dummy)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    pos = position_tracker.add_position(
        "ETH",
        200.0,
        trade_origin="manual",
        execution_mode="manual",
        created_by="telegram_command",
        order_creator="user",
        order_channel="telegram",
    )

    assert pos["trade_origin"] == "manual"
    assert pos["execution_mode"] == "manual"
    assert pos["created_by"] == "telegram_command"
    assert pos["order_creator"] == "user"
    assert pos["order_channel"] == "telegram"
    assert pos["is_manual"] is True
    assert pos["is_user_order"] is True
    assert pos["is_user_telegram_order"] is True
    assert pos["is_system_paper_order"] is False


def test_manual_position_records_whether_it_follows_a_system_signal(monkeypatch):
    dummy = _DummyCollection()
    monkeypatch.setattr(position_tracker, "positions_col", dummy)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    pos = position_tracker.add_position(
        "BTC",
        100.0,
        trade_origin="manual",
        manual_decision_basis="system_signal",
        signal_id="signal-123",
    )

    assert pos["trade_origin"] == "manual"
    assert pos["manual_decision_basis"] == "system_signal"
    assert pos["is_system_signal_manual"] is True
    assert pos["order_creator"] == "user"
    assert pos["is_user_order"] is True
    assert pos["is_system_order"] is False
    assert pos["signal_id"] == "signal-123"


def test_paper_position_is_system_paper_order(monkeypatch):
    dummy = _DummyCollection()
    monkeypatch.setattr(position_tracker, "positions_col", dummy)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    pos = position_tracker.add_position(
        "BTC",
        100.0,
        trade_origin="paper_mode",
        execution_mode="paper",
        created_by="auto_trader",
    )

    assert pos["trade_origin"] == "paper_mode"
    assert pos["order_creator"] == "system"
    assert pos["order_channel"] == "paper_runner"
    assert pos["is_system_order"] is True
    assert pos["is_system_paper_order"] is True
    assert pos["is_user_order"] is False
    assert position_tracker.format_order_provenance(pos) == "System paper mode"


def test_created_by_can_infer_user_channel(monkeypatch):
    dummy = _DummyCollection()
    monkeypatch.setattr(position_tracker, "positions_col", dummy)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    pos = position_tracker.add_position(
        "SOL",
        50.0,
        trade_origin="manual",
        execution_mode="manual",
        created_by="web_ui",
    )

    assert pos["order_creator"] == "user"
    assert pos["order_channel"] == "ui"
    assert pos["is_user_ui_order"] is True
    assert position_tracker.format_order_provenance(pos) == "User via UI"


def test_formatter_infers_legacy_manual_telegram_source():
    label = position_tracker.format_order_provenance(
        {
            "trade_origin": "manual",
            "execution_mode": "manual",
            "created_by": "telegram_command",
        }
    )

    assert label == "User via Telegram"


def test_backfill_classifier_distinguishes_paper_manual_and_test():
    assert classify_record({"mode": "DRY_RUN", "status": "FILLED"})["trade_origin"] == "paper_mode"
    assert classify_record({"note": "[MANUAL] Telegram Command"})["trade_origin"] == "manual"
    assert classify_record({"source_test_name": "tests/test_x.py::case"})["trade_origin"] == "test_function"
    assert classify_record({"mode": "TESTNET", "fill_source": "live"})["trade_origin"] == "live"
    telegram = classify_record({"note": "[MANUAL] Telegram Command", "created_by": "telegram_command"})
    assert telegram["order_creator"] == "user"
    assert telegram["order_channel"] == "telegram"
    assert telegram["is_user_telegram_order"] is True
    paper = classify_record({"mode": "DRY_RUN", "status": "FILLED"})
    assert paper["order_creator"] == "system"
    assert paper["order_channel"] == "paper_runner"


def test_backfill_marks_legacy_manual_records_as_unknown_basis():
    metadata = classify_record({"note": "[MANUAL] Telegram Command"})

    assert metadata["manual_decision_basis"] == "unknown"
    assert metadata["is_system_signal_manual"] is False
