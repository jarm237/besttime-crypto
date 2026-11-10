from __future__ import annotations

import asyncio
import datetime
from datetime import timezone
from unittest.mock import MagicMock
import pytest

from btc_scraper.ml_engine.production_evaluator import _observation_rows, evaluate_live_market
from btc_scraper.ml_engine.common_evaluator import canonical_window_from_rows, CanonicalCandleWindow
from btc_scraper.trading.auto_trader import AutoTrader
from btc_scraper.trading.decision_types import TradeAction, SizingDecision


def test_observation_rows_prioritizes_time_utc_over_naive_time():
    history_item = {
        "time": "2026-09-09 19:30",  # Local UTC+7 string
        "time_utc": "2026-09-09T12:30:00Z",  # Aware UTC string
        "open": 100.0,
        "high": 105.0,
        "low": 95.0,
        "close": 102.0,
        "volume": 10.0,
        "closed": True,
    }
    analysis = {"history": [history_item]}
    eval_time = datetime.datetime(2026, 9, 9, 12, 31, 0, tzinfo=timezone.utc)

    rows = _observation_rows(analysis, eval_time)
    assert len(rows) == 1
    # Must prioritize time_utc or aware UTC timestamp to avoid lookahead bug
    assert rows[0]["timestamp"] == "2026-09-09T12:30:00Z"


def test_closed_flag_defaults_to_true_when_keys_missing_or_none():
    # Simulate Binance REST shape where "closed" and "is_closed" are missing or None
    history_item_missing = {
        "time": "2026-09-09 19:30",
        "time_utc": "2026-09-09T12:30:00Z",
        "open": 100.0,
        "high": 105.0,
        "low": 95.0,
        "close": 102.0,
        "volume": 10.0,
    }
    history_item_none = {
        "time": "2026-09-09 19:30",
        "time_utc": "2026-09-09T12:30:00Z",
        "closed": None,
        "is_closed": None,
        "open": 100.0,
        "high": 105.0,
        "low": 95.0,
        "close": 102.0,
        "volume": 10.0,
    }
    # User probe scenario: 15m candle opened at 12:30:00Z, missing metadata
    eval_time_forming = datetime.datetime(2026, 9, 9, 12, 35, 0, tzinfo=timezone.utc)
    eval_time_closed = datetime.datetime(2026, 9, 9, 12, 46, 0, tzinfo=timezone.utc)

    # Evaluated at 12:35 (5 minutes into 15m bar) -> MUST be filtered out as forming candle!
    rows_forming = _observation_rows({"history": [history_item_missing], "timeframe": "15m"}, eval_time_forming)
    assert len(rows_forming) == 0  # Fail-safe! Candle has not completed its 15m duration.

    # Evaluated at 12:46 (after 15m duration complete) -> Included as closed!
    rows_missing = _observation_rows({"history": [history_item_missing], "timeframe": "15m"}, eval_time_closed)
    rows_none = _observation_rows({"history": [history_item_none], "timeframe": "15m"}, eval_time_closed)

    assert len(rows_missing) == 1
    assert rows_missing[0]["closed"] is True
    assert len(rows_none) == 1
    assert rows_none[0]["closed"] is True

    # Check that canonical window point-in-time check passes
    window_missing = canonical_window_from_rows(rows_missing, symbol="BTCUSDT", timeframe="15m", default_interval_seconds=900)
    window_none = canonical_window_from_rows(rows_none, symbol="BTCUSDT", timeframe="15m", default_interval_seconds=900)

    window_missing.assert_point_in_time(eval_time_closed)
    window_none.assert_point_in_time(eval_time_closed)


def test_canonical_window_point_in_time_under_utc_plus_7():
    # Simulate a candle from 12:30:00Z (which is 19:30 UTC+7)
    # History contains both naive "time" and aware "time_utc"
    history_item = {
        "time": "2026-09-09 19:30",
        "time_utc": "2026-09-09T12:30:00Z",
        "open": 100.0,
        "high": 105.0,
        "low": 95.0,
        "close": 102.0,
        "volume": 10.0,
        "closed": True,
    }
    analysis = {"history": [history_item]}
    eval_time = datetime.datetime(2026, 9, 9, 12, 46, 0, tzinfo=timezone.utc)

    rows = _observation_rows(analysis, eval_time)
    window = canonical_window_from_rows(
        rows,
        symbol="BTCUSDT",
        timeframe="15m",
        default_interval_seconds=900,
    )
    # Point-in-time check MUST pass without raising ValueError("canonical_window_lookahead")
    window.assert_point_in_time(eval_time)


def test_evaluate_live_market_production_path_without_lookahead_error():
    base_time = datetime.datetime(2026, 9, 9, 0, 0, 0, tzinfo=timezone.utc)
    history = []
    for i in range(100):
        t_utc = base_time + datetime.timedelta(minutes=15 * i)
        t_local_str = (t_utc + datetime.timedelta(hours=7)).strftime("%Y-%m-%d %H:%M")
        history.append({
            "time": t_local_str,
            "time_utc": t_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "open": 100.0 + i,
            "high": 105.0 + i,
            "low": 95.0 + i,
            "close": 102.0 + i,
            "volume": 10.0,
            # No explicit "closed" key — tests Binance REST shape
        })

    analysis = {
        "signal": "BUY",
        "close": 202.0,
        "timeframe": "15m",
        "history": history,
        "signal_score": {
            "score": 85,
            "strength": 85,
            "meta_probability": 0.90,
            "action": "BUY",
        },
        "tp_sl": {"tp1": 210.0, "sl": 195.0, "rr1": 2.0},
    }
    eval_time = base_time + datetime.timedelta(minutes=15 * 100 + 1)
    trader = AutoTrader()

    prod_eval = evaluate_live_market(
        analysis=analysis,
        coin="BTC",
        trader=trader,
        current_balance=500.0,
        var_cap=100.0,
        exposure_cap=200.0,
        evaluation_time=eval_time,
    )
    assert prod_eval is not None
    assert prod_eval.result.symbol == "BTCUSDT"


def test_eligible_signal_flows_to_submit_paper(monkeypatch):
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.trading.auto_trader.exposure_manager.get_open_positions", lambda: [])
    async def _run():
        trader = AutoTrader()
        monkeypatch.setattr(trader, "get_last_exit_timestamps", lambda: {})
        base_time = datetime.datetime(2026, 9, 9, 0, 0, 0, tzinfo=timezone.utc)
        history = []
        for i in range(100):
            t_utc = base_time + datetime.timedelta(minutes=15 * i)
            t_local_str = (t_utc + datetime.timedelta(hours=7)).strftime("%Y-%m-%d %H:%M")
            history.append({
                "time": t_local_str,
                "time_utc": t_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "open": 100.0 + i,
                "high": 105.0 + i,
                "low": 95.0 + i,
                "close": 102.0 + i,
                "volume": 10.0,
            })

        mock_fill = MagicMock()
        mock_fill.fill_id = "fill_test_123"

        mock_rec = MagicMock()
        mock_rec.execution_id = "paper_test_123"
        mock_rec.status = "paper_submitted"
        mock_rec.avg_fill_price = 202.0
        mock_rec.guard_action = "ALLOW"
        mock_rec.expected_slippage_bps = 5.0
        mock_rec.liquidity_score = 1.0
        mock_rec.execution_mode = "paper"
        mock_rec.fill_source = "simulated"
        mock_rec.paper_run_id = "test_run_1"
        mock_rec.cycle_id = "cycle_123"
        mock_rec.prediction_id = "pred_123"
        mock_rec.signal_id = "sig_123"
        mock_rec.entry_decision_id = "dec_123"
        mock_rec.reservation_id = "res_123"
        mock_rec.idempotency_key = "idemp_123"
        mock_rec.client_order_id = "client_123"
        mock_rec.exchange_order_id = "ex_123"
        mock_rec.fills = [mock_fill]
        mock_rec.position_id = "pos_123"
        mock_rec.lifecycle_schema_version = "trade-lifecycle-v1"

        engine = trader._get_execution_engine()
        engine.submit_paper = MagicMock(return_value=mock_rec)

        # Mock breakdown & real dataclass SizingDecision
        mock_breakdown = MagicMock()
        mock_breakdown.meta_probability = 0.90
        mock_breakdown.technical_score = 85
        mock_breakdown.signal_strength = 85
        mock_breakdown.gross_expected_value = 0.05
        mock_breakdown.estimated_cost = 0.001
        mock_breakdown.net_expected_value = 0.049
        mock_breakdown.kelly_raw = 0.2
        mock_breakdown.kelly_applied = 0.1
        mock_breakdown.rr_ratio = 2.0
        mock_breakdown.to_dict.return_value = {"meta_probability": 0.90}

        real_sizing = SizingDecision(
            entry_price=202.0,
            sl_price=195.0,
            stop_distance_pct=0.0346,
            risk_pct=0.02,
            risk_notional=10.0,
            raw_notional=50.0,
            risk_adjusted_notional=50.0,
            final_notional=50.0,
        )

        mock_final_status = MagicMock()
        mock_final_status.value = "AUTHORIZED_EXECUTION"

        # Mock evaluate_live_market to return an eligible entry decision
        mock_decision = MagicMock()
        mock_decision.eligible = True
        mock_decision.action = TradeAction.BUY
        mock_decision.decision_id = "dec_123"
        mock_decision.decision_sha256 = "sha_123"
        mock_decision.rejection_reason = None
        mock_decision.sizing = real_sizing
        mock_decision.breakdown = mock_breakdown
        mock_decision.final_position_size = 50.0
        mock_decision.gated = False
        mock_decision.signal_eligible = True
        mock_decision.live_authorized = True
        mock_decision.final_status = mock_final_status
        mock_decision.model_version = "v1"
        mock_decision.artifact_hash = "hash_123"
        mock_decision.feature_schema_version = "v1"
        mock_decision.deployment_id = "dep_123"
        mock_decision.paper_run_id = "paper_123"
        mock_decision.cycle_id = "cycle_123"
        mock_decision.decision_context = "entry"
        mock_decision.caller_context = "auto_trader"

        mock_eval = MagicMock()
        mock_eval.entry_decision = mock_decision
        mock_eval.result = MagicMock()
        mock_eval.result.to_dict.return_value = {"eligible": True, "action": "BUY"}

        import btc_scraper.ml_engine.production_evaluator as prod_eval_mod
        monkeypatch.setattr(prod_eval_mod, "evaluate_live_market", MagicMock(return_value=mock_eval))

        analysis_map = {
            "BTC:BINANCE": {
                "coin": "BTC",
                "close": 202.0,
                "timeframe": "15m",
                "history": history,
                "signal": "BUY",
                "signal_score": {
                    "score": 85,
                    "strength": 85,
                    "meta_probability": 0.90,
                    "meta_confidence": 0.90,
                    "action": "BUY",
                    "rr1": 2.0,
                },
                "tp_sl": {"tp1": 210.0, "sl": 195.0, "rr1": 2.0},
            }
        }

        results = await trader.evaluate_and_trade(analysis_map)
        assert len(results) == 1
        res = results[0]
        assert res["order_id"] == "paper_test_123"
        assert res["status"] == "paper_submitted"
        assert res["is_paper"] is True
        engine.submit_paper.assert_called_once()

    asyncio.run(_run())


def test_true_end_to_end_binance_rest_to_submit_paper(monkeypatch):
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    async def _run():
        import btc_scraper.trading.auto_trader as auto_trader_mod
        import btc_scraper.trading.exposure_manager as exp_mgr_mod
        import btc_scraper.trading.position_tracker as pos_trk_mod
        monkeypatch.setattr(auto_trader_mod, "runtime_evidence_eligible", lambda: False)
        monkeypatch.setattr(exp_mgr_mod.exposure_manager, "get_open_positions", lambda: [])
        monkeypatch.setattr(pos_trk_mod, "get_open_positions", lambda: [])

        trader = AutoTrader()
        monkeypatch.setattr(trader, "get_last_exit_timestamps", lambda: {})
        now_utc = datetime.datetime.now(timezone.utc)
        # Base time 99 15-min intervals in the past
        base_time = now_utc - datetime.timedelta(minutes=15 * 99)
        history = []
        # Create 99 closed candles + 1 forming/unclosed candle
        for i in range(100):
            t_open = base_time + datetime.timedelta(minutes=15 * i)
            t_close = t_open + datetime.timedelta(minutes=14, seconds=59, milliseconds=999)
            t_local_str = (t_open + datetime.timedelta(hours=7)).strftime("%Y-%m-%d %H:%M")
            is_closed = (i < 99)  # Last candle is forming/unclosed
            history.append({
                "time": t_local_str,
                "time_utc": t_open.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "open_time_utc": t_open.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "close_time_utc": t_close.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                "open": 100.0 + i,
                "high": 105.0 + i,
                "low": 95.0 + i,
                "close": 102.0 + i,
                "volume": 10.0,
                "closed": is_closed,
                "is_closed": is_closed,
            })

        mock_fill = MagicMock()
        mock_fill.fill_id = "fill_e2e_123"

        mock_rec = MagicMock()
        mock_rec.execution_id = "paper_e2e_123"
        mock_rec.status = "paper_submitted"
        mock_rec.avg_fill_price = 202.0
        mock_rec.guard_action = "ALLOW"
        mock_rec.expected_slippage_bps = 5.0
        mock_rec.liquidity_score = 1.0
        mock_rec.execution_mode = "paper"
        mock_rec.fill_source = "simulated"
        mock_rec.paper_run_id = "test_run_e2e"
        mock_rec.cycle_id = "cycle_e2e"
        mock_rec.prediction_id = "pred_e2e"
        mock_rec.signal_id = "sig_e2e"
        mock_rec.entry_decision_id = "dec_e2e"
        mock_rec.reservation_id = "res_e2e"
        mock_rec.idempotency_key = "idemp_e2e"
        mock_rec.client_order_id = "client_e2e"
        mock_rec.exchange_order_id = "ex_e2e"
        mock_rec.fills = [mock_fill]
        mock_rec.position_id = "pos_e2e"
        mock_rec.lifecycle_schema_version = "trade-lifecycle-v1"

        engine = trader._get_execution_engine()
        engine.submit_paper = MagicMock(return_value=mock_rec)

        analysis_map = {
            "BTC:BINANCE": {
                "coin": "BTC",
                "close": 202.0,
                "timeframe": "15m",
                "history": history,
                "signal": "BUY",
                "signal_score": {
                    "score": 85,
                    "strength": 85,
                    "meta_probability": 0.90,
                    "meta_confidence": 0.90,
                    "action": "BUY",
                    "rr1": 2.0,
                    "model_family": "xgboost",
                    "model_version": "v1",
                    "artifact_hash": "hash_e2e",
                    "artifact_sha256": "hash_e2e",
                    "feature_schema_version": "v1",
                    "feature_schema_hash": "v1",
                },
                "tp_sl": {"tp1": 210.0, "sl": 195.0, "rr1": 2.0},
                "model_version": "v1",
                "artifact_hash": "hash_e2e",
                "feature_schema_version": "v1",
                "deployment_id": "dep_e2e",
                "cycle_id": "cycle_e2e",
                "paper_run_id": "paper_e2e",
            }
        }

        results = await trader.evaluate_and_trade(analysis_map)
        assert len(results) == 1
        res = results[0]
        assert res["order_id"] == "paper_e2e_123"
        assert res["status"] == "paper_submitted"
        assert res["is_paper"] is True
        engine.submit_paper.assert_called_once()

    asyncio.run(_run())


def test_websocket_parser_and_candlestore_preserves_closed_contract():
    from btc_scraper.exchanges.binance_ws import _parse_kline_event
    from btc_scraper.core.candle_store import CandleStore

    msg_forming = {
        "e": "kline",
        "s": "BTCUSDT",
        "k": {
            "t": 1788957000000,
            "T": 1788957899999,
            "i": "15m",
            "o": "100.0",
            "h": "105.0",
            "l": "95.0",
            "c": "102.0",
            "v": "10.0",
            "x": False,  # forming candle
        },
    }
    parsed = _parse_kline_event(msg_forming)
    assert parsed is not None
    assert parsed["is_closed"] is False
    assert parsed["candle"]["closed"] is False
    assert parsed["candle"]["is_closed"] is False
    assert parsed["candle"]["open_time_utc"] == "2026-09-09T12:30:00Z"

    store = CandleStore()
    store.update("BTC", "15m", parsed["candle"], is_closed=False)
    stored_candles = store.get("BTC", "15m")
    assert len(stored_candles) == 1
    assert stored_candles[0]["closed"] is False
    assert stored_candles[0]["is_closed"] is False

    # Check that _observation_rows filters out forming candles (returns [] when no closed candles exist)
    eval_time = datetime.datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
    obs = _observation_rows({"history": stored_candles}, eval_time)
    assert len(obs) == 0  # No dummy row fabricated; forming candle correctly excluded!


def test_bybit_okx_fallbacks_populate_candle_contract(monkeypatch):
    async def _run():
        from unittest.mock import AsyncMock
        from btc_scraper.exchanges.binance import _fetch_from_bybit, _fetch_from_okx

        # Mock aiohttp response for Bybit
        mock_bybit_resp = MagicMock()
        mock_bybit_resp.raise_for_status = MagicMock()
        mock_bybit_resp.json = AsyncMock(return_value={
            "retCode": 0,
            "result": {
                "list": [
                    ["1788957000000", "100.0", "105.0", "95.0", "102.0", "10.0"]
                ]
            }
        })
        mock_cm_bybit = MagicMock()
        mock_cm_bybit.__aenter__ = AsyncMock(return_value=mock_bybit_resp)
        mock_cm_bybit.__aexit__ = AsyncMock(return_value=None)
        mock_sess_bybit = MagicMock()
        mock_sess_bybit.get = MagicMock(return_value=mock_cm_bybit)

        bybit_candles = await _fetch_from_bybit("BTCUSDT", "15m", 1, mock_sess_bybit)
        assert len(bybit_candles) == 1
        assert "open_time_utc" in bybit_candles[0]
        assert "close_time_utc" in bybit_candles[0]
        assert "closed" in bybit_candles[0]
        assert "is_closed" in bybit_candles[0]

        # Mock aiohttp response for OKX
        mock_okx_resp = MagicMock()
        mock_okx_resp.raise_for_status = MagicMock()
        mock_okx_resp.json = AsyncMock(return_value={
            "code": "0",
            "data": [
                ["1788957000000", "100.0", "105.0", "95.0", "102.0", "10.0"]
            ]
        })
        mock_cm_okx = MagicMock()
        mock_cm_okx.__aenter__ = AsyncMock(return_value=mock_okx_resp)
        mock_cm_okx.__aexit__ = AsyncMock(return_value=None)
        mock_sess_okx = MagicMock()
        mock_sess_okx.get = MagicMock(return_value=mock_cm_okx)

        okx_candles = await _fetch_from_okx("BTC", "15m", 1, mock_sess_okx)
        assert len(okx_candles) == 1
        assert "open_time_utc" in okx_candles[0]
        assert "close_time_utc" in okx_candles[0]
        assert "closed" in okx_candles[0]
        assert "is_closed" in okx_candles[0]

    asyncio.run(_run())


def test_full_e2e_producer_candlestore_analyze_market_evaluator_real_execution(monkeypatch):
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    async def _run():
        import btc_scraper.trading.auto_trader as auto_trader_mod
        import btc_scraper.trading.exposure_manager as exp_mgr_mod
        import btc_scraper.trading.position_tracker as pos_trk_mod
        import btc_scraper.execution.execution_engine as exec_eng_mod
        import btc_scraper.core.paths as paths_mod
        import time
        from btc_scraper.core.candle_store import CandleStore
        from btc_scraper.exchanges.binance import _fetch_from_domains
        from btc_scraper.analysis.core import analyze_market

        monkeypatch.setattr(auto_trader_mod, "runtime_evidence_eligible", lambda: False)
        monkeypatch.setattr(exec_eng_mod, "runtime_evidence_eligible", lambda: False)
        monkeypatch.setattr(paths_mod, "runtime_evidence_eligible", lambda: False)
        monkeypatch.setattr(exp_mgr_mod.exposure_manager, "get_open_positions", lambda: [])
        monkeypatch.setattr(pos_trk_mod, "get_open_positions", lambda: [])

        # 1. MOCK REST PRODUCER HTTP RESPONSE (Binance 100 klines via aiohttp)
        class MockAiohttpResp:
            def __init__(self, data):
                self._data = data
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def raise_for_status(self):
                pass
            async def json(self):
                return self._data

        def mock_aiohttp_get(*args, **kwargs):
            now_ms = int(time.time() * 1000)
            base_ms = now_ms - (15 * 60 * 1000 * 104)
            klines = []
            for i in range(105):
                open_ms = base_ms + (15 * 60 * 1000 * i)
                close_ms = open_ms + (15 * 60 * 1000) - 1
                open_val = 100.0 + i
                close_val = 102.0 + i
                high_val = max(open_val, close_val) + 5.0
                low_val = min(open_val, close_val) - 5.0
                klines.append([
                    open_ms,
                    str(open_val),
                    str(high_val),
                    str(low_val),
                    str(close_val),
                    "10000.0",
                    close_ms,
                    "1020000.0",
                    100,
                    "5000.0",
                    "510000.0",
                    "0",
                ])
            return MockAiohttpResp(klines)

        import aiohttp
        monkeypatch.setattr(aiohttp.ClientSession, "get", mock_aiohttp_get)

        # 2. RUN REAL PRODUCER LINEAGE (_fetch_from_domains)
        async with aiohttp.ClientSession() as sess:
            producer_candles = await _fetch_from_domains("BTCUSDT", "15m", 105, sess)
        assert len(producer_candles) == 105
        assert producer_candles[-1]["closed"] is False  # Forming candle dynamically identified!

        # 3. RUN REAL CANDLESTORE LINEAGE (store.update)
        store = CandleStore()
        for c in producer_candles:
            store.update("BTC", "15m", c)

        stored_candles = store.get("BTC", "15m")
        assert len(stored_candles) == 105
        assert stored_candles[-1]["closed"] is False

        # 4. RUN REAL ANALYZE_MARKET LINEAGE (analyze_market)
        ana = analyze_market(stored_candles, coin_name="BTC")
        assert len(ana["history"]) >= 73
        assert ana["history"][-1]["closed"] is False

        # Populate signal metadata for evaluation
        ana["coin"] = "BTC"
        ana["timeframe"] = "15m"
        ana["close"] = float(stored_candles[-1]["close"])
        ana["volume"] = 10000.0
        ana["signal"] = "BUY"
        ana["signal_id"] = "sig_e2e_real"
        ana["prediction_id"] = "pred_e2e_real"
        ana["entry_decision_id"] = "dec_e2e_real"
        ana["signal_score"] = {
            "score": 85,
            "strength": 85,
            "meta_probability": 0.90,
            "meta_confidence": 0.90,
            "action": "BUY",
            "rr1": 2.0,
            "model_family": "xgboost",
            "model_version": "v1",
            "artifact_hash": "hash_e2e_real",
            "artifact_sha256": "hash_e2e_real",
            "feature_schema_version": "v1",
            "feature_schema_hash": "v1",
            "signal_id": "sig_e2e_real",
            "prediction_id": "pred_e2e_real",
        }
        ana["tp_sl"] = {"tp1": 210.0, "sl": 195.0, "rr1": 2.0}
        ana["model_version"] = "v1"
        ana["artifact_hash"] = "hash_e2e_real"
        ana["feature_schema_version"] = "v1"
        ana["deployment_id"] = "dep_e2e_real"
        ana["cycle_id"] = "cycle_e2e_real"
        ana["paper_run_id"] = "paper_e2e_real"

        trader = AutoTrader()
        monkeypatch.setattr(trader, "get_last_exit_timestamps", lambda: {})
        analysis_map = {"BTC:BINANCE": ana}

        from btc_scraper.ml_engine.production_evaluator import evaluate_live_market
        eval_res = evaluate_live_market(analysis=ana, coin="BTC", trader=trader, current_balance=500.0, var_cap=None, exposure_cap=None)
        print("DEBUG eval_res entry_decision:", eval_res.entry_decision)

        # 5. RUN REAL EVALUATOR & REAL EXECUTION ENGINE LINEAGE
        results = await trader.evaluate_and_trade(analysis_map)
        assert len(results) == 1
        res = results[0]
        print("DEBUG True E2E res:", res)
        assert res["is_paper"] is True
        assert res["status"] in ("paper_submitted", "FILLED")
        assert res["order_id"] is not None
        assert len(res["order_id"]) > 0

    asyncio.run(_run())
