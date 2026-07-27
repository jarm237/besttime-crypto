"""
tests/test_execution_reservation_concurrency.py
PR 5 — Concurrency, Idempotency, and Sizing edge cases tests.
"""
import json
import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from btc_scraper.execution.execution_engine import ExecutionEngine
from btc_scraper.execution.exchange_adapter import WriteExchangeAdapter
from btc_scraper.execution.reservation_store import ReservationStore, ReservationStatus
from btc_scraper.execution.live_execution_guard import LiveExecutionGuard
from btc_scraper.trading.decision_types import SizingDecision, EntryRejectionReason
from btc_scraper.trading.auto_trader import AutoTrader
from btc_scraper.execution.hard_risk_limits import OrderIntent
from btc_scraper.execution.fill_tracker import OrderStatus
from btc_scraper.execution.kill_switch import KSState


class DummyKillSwitch:
    state = KSState.ARMED


@pytest.fixture(autouse=True)
def mock_exposure_positions(monkeypatch):
    # Isolate test from developer database open positions state
    monkeypatch.setattr(
        "btc_scraper.trading.exposure_manager.exposure_manager.get_open_positions",
        lambda: []
    )


@pytest.fixture
def mock_adapter():
    adapter = MagicMock(spec=WriteExchangeAdapter)
    adapter.get_symbol_price = AsyncMock(return_value=10000.0)
    adapter.get_usdt_balance = AsyncMock(return_value=10000.0)
    adapter.create_market_buy = AsyncMock(return_value={
        "id": "ord-123",
        "price": 10000.0,
        "amount": 0.001,
        "fee": {"cost": 0.05},
    })
    adapter.create_limit_buy = AsyncMock(return_value={
        "id": "ord-123",
        "price": 10000.0,
        "amount": 0.001,
        "fee": {"cost": 0.05},
        "type": "limit",
    })
    return adapter


def _buy_write_mock(adapter):
    return adapter.create_market_buy if adapter.create_market_buy.await_count else adapter.create_limit_buy


@pytest.fixture
def guard_setup(tmp_path):
    # Setup open gate & live mode enabled config
    phase5 = tmp_path / "phase5_report_latest.json"
    phase5.write_text(json.dumps({"live_readiness_gate": {"passed": True}}))

    live_mode = tmp_path / "live_mode_enabled.json"
    live_mode.write_text(json.dumps({"enabled": True}))

    # Set up rollout stage = 1
    rollout = Path("data/execution/rollout_state.json")
    rollout.parent.mkdir(parents=True, exist_ok=True)
    rollout.write_text(json.dumps({"current_stage": 1}))

    guard = LiveExecutionGuard(
        kill_switch=DummyKillSwitch(),
        phase5_report_path=str(phase5),
        live_mode_flag_path=str(live_mode),
    )
    return guard


@pytest.mark.anyio
async def test_idempotency_deduplication(mock_adapter, tmp_path, guard_setup):
    db_file = tmp_path / "reservations_idem.db"
    store = ReservationStore(db_path=db_file)
    
    engine = ExecutionEngine(
        fills_dir=str(tmp_path / "fills"),
        log_dir=str(tmp_path / "logs"),
        reports_dir=str(tmp_path / "reports"),
        exchange_adapter=mock_adapter,
        live_guard=guard_setup,
    )
    engine._reservation_store = store

    signal1 = {
        "id": "sig-1",
        "coin": "BTC",
        "signal": "BUY",
        "intent": OrderIntent.ENTRY,
        "idempotency_key": "key-abc-123",
        "decision_id": "dec-1",
    }
    candle = {"close": 10000.0, "high": 10010.0, "low": 9990.0, "open": 10000.0, "volume": 1.0}

    # Submit first time -> fills successfully
    res1 = await engine.submit_live(signal1, candle, notional_usdt=10.0)
    assert res1.status == OrderStatus.FILLED
    first_params = _buy_write_mock(mock_adapter).await_args.args[-1]
    assert first_params["clientOrderId"] == "key-abc-123"
    assert first_params["reservationId"].startswith("res-")

    # Submit second time -> duplicate request already completed
    res2 = await engine.submit_live(signal1, candle, notional_usdt=10.0)
    assert res2.status == OrderStatus.FILLED
    assert res2.reason == "Duplicate request already completed"
    assert mock_adapter.create_market_buy.await_count + mock_adapter.create_limit_buy.await_count == 1


@pytest.mark.anyio
async def test_released_idempotency_key_requires_reconciliation(mock_adapter, tmp_path, guard_setup):
    db_file = tmp_path / "reservations_released.db"
    store = ReservationStore(db_path=db_file)

    rec, created = store.reserve(
        reservation_id="res-released",
        idempotency_key="key-used-before",
        entry_decision_id="dec-old",
        symbol="BTC/USDT",
        side="buy",
        reserved_notional=10.0,
    )
    assert created
    store.release(rec.reservation_id)

    engine = ExecutionEngine(
        fills_dir=str(tmp_path / "fills"),
        log_dir=str(tmp_path / "logs"),
        reports_dir=str(tmp_path / "reports"),
        exchange_adapter=mock_adapter,
        live_guard=guard_setup,
    )
    engine._reservation_store = store

    signal = {
        "id": "sig-retry",
        "coin": "BTC",
        "signal": "BUY",
        "intent": OrderIntent.ENTRY,
        "idempotency_key": "key-used-before",
        "decision_id": "dec-retry",
    }
    candle = {"close": 10000.0, "high": 10010.0, "low": 9990.0, "open": 10000.0, "volume": 1.0}

    result = await engine.submit_live(signal, candle, notional_usdt=10.0)

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "Idempotency key already used; reconciliation required"
    mock_adapter.create_market_buy.assert_not_awaited()
    mock_adapter.create_limit_buy.assert_not_awaited()


@pytest.mark.anyio
async def test_concurrency_race_condition_blocks_stage_1(mock_adapter, tmp_path, guard_setup):
    # Under Stage 1 rollout, max_open_positions is 1.
    # Concurrent entry submissions must not both pass! The second one must be blocked
    # because the first reservation consumes the 1 available position slot.
    db_file = tmp_path / "reservations_race.db"
    store = ReservationStore(db_path=db_file)

    async def slow_create_buy(symbol, notional, params=None):
        await asyncio.sleep(0.1)
        return {
            "id": "ord-slow",
            "price": 10000.0,
            "amount": 0.001,
            "fee": {"cost": 0.05},
        }
    async def slow_create_limit_buy(symbol, notional, price, params=None):
        return await slow_create_buy(symbol, notional, params)
    mock_adapter.create_market_buy.side_effect = slow_create_buy
    mock_adapter.create_limit_buy.side_effect = slow_create_limit_buy

    engine = ExecutionEngine(
        fills_dir=str(tmp_path / "fills"),
        log_dir=str(tmp_path / "logs"),
        reports_dir=str(tmp_path / "reports"),
        exchange_adapter=mock_adapter,
        live_guard=guard_setup,
    )
    engine._reservation_store = store

    signal1 = {
        "id": "sig-first",
        "coin": "BTC",
        "signal": "BUY",
        "intent": OrderIntent.ENTRY,
        "idempotency_key": "idem-first",
        "decision_id": "dec-first",
    }
    signal2 = {
        "id": "sig-second",
        "coin": "ETH",
        "signal": "BUY",
        "intent": OrderIntent.ENTRY,
        "idempotency_key": "idem-second",
        "decision_id": "dec-second",
    }
    candle = {"close": 10000.0, "high": 10010.0, "low": 9990.0, "open": 10000.0, "volume": 1.0}

    # Run concurrently
    tasks = [
        engine.submit_live(signal1, candle, notional_usdt=10.0),
        engine.submit_live(signal2, candle, notional_usdt=10.0),
    ]
    results = await asyncio.gather(*tasks)

    # One must be filled, the other must be rejected due to rollout_stage / open positions limit!
    statuses = [r.status for r in results]
    assert OrderStatus.FILLED in statuses
    assert OrderStatus.REJECTED in statuses

    rejected_rec = [r for r in results if r.status == OrderStatus.REJECTED][0]
    assert "max_open_positions_reached" in rejected_rec.reason or "rollout_stage" in rejected_rec.reason


def test_sizing_edge_cases_and_caps(monkeypatch):
    monkeypatch.setenv("AUTO_TRADE_DRY_RUN", "True")
    monkeypatch.setenv("AUTO_TRADE_ACCOUNT_USDT", "1000.0")
    monkeypatch.setenv("AUTO_TRADE_RISK_PCT", "2.0")
    monkeypatch.setenv("AUTO_TRADE_MIN_TRADE_USDT", "10.0")
    monkeypatch.setenv("AUTO_TRADE_MAX_TRADE_USDT", "100.0")
    monkeypatch.setenv("AUTO_TRADE_USE_KELLY", "True")
    monkeypatch.setenv("AUTO_TRADE_KELLY_FRACTION", "0.5")

    # Construct AutoTrader
    trader = AutoTrader()

    # 1. Invalid price rejection
    sd = trader.compute_position_size(entry_price=0.0, sl_price=10.0)
    assert sd.rejected
    assert sd.rejection_reason == EntryRejectionReason.INVALID_SIZING_INPUT

    # 2. Too close stop distance rejection
    sd = trader.compute_position_size(entry_price=100.0, sl_price=99.95)
    assert sd.rejected
    assert sd.rejection_reason == EntryRejectionReason.INVALID_SIZING_INPUT

    # 3. Non-positive Kelly rejection
    # win_prob = 0.3, rr_ratio = 1.0 -> kelly_f = 0.3 - (0.7 / 1.0) = -0.4 <= 0
    sd = trader.compute_position_size(entry_price=100.0, sl_price=90.0, win_prob=0.3, rr_ratio=1.0)
    assert sd.rejected
    assert sd.rejection_reason == EntryRejectionReason.NON_POSITIVE_KELLY

    # 4. VaR Sizing cap scale down
    # With win_prob = 0.6, rr_ratio = 2.0 -> kelly_f = 0.6 - (0.4 / 2.0) = 0.4.
    # kelly_risk_pct = 0.4 * 0.5 * 100.0 = 10.0%.
    # adjusted_risk_pct = min(10.0%, 2.0%) = 2.0%.
    # risk_notional = 1000 * 2% = 20 USDT.
    # sl_distance = 10% -> raw_notional = 20 / 0.10 = 200 USDT.
    # Capped at max_trade_usdt (100) -> 100 USDT.
    # Apply VaR cap of 50.0 USDT -> final size should be 50.0 USDT!
    sd = trader.compute_position_size(
        entry_price=100.0,
        sl_price=90.0,
        win_prob=0.6,
        rr_ratio=2.0,
        var_cap=50.0,
    )
    assert not sd.rejected
    assert sd.final_notional == 50.0

    # 5. Normal risk-based sizing above min notional.
    # risk_notional = 20 USDT and stop distance = 50%, so raw notional is 40 USDT.
    sd = trader.compute_position_size(entry_price=100.0, sl_price=50.0)
    assert not sd.rejected
    assert sd.final_notional == 40.0

    # 6. Min notional check exceeding risk cap -> rejection
    # If we set min_trade_usdt to 50.0 USDT.
    # At sl_distance = 50%, 50 USDT size risks 25 USDT.
    # Allowed risk is 20 USDT. Raising to min trade size (50) risks 25 USDT which exceeds 20.
    # So it should reject!
    sd = trader.compute_position_size(entry_price=100.0, sl_price=50.0, min_trade_cap=50.0)
    assert sd.rejected
    assert sd.rejection_reason == EntryRejectionReason.INVALID_SIZING_INPUT
