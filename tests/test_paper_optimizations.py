"""
tests/test_paper_optimizations.py

Unit tests for paper/demo performance optimizations:
1. Startup mode resolution and non-blocking cache startup.
2. Parse.bot cron slot persistence across scheduler restarts.
3. Entry-only lazy PyTorch isolation (torch NOT in sys.modules).
4. Dynamic PPO exit stack loading when requested.
5. CycleMetricsCollector unclamped measurements and invariant violation detection.
6. CandleStore live sliding-window bounding.
"""

import os
import sys
import json
import time
import tempfile
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    sub_env = dict(os.environ)
    sub_env["PYTHONUTF8"] = "1"
    sub_env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        sub_env.update(extra)
    return sub_env


# ─── Test 1: Startup Mode Resolution ──────────────────────────────────────────

def test_resolve_startup_mode():
    from btc_scraper.collectors.alternative_scheduler import resolve_startup_mode

    # Explicit override always wins
    assert resolve_startup_mode(configured="blocking") == "blocking"
    assert resolve_startup_mode(configured="background") == "background"
    assert resolve_startup_mode(configured="cache") == "cache"

    # Environment variable override
    with patch.dict(os.environ, {"ALTERNATIVE_DATA_STARTUP_MODE": "background"}):
        assert resolve_startup_mode() == "background"

    # Default in paper/demo or once mode is "cache"
    with patch.dict(os.environ, {"ALTERNATIVE_DATA_STARTUP_MODE": "", "BTC_RUNTIME_ENVIRONMENT": "paper"}):
        assert resolve_startup_mode() == "cache"

    with patch.dict(os.environ, {"ALTERNATIVE_DATA_STARTUP_MODE": "", "AUTO_TRADE_DRY_RUN": "true"}):
        assert resolve_startup_mode() == "cache"


# ─── Test 2: Startup Mode "cache" Does Not Block and Loads Existing Data ─────

def test_startup_mode_cache_non_blocking():
    from btc_scraper.collectors.alternative_scheduler import AlternativeDataScheduler

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        cache_file = tmp_path / "alternative_data.json"
        dummy_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fng": {"value": 55, "classification": "Greed"},
            "cbbi": {"confidence": 0.6},
        }
        cache_file.write_text(json.dumps(dummy_data), encoding="utf-8")

        with patch.dict(os.environ, {"BTC_RUNTIME_ROOT": str(tmp_path), "BTC_DATA_DIR": ""}):
            scheduler = AlternativeDataScheduler(output_path=cache_file)
            t0 = time.perf_counter()
            data = scheduler.run_startup(mode="cache")
            elapsed = time.perf_counter() - t0

            # Cache startup must complete in under 100ms
            assert elapsed < 0.1, f"Cache startup took too long: {elapsed:.4f}s"
            assert data is not None
            assert data["fng"]["value"] == 55


# ─── Test 3: Parse.bot Cron Slot Persistence ─────────────────────────────────

def test_parsebot_cron_slot_persistence():
    from btc_scraper.collectors.alternative_scheduler import AlternativeDataScheduler

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        cache_file = tmp_path / "alternative_data.json"
        cache_file.write_text(json.dumps({"test": 1}), encoding="utf-8")

        with patch.dict(os.environ, {"BTC_RUNTIME_ROOT": str(tmp_path), "BTC_DATA_DIR": ""}):
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            test_recent_slot = f"{today_str}_12:00"
            test_all_slot = f"{today_str}_00:00"

            # Create scheduler and record slot completion
            s1 = AlternativeDataScheduler(output_path=cache_file)
            s1._last_recent_run_slot = test_recent_slot
            s1._last_all_run_slot = test_all_slot
            s1._persist_slot("_last_recent_run_slot", test_recent_slot)
            s1._persist_slot("_last_all_run_slot", test_all_slot)

            # Verify persistent slots file exists
            assert s1._slots_file.exists()
            content = json.loads(s1._slots_file.read_text(encoding="utf-8"))
            assert content.get("recent") == test_recent_slot
            assert content.get("all") == test_all_slot

            # New scheduler instance in a new "process" should load slots automatically
            s2 = AlternativeDataScheduler(output_path=cache_file)
            assert s2._last_recent_run_slot == test_recent_slot
            assert s2._last_all_run_slot == test_all_slot


# ─── Test 4: Entry-Only Stack Leaves PyTorch Unloaded in Subprocess ───────────

def test_entry_only_torch_isolation():
    """Confirms that importing position_tracker and main does NOT load torch into sys.modules."""
    code = f"""
import sys, os
sys.path.insert(0, r"{REPO_ROOT}")
os.environ["BTC_RUNTIME_ENVIRONMENT"] = "paper"
os.environ["AUTO_TRADE_DRY_RUN"] = "true"
os.environ["LIVE_TRADING_ENABLED"] = "false"
os.environ["BTC_EVIDENCE_ELIGIBLE"] = "false"

import btc_scraper.trading.position_tracker as pt
import btc_scraper.core.runtime_ownership
from btc_scraper.ml_engine.inference_coordinator import get_inference_coordinator

has_torch = "torch" in sys.modules
print(f"TORCH_IN_SYS_MODULES:{{has_torch}}")
assert not has_torch, f"torch was eagerly loaded into sys.modules: {{[m for m in sys.modules if 'torch' in m]}}"
"""
    res = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_make_subprocess_env(),
    )
    assert res.returncode == 0, f"Subprocess failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "TORCH_IN_SYS_MODULES:False" in res.stdout


# ─── Test 5: Dynamic PPO Exit Stack Loading ───────────────────────────────────

def test_dynamic_ppo_loading_on_demand():
    """Confirms that calling pt.get_ppo_model() loads torch lazily and successfully returns RecurrentPPO."""
    code = f"""
import sys, os
sys.path.insert(0, r"{REPO_ROOT}")
os.environ["BTC_RUNTIME_ENVIRONMENT"] = "paper"
os.environ["AUTO_TRADE_DRY_RUN"] = "true"
os.environ["LIVE_TRADING_ENABLED"] = "false"
os.environ["BTC_EVIDENCE_ELIGIBLE"] = "false"

import btc_scraper.trading.position_tracker as pt
assert "torch" not in sys.modules, "torch should not be loaded before get_ppo_model()"

model = pt.get_ppo_model()
assert "torch" in sys.modules, "torch should be loaded after get_ppo_model()"
assert model is not None, "get_ppo_model() should return loaded model"
print("PPO_DYNAMIC_LOAD_SUCCESS")
"""
    res = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_make_subprocess_env(),
    )
    assert res.returncode == 0, f"Subprocess failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "PPO_DYNAMIC_LOAD_SUCCESS" in res.stdout


# ─── Test 6: CycleMetricsCollector Unclamped Measurements and Validation ──────

def test_collector_unclamped_and_validation():
    # Import CycleMetricsCollector from benchmark script
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from run_paper_benchmark import CycleMetricsCollector

    # Case A: Valid normal cycle with expected counts
    c1 = CycleMetricsCollector()
    c1.start_cycle()
    time.sleep(0.01)
    for _ in range(36):
        c1.record("market_data_fetch", 0.001, 0.005)
    for _ in range(2):
        c1.record("alternative_macro_collection", 0.001, 0.002)
    c1.record("indicator_calculation", 0.005, 0.008)
    for _ in range(10):
        c1.record("context_causal_processing", 0.008, 0.010)
    for _ in range(9):
        c1.record("model_inference", 0.010, 0.012)
    for _ in range(2):
        c1.record("decision_sizing", 0.012, 0.014)
    c1.record("persistence", 0.014, 0.016)
    time.sleep(0.02)
    c1.end_cycle()

    res1 = c1.compile()
    assert "stages" in res1
    assert res1["stages"]["market_data_fetch"]["wall_sec"] > 0
    # Invariant: wall_sec must never be clamped
    assert "wall_sec" in res1["stages"]["market_data_fetch"]
    assert res1["measurement_valid"] is True, f"Expected valid cycle but got errors: {res1['validation_errors']}"

    # Case B: Invariant violation: stage duration exceeds total cycle time
    c2 = CycleMetricsCollector()
    c2.cycle_start = 100.0
    c2.cycle_end = 101.0  # total wall = 1.0s
    # Stage duration = 2.0s (> total wall)
    c2.record("market_data_fetch", 100.0, 102.0)

    res2 = c2.compile()
    # Invariant: wall_sec must NOT be clamped to 1.0
    assert res2["stages"]["market_data_fetch"]["wall_sec"] == 2.0
    assert res2["measurement_valid"] is False
    assert any("exceeds" in err or "Invariant violation" in err for err in res2["validation_errors"])


# ─── Test 7: CandleStore Live Sliding-Window Bounding ────────────────────────

def test_candle_store_sliding_window_bound():
    from btc_scraper.core.candle_store import CandleStore

    store = CandleStore(max_candles=50)
    coin = "BTC"
    interval = "15m"

    # Seed 60 candles via update
    for i in range(60):
        c = {
            "time": f"2026-10-31T12:{i:02d}:00Z",
            "open": 50000.0 + i,
            "high": 50010.0 + i,
            "low": 49990.0 + i,
            "close": 50005.0 + i,
            "volume": 10.0,
            "is_closed": True,
        }
        store.update(coin, interval, c, is_closed=True)

    candles = store.get(coin, interval)
    assert len(candles) == 50, f"Candle store exceeded max_candles bound: {len(candles)}"
    # Verify the oldest candles were trimmed (first remaining timestamp should be i=10)
    assert candles[0]["time"] == "2026-10-31T12:10:00Z"
    assert candles[-1]["time"] == "2026-10-31T12:59:00Z"


# ─── Test 8: AgentOrchestrator Entry-Only Isolation (Zero Torch Load) ────────

def test_orchestrator_lazy_rl_exit_isolation():
    """Confirms AgentOrchestrator runs entry cycle without loading PyTorch or PPO model."""
    code = f"""
import sys, os, asyncio
sys.path.insert(0, r"{REPO_ROOT}")
os.environ["BTC_RUNTIME_ENVIRONMENT"] = "paper"
os.environ["AUTO_TRADE_DRY_RUN"] = "true"
os.environ["LIVE_TRADING_ENABLED"] = "false"
os.environ["BTC_EVIDENCE_ELIGIBLE"] = "false"

from btc_scraper.ml_engine.multi_agent import AgentOrchestrator

orch = AgentOrchestrator()
assert orch.rl_exit.model is None, "RLExitAgent should not preload model at init"
assert "torch" not in sys.modules, "torch should not be loaded at AgentOrchestrator init"

# Run a cycle with empty open_positions
ctx = {{"open_positions": []}}
res = asyncio.run(orch.run_cycle(ctx, mtf_candles_dict={{}}))
assert "torch" not in sys.modules, "torch should NOT be loaded after cycle with 0 open positions"
assert res.get("rl_model_loaded") is False, "rl_model_loaded should be False"
print("ORCH_LAZY_SUCCESS")
"""
    res = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_make_subprocess_env(),
    )
    assert res.returncode == 0, f"Subprocess failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "ORCH_LAZY_SUCCESS" in res.stdout


# ─── Test 9: AgentOrchestrator Dynamic PPO Loading on Open Positions ─────────

def test_orchestrator_dynamic_ppo_loading_on_open_positions():
    """Confirms AgentOrchestrator lazily loads RecurrentPPO when open_positions > 0."""
    code = f"""
import sys, os, asyncio, tempfile
from pathlib import Path
sys.path.insert(0, r"{REPO_ROOT}")
os.environ["BTC_RUNTIME_ENVIRONMENT"] = "paper"
os.environ["AUTO_TRADE_DRY_RUN"] = "true"
os.environ["LIVE_TRADING_ENABLED"] = "false"
os.environ["BTC_EVIDENCE_ELIGIBLE"] = "false"

with tempfile.TemporaryDirectory() as td:
    tpath = Path(td)
    os.environ["BTC_RUNTIME_ROOT"] = str(tpath)
    os.environ["BTC_FALLBACK_BUFFER_DB"] = str(tpath / "fallback_buffer.db")
    import btc_scraper.trading.position_tracker as pt
    pt.add_position("BTC", 50000.0, "LONG", note="test", invested_usdt=100.0)
    assert len(pt.get_open_positions()) == 1

    from btc_scraper.ml_engine.multi_agent import AgentOrchestrator
    orch = AgentOrchestrator()
    assert "torch" not in sys.modules, "torch should not be loaded at init"

    res = asyncio.run(orch.run_cycle({{}}, {{}}))
    assert "torch" in sys.modules, "torch should be loaded dynamically when open_positions > 0"
    assert res.get("rl_model_loaded") is True, "rl_model_loaded should be True"
    print("ORCH_DYNAMIC_LOAD_SUCCESS")
"""
    res = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_make_subprocess_env(),
    )
    assert res.returncode == 0, f"Subprocess failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "ORCH_DYNAMIC_LOAD_SUCCESS" in res.stdout


# ─── Test 10: Precision Monotonic Milestones and Invariant Validation ─────────

def test_milestone_tracker_monotonicity_and_distinct_timestamps():
    from btc_scraper.core.milestones import MilestoneTracker

    tracker = MilestoneTracker()
    tracker.reset()

    # Step-by-step recording with distinct timestamps
    tracker.record("process_started")
    time.sleep(0.002)
    tracker.record("imports_ready")
    time.sleep(0.002)
    tracker.record("alternative_cache_ready")
    time.sleep(0.002)
    tracker.record("market_data_ready")
    time.sleep(0.002)
    tracker.record("first_analysis_ready")
    time.sleep(0.002)
    tracker.record("all_analysis_ready")
    time.sleep(0.002)
    tracker.record("first_prediction_ready")
    time.sleep(0.002)
    tracker.record("all_predictions_ready")
    time.sleep(0.002)
    tracker.record("first_final_decision_ready")
    time.sleep(0.002)
    tracker.record("cycle_complete")

    valid, errors = tracker.validate_invariants()
    assert valid is True, f"Milestone validation failed: {errors}"
    assert len(errors) == 0

    t_ana = tracker.get("first_analysis_ready")
    t_pred = tracker.get("first_prediction_ready")
    t_dec = tracker.get("first_final_decision_ready")
    assert t_ana is not None and t_pred is not None and t_dec is not None
    assert t_ana < t_pred < t_dec, "Milestones must have strictly distinct ordered timestamps"

    # Inversion detection
    tracker_bad = MilestoneTracker()
    tracker_bad._milestones = {
        "process_started": 10.0,
        "imports_ready": 10.1,
        "market_data_ready": 10.2,
        "first_analysis_ready": 10.5,
        "first_prediction_ready": 10.3,  # Inversion: pred before ana
        "first_final_decision_ready": 10.6,
        "cycle_complete": 10.7,
    }
    bad_valid, bad_errors = tracker_bad.validate_invariants()
    assert bad_valid is False
    assert any("first_analysis_ready" in e and "first_prediction_ready" in e for e in bad_errors)

    # Collision detection
    tracker_coll = MilestoneTracker()
    tracker_coll._milestones = {
        "process_started": 10.0,
        "imports_ready": 10.1,
        "market_data_ready": 10.2,
        "first_analysis_ready": 10.4,
        "all_analysis_ready": 10.4,
        "first_prediction_ready": 10.4,  # Identical timestamp collision
        "all_predictions_ready": 10.5,
        "first_final_decision_ready": 10.6,
        "cycle_complete": 10.7,
    }
    coll_valid, coll_errors = tracker_coll.validate_invariants()
    assert coll_valid is False
    assert any("collision" in e.lower() or ">=" in e for e in coll_errors)


# ─── Test 11: Controlled Inference Scope A/B (Execution vs Analysis) ──────────

def test_paper_inference_scope_execution_vs_analysis():
    from btc_scraper.ml_engine.multi_agent import SignalGeneratorAgent
    from unittest.mock import MagicMock

    symbols = ["BTC", "ETH", "BNB", "SOL", "DOGE", "NEAR", "TRX", "IOTA", "ZEC"]

    # 1. Execution Scope: only BTC, ETH, BNB get model inference; other 6 get skipped
    with patch.dict(os.environ, {
        "PAPER_INFERENCE_SCOPE": "execution",
        "AUTO_TRADE_COINS": "BTC,ETH,BNB",
        "BTC_RUNTIME_ENVIRONMENT": "paper",
        "AUTO_TRADE_DRY_RUN": "true",
    }):
        agent = SignalGeneratorAgent()
        mock_coordinator = MagicMock()
        mock_prediction = MagicMock()
        mock_prediction.to_dict.return_value = {"prediction": 0.65, "model_family": "lgbm"}
        mock_coordinator.predict_once.return_value = mock_prediction

        analysis = {
            f"{c}:15m": {
                "coin": c,
                "symbol": f"{c}USDT",
                "timeframe": "15m",
                "action": "BUY",
                "close": 100.0,
                "atr": 2.0,
                "signal": "BUY",
            }
            for c in symbols
        }
        context = {"analysis": analysis}

        with patch("btc_scraper.ml_engine.inference_coordinator.get_inference_coordinator", return_value=mock_coordinator), \
             patch("btc_scraper.ml_engine.signal_score.evaluate_signal_score", return_value={"action": "BUY", "score": 75}):
            res = agent.run(context)

        # Coordinator should be called exactly 3 times (BTC, ETH, BNB)
        assert mock_coordinator.predict_once.call_count == 3
        called_coins = [call.args[1] if len(call.args) > 1 else call.kwargs.get("symbol") for call in mock_coordinator.predict_once.call_args_list]
        assert set(called_coins) == {"BTC", "ETH", "BNB"}

        # UI coverage: signals_info must contain all 9 coins
        assert len(res["signals_info"]) == 9
        non_exec_signals = [s for s in res["signals_info"] if s["coin"] not in {"BTC", "ETH", "BNB"}]
        assert len(non_exec_signals) == 6
        for s in non_exec_signals:
            assert s["execution_eligible"] is False
            assert s["skip_reason"] == "ANALYSIS_ONLY_NOT_IN_EXECUTION_UNIVERSE"

    # 2. Analysis Scope: all 9 coins get model inference
    with patch.dict(os.environ, {
        "PAPER_INFERENCE_SCOPE": "analysis",
        "AUTO_TRADE_COINS": "BTC,ETH,BNB",
        "BTC_RUNTIME_ENVIRONMENT": "paper",
        "AUTO_TRADE_DRY_RUN": "true",
    }):
        agent = SignalGeneratorAgent()
        mock_coordinator = MagicMock()
        mock_prediction = MagicMock()
        mock_prediction.to_dict.return_value = {"prediction": 0.65, "model_family": "lgbm"}
        mock_coordinator.predict_once.return_value = mock_prediction

        analysis2 = {
            f"{c}:15m": {
                "coin": c,
                "symbol": f"{c}USDT",
                "timeframe": "15m",
                "action": "BUY",
                "close": 100.0,
                "atr": 2.0,
                "signal": "BUY",
            }
            for c in symbols
        }
        context2 = {"analysis": analysis2}

        with patch("btc_scraper.ml_engine.inference_coordinator.get_inference_coordinator", return_value=mock_coordinator), \
             patch("btc_scraper.ml_engine.signal_score.evaluate_signal_score", return_value={"action": "BUY", "score": 75}):
            res2 = agent.run(context2)

        # In analysis mode, all 9 coins are evaluated through InferenceCoordinator
        assert mock_coordinator.predict_once.call_count == 9
        assert len(res2["signals_info"]) == 9


# ─── Test 12: Alternative Mode CLI Parsing and Quality Tagging ────────────────

def test_alternative_mode_cli_and_quality_tagging():
    import argparse
    from btc_scraper.ml_engine.multi_agent import SignalGeneratorAgent
    from unittest.mock import MagicMock

    # 1. CLI parser tests
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--alternative-mode",
        choices=["cache", "refresh", "blocking", "background"],
        default=None,
    )
    args_cache = parser.parse_args(["--alternative-mode", "cache"])
    assert args_cache.alternative_mode == "cache"

    args_refresh = parser.parse_args(["--alternative-mode", "refresh"])
    assert args_refresh.alternative_mode == "refresh"

    args_default = parser.parse_args([])
    assert args_default.alternative_mode is None

    # 2. Quality status contract tagging on analysis dict
    quality_cases = [
        ("available", "COMPLETE"),
        ("partial", "PARTIAL"),
        ("stale", "STALE"),
        ("unavailable", "NEUTRAL_DEFAULTS"),
    ]

    for status_str, expected_quality in quality_cases:
        with patch.dict(os.environ, {"PAPER_INFERENCE_SCOPE": "analysis"}):
            agent = SignalGeneratorAgent()
            mock_coordinator = MagicMock()
            mock_prediction = MagicMock()
            mock_prediction.to_dict.return_value = {"prediction": 0.5}
            mock_coordinator.predict_once.return_value = mock_prediction

            ana = {
                "BTC:15m": {
                    "coin": "BTC",
                    "symbol": "BTCUSDT",
                    "timeframe": "15m",
                    "action": "BUY",
                    "close": 100.0,
                    "atr": 2.0,
                    "signal": "BUY",
                }
            }
            context = {"analysis": ana}

            dummy_ref = {"status": status_str, "timestamp": "2026-10-31T12:00:00Z"}
            with patch("btc_scraper.collectors.alternative_reference.load_alternative_reference", return_value=dummy_ref), \
                 patch("btc_scraper.ml_engine.inference_coordinator.get_inference_coordinator", return_value=mock_coordinator), \
                 patch("btc_scraper.ml_engine.signal_score.evaluate_signal_score", return_value={"action": "BUY"}):
                res = agent.run(context)
                assert ana["BTC:15m"]["prediction_input_quality"] == expected_quality


# ─── Test 13: AutoTrader Single-Writer Bounded Latency Append Persistence ─────

def test_auto_trader_append_log_bounded_latency():
    """Validates that _append_log performs bounded latency appends under single-writer contract and produces valid JSON array on disk."""
    import json
    from btc_scraper.trading.auto_trader import _append_log

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / "auto_trade_log.json"

        with patch.dict(os.environ, {"BTC_RUNTIME_ROOT": str(tmp_path), "BTC_LOG_DIR": ""}):
            # 1. Append to fresh/empty file
            entry1 = {"id": 1, "coin": "BTC", "action": "HOLD", "reason": "NO_VIABLE_ECONOMIC_CANDIDATE"}
            _append_log(entry1)

            assert log_file.exists()
            with open(log_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            assert len(loaded) == 1
            assert loaded[0]["id"] == 1

            # 2. Append second and third entries via seek-and-append
            entry2 = {"id": 2, "coin": "ETH", "action": "HOLD", "reason": "NO_VIABLE_ECONOMIC_CANDIDATE"}
            entry3 = {"id": 3, "coin": "BNB", "action": "HOLD", "reason": "NO_VIABLE_ECONOMIC_CANDIDATE"}
            _append_log(entry2)
            _append_log(entry3)

            with open(log_file, "r", encoding="utf-8") as f:
                loaded2 = json.load(f)
            assert len(loaded2) == 3
            assert [e["id"] for e in loaded2] == [1, 2, 3]

            # 3. Pre-seed 1,000 entries and verify append maintains bounded latency
            large_entries = [{"id": 1000 + i, "coin": "BTC", "action": "HOLD"} for i in range(1000)]
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(large_entries, f)

            t0 = time.perf_counter()
            _append_log({"id": 9999, "coin": "SOL", "action": "HOLD"})
            elapsed = time.perf_counter() - t0

            # Bounded write latency < 30ms even on a 1,000-entry file under single-writer contract
            assert elapsed < 0.030, f"Append to 1000-entry file took {elapsed*1000:.2f}ms (> 30ms)"

            with open(log_file, "r", encoding="utf-8") as f:
                loaded_large = json.load(f)
            assert len(loaded_large) == 1001
            assert loaded_large[-1]["id"] == 9999


# ─── Test 14: Shadow Fast Path Isolation & Default Log Preservation ───────────

def test_shadow_fast_path_isolation_and_no_pollution():
    """Confirms that direct fast path executes in an isolated root without modifying default auto_trade_log.json."""
    import asyncio
    from unittest.mock import MagicMock
    from btc_scraper.trading.auto_trader import AutoTrader

    async def _run_async_test():
        default_log = REPO_ROOT / "runtime" / "paper" / "local-paper" / "logs" / "auto_trade_log.json"
        stat_before = None
        if default_log.exists():
            stat_before = (default_log.stat().st_mtime, default_log.stat().st_size)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            isolated_log = tmp_path / "logs" / "auto_trade_log.json"

            with patch.dict(os.environ, {"BTC_RUNTIME_ROOT": str(tmp_path), "BTC_LOG_DIR": ""}):
                trader = AutoTrader()
                payload = {
                    "coin": "BTC",
                    "symbol": "BTCUSDT",
                    "signal": "BUY",
                    "signal_score": {"score": 85, "meta_probability": 0.88},
                    "causal_decision": {
                        "decision_id": "fastpath-isolation-test",
                        "action": "HOLD",
                        "shadow_action": "BUY",
                        "eligible": False,
                        "terminal_status": "HOLD",
                        "rejection_reason": "NO_VIABLE_ECONOMIC_CANDIDATE",
                        "paper_economic_policy": "NO_TRADE_SHADOW",
                    },
                }

                with patch("btc_scraper.trading.auto_trader.exposure_manager.get_open_positions", return_value=[]), \
                     patch("btc_scraper.trading.auto_trader.exposure_manager.calculate_max_size_by_var_limit", return_value=0.0), \
                     patch("btc_scraper.ml_engine.production_evaluator.evaluate_live_market", return_value=None), \
                     patch.object(trader, "_get_execution_engine", return_value=MagicMock()), \
                     patch("btc_scraper.telegram_bot.api.send_telegram_message", return_value=None):

                    res = await trader._process_signal("BTC:Binance", payload)
                    assert res is not None
                    assert res["status"] == "skipped"
                    assert res["reason_skip"] == "NO_VIABLE_ECONOMIC_CANDIDATE"

                # Assert log was written to isolated path
                assert isolated_log.exists()
                with open(isolated_log, "r", encoding="utf-8") as f:
                    entries = json.load(f)
                assert len(entries) == 1
                assert entries[0]["decision_id"] == "fastpath-isolation-test"

        # Assert default production/paper log was NOT modified or touched
        if default_log.exists() and stat_before is not None:
            stat_after = (default_log.stat().st_mtime, default_log.stat().st_size)
            assert stat_before == stat_after, "Default auto_trade_log.json was polluted by fast-path run!"

    asyncio.run(_run_async_test())


# ─── Test 15: Benchmark Script Compiles and Imports Cleanly ──────────────────

def test_benchmark_script_compiles_and_imports():
    """Ensure benchmark scripts compile without syntax errors and import without side-effects."""
    import py_compile
    bench_script = REPO_ROOT / "scripts" / "run_paper_benchmark.py"
    cold_runner = REPO_ROOT / "scripts" / "cold_start_runner.py"
    bench_support = REPO_ROOT / "scripts" / "paper_benchmark_support.py"

    assert bench_script.exists()
    assert cold_runner.exists()
    assert bench_support.exists()

    # Must compile cleanly with 0 errors
    py_compile.compile(str(bench_script), doraise=True)
    py_compile.compile(str(cold_runner), doraise=True)
    py_compile.compile(str(bench_support), doraise=True)

    # Cold runner source must not pre-import run_paper_benchmark
    cold_src = cold_runner.read_text(encoding="utf-8")
    assert "from scripts.run_paper_benchmark" not in cold_src
    assert "import scripts.run_paper_benchmark" not in cold_src

    # Key functions must be importable
    from scripts.run_paper_benchmark import (
        NetworkInterceptor,
        CycleMetricsCollector,
        make_synthetic_candles,
        seed_isolated_runtime_data,
    )
    candles = make_synthetic_candles(50000.0, 5)
    assert len(candles) == 5
    assert candles[0]["close"] > 0


# ─── Test 16: Macro Cache TTL and Stale Degradation ──────────────────────────

def test_macro_cache_ttl_and_stale_degradation():
    """Verify macro state file freshness contract and explicit stale degradation."""
    from btc_scraper.collectors.macro_collector import (
        is_macro_state_fresh,
        fetch_and_save_macro,
        load_macro_state,
        _macro_data_file,
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        macro_file = data_dir / "macro_state.json"

        with patch.dict(os.environ, {
            "BTC_RUNTIME_ROOT": str(tmp_path),
            "BTC_DATA_DIR": str(data_dir),
            "ALTERNATIVE_DATA_STARTUP_MODE": "cache",
            "MACRO_MAX_AGE_SECONDS": "10",
        }):
            if macro_file.exists():
                macro_file.unlink()

            # 1. Non-existent file
            assert not is_macro_state_fresh(macro_file)
            res_default = fetch_and_save_macro()
            assert res_default.get("stale") is True
            assert macro_file.exists()

            # 2. Fresh file (just written)
            assert is_macro_state_fresh(macro_file, max_age_seconds=60)
            res_fresh = fetch_and_save_macro()
            assert res_fresh.get("timestamp") is not None

            # 3. Old file (> TTL)
            old_time = time.time() - 3600  # 1 hour ago
            os.utime(macro_file, (old_time, old_time))
            assert not is_macro_state_fresh(macro_file, max_age_seconds=10)
            res_stale = fetch_and_save_macro()
            assert res_stale.get("stale") is True


# ─── Test 17: Old Sentiment History Marked Stale ─────────────────────────────

def test_old_sentiment_marked_stale():
    """Verify sentiment cache marks older than TTL observations as stale."""
    from datetime import timedelta
    import btc_scraper.core.sentiment as sentiment_mod
    from btc_scraper.core.sentiment import get_market_sentiment

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        hist_path = logs_dir / "sentiment_history.json"

        # Seed with an old observation from 30 days ago
        old_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        with open(hist_path, "w", encoding="utf-8") as f:
            json.dump({
                old_date: {
                    "score": 0.2,
                    "normalized_score": 0.2,
                    "raw_value": 60,
                    "label": "Greed",
                    "observed_at": f"{old_date}T00:00:00Z",
                }
            }, f)

        # Reset in-memory cache
        sentiment_mod._cache = {
            "score": None, "normalized_score": None, "raw_value": None,
            "label": None, "observed_at": None, "observation_date": None,
            "status": "empty", "timestamp": 0.0, "trend": [],
        }

        with patch.dict(os.environ, {
            "BTC_RUNTIME_ROOT": str(tmp_path),
            "BTC_LOG_DIR": str(logs_dir),
            "ALTERNATIVE_DATA_STARTUP_MODE": "cache",
            "SENTIMENT_MAX_AGE_SECONDS": "86400",
        }):
            res = get_market_sentiment()
            assert res.get("stale") is True
            assert res.get("status") == "stale"


# ─── Test 18: CandleStore Freshness Contract & Main Fallback ─────────────────

def test_candle_store_freshness_and_main_fallback():
    """Verify CandleStore is_fresh contract and fallback behavior in main._get_candles_for_coin."""
    import asyncio
    from unittest.mock import MagicMock, AsyncMock
    from btc_scraper.core.candle_store import CandleStore
    import main as main_module

    store = CandleStore(max_candles=50)

    # 1. Empty store is not fresh
    assert not store.is_fresh("BTC", "15m")

    # 2. Store with old candles is not fresh
    old_time = time.time() - 7200  # 2 hours ago
    dt_old = datetime.fromtimestamp(old_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    old_candles = [{
        "time": dt_old,
        "time_utc": dt_old + ":00Z",
        "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50050.0, "volume": 10.0,
        "closed": True, "is_closed": True,
    }]
    store.seed("BTC", "15m", old_candles)
    # Candle timestamp is 2h old, max_age is 1800s (30m)
    assert not store.is_fresh("BTC", "15m", max_age_seconds=1800.0)

    # 3. Store with fresh candles is fresh
    now_time = time.time()
    dt_now = datetime.fromtimestamp(now_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    fresh_candles = [{
        "time": dt_now,
        "time_utc": dt_now + ":00Z",
        "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50050.0, "volume": 10.0,
        "closed": True, "is_closed": True,
    }]
    store.seed("BTC", "15m", fresh_candles)
    assert store.is_fresh("BTC", "15m", max_age_seconds=1800.0)

    # 4. In main._get_candles_for_coin:
    async def _test_main_fallback():
        mock_ws = MagicMock()
        mock_rest = AsyncMock(return_value=[{"source": "REST_FALLBACK"}])

        # A: WS healthy + CandleStore fresh -> uses CandleStore
        mock_ws.is_healthy.return_value = True
        with patch.object(main_module, "_ws_manager", mock_ws), \
             patch.object(main_module, "candle_store", store), \
             patch("btc_scraper.exchanges.binance.fetch_ohlcv", mock_rest):
            res_a = await main_module._get_candles_for_coin("BTC", "15m")
            assert len(res_a) == 1
            assert res_a[0].get("source") != "REST_FALLBACK"
            assert mock_rest.await_count == 0

        # B: WS unhealthy -> falls back to REST
        mock_ws.is_healthy.return_value = False
        with patch.object(main_module, "_ws_manager", mock_ws), \
             patch.object(main_module, "candle_store", store), \
             patch("btc_scraper.exchanges.binance.fetch_ohlcv", mock_rest):
            res_b = await main_module._get_candles_for_coin("BTC", "15m")
            assert res_b == [{"source": "REST_FALLBACK"}]
            assert mock_rest.await_count == 1

    asyncio.run(_test_main_fallback())


# ─── Test 19: Synthetic Candles Interval Timestamp Spacing ────────────────────

def test_synthetic_candles_interval_spacing():
    """Validates that make_synthetic_candles spaces timestamps per timeframe: 15m=900s, 1h=3600s, 4h=14400s, 1d=86400s."""
    from scripts.paper_benchmark_support import make_synthetic_candles

    fixed_end = 1700000000.0
    expected_steps = {
        "15m": 900,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
    }

    for interval, expected_delta in expected_steps.items():
        candles = make_synthetic_candles(50000.0, n=5, interval=interval, end_time=fixed_end)
        assert len(candles) == 5

        # Parse timestamps and check deltas
        parsed_ts = []
        for c in candles:
            dt = datetime.strptime(c["time"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            parsed_ts.append(dt.timestamp())

        for idx in range(1, len(parsed_ts)):
            delta = parsed_ts[idx] - parsed_ts[idx - 1]
            assert delta == expected_delta, f"Expected {expected_delta}s for {interval}, got {delta}s"


# ─── Test 20: CandleStore Rejection of Future Skew and Stale Candles ──────────

def test_candlestore_freshness_future_skew_rejection():
    """Validates that CandleStore.is_fresh rejects future-skewed timestamps and stale timestamps."""
    from btc_scraper.core.candle_store import CandleStore

    store = CandleStore()
    now_ref = 1700000000.0

    # 1. Past fresh candle: 300s old (<= 1800s) -> Valid
    past_fresh_ts = now_ref - 300
    dt_fresh = datetime.fromtimestamp(past_fresh_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    store.seed("BTC", "15m", [{
        "time": dt_fresh,
        "time_utc": dt_fresh + ":00Z",
        "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50050.0, "volume": 10.0,
    }], now=now_ref)
    assert store.is_fresh("BTC", "15m", max_age_seconds=1800.0, max_future_skew_seconds=60.0, now=now_ref)

    # 2. Stale past candle: 3600s old (> 1800s) -> Invalid
    past_stale_ts = now_ref - 3600
    dt_stale = datetime.fromtimestamp(past_stale_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    store.seed("BTC", "15m", [{
        "time": dt_stale,
        "time_utc": dt_stale + ":00Z",
        "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50050.0, "volume": 10.0,
    }], now=now_ref)
    assert not store.is_fresh("BTC", "15m", max_age_seconds=1800.0, max_future_skew_seconds=60.0, now=now_ref)

    # 3. Small acceptable future skew (e.g. 10s <= 60s) -> Valid
    small_skew_ts = now_ref + 10
    dt_skew = datetime.fromtimestamp(small_skew_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    store.seed("BTC", "15m", [{
        "time": dt_skew,
        "time_utc": dt_skew + ":00Z",
        "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50050.0, "volume": 10.0,
    }], now=now_ref)
    assert store.is_fresh("BTC", "15m", max_age_seconds=1800.0, max_future_skew_seconds=60.0, now=now_ref)

    # 4. Large unphysical future skew (e.g. 3600s in the future) -> Must be rejected!
    large_skew_ts = now_ref + 3600
    dt_large_skew = datetime.fromtimestamp(large_skew_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    store.seed("BTC", "15m", [{
        "time": dt_large_skew,
        "time_utc": dt_large_skew + ":00Z",
        "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50050.0, "volume": 10.0,
    }], now=now_ref)
    assert not store.is_fresh("BTC", "15m", max_age_seconds=1800.0, max_future_skew_seconds=60.0, now=now_ref)


# ─── Test 21: Interval-Aware Freshness TTL Mapping ────────────────────────────

def test_interval_aware_freshness_ttl_mapping():
    """Validates that _get_candles_for_coin uses interval-aware TTL (15m=1800, 1h=7200, 4h=28800, 1d=172800)."""
    import main as main_module
    from btc_scraper.core.candle_store import CandleStore

    store = CandleStore()
    now_ts = time.time()

    # 1h candle updated 3600 seconds ago (1h old)
    # Under fixed 1800s TTL this would fail, but under 1h TTL (7200s) this is completely fresh.
    dt_1h = datetime.fromtimestamp(now_ts - 3600, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    store.seed("BTC", "1h", [{
        "time": dt_1h,
        "time_utc": dt_1h + ":00Z",
        "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50050.0, "volume": 10.0,
        "closed": True, "is_closed": True,
    }])

    assert main_module.INTERVAL_FRESHNESS_TTL["15m"] == 1800.0
    assert main_module.INTERVAL_FRESHNESS_TTL["1h"] == 7200.0
    assert main_module.INTERVAL_FRESHNESS_TTL["4h"] == 28800.0
    assert main_module.INTERVAL_FRESHNESS_TTL["1d"] == 172800.0

    async def _check():
        from unittest.mock import MagicMock, AsyncMock
        mock_ws = MagicMock()
        mock_ws.is_healthy.return_value = True
        mock_rest = AsyncMock()

        with patch.object(main_module, "_ws_manager", mock_ws), \
             patch.object(main_module, "candle_store", store), \
             patch("btc_scraper.exchanges.binance.fetch_ohlcv_tf", mock_rest):
            res = await main_module._get_candles_for_coin("BTC", "1h")
            assert len(res) == 1
            assert mock_rest.await_count == 0  # Did NOT trigger false REST fallback!

    import asyncio
    asyncio.run(_check())


# ─── Test 22: Macro Freshness Payload Timestamp & Future Skew ─────────────────

def test_macro_freshness_payload_timestamp_and_future_skew():
    """Validates that is_macro_state_fresh parses JSON payload timestamp first, rejecting stale and future-skewed timestamps."""
    from btc_scraper.collectors.macro_collector import is_macro_state_fresh

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        macro_file = tmp_path / "macro_state.json"
        now_ref = 1700000000.0

        # Case 1: Fresh timestamp in payload
        fresh_ts = datetime.fromtimestamp(now_ref - 600, tz=timezone.utc).isoformat()
        macro_file.write_text(json.dumps({"DXY": 100.0, "timestamp": fresh_ts}), encoding="utf-8")
        os.utime(macro_file, (now_ref - 600, now_ref - 600))
        assert is_macro_state_fresh(macro_file, max_age_seconds=3600, now=now_ref)

        # Case 2: Stale timestamp in payload (2 hours old) even though file was touched just now
        stale_ts = datetime.fromtimestamp(now_ref - 7200, tz=timezone.utc).isoformat()
        macro_file.write_text(json.dumps({"DXY": 100.0, "timestamp": stale_ts}), encoding="utf-8")
        os.utime(macro_file, (now_ref, now_ref))
        assert not is_macro_state_fresh(macro_file, max_age_seconds=3600, now=now_ref)

        # Case 3: Future-skewed timestamp in payload (1 hour in the future) -> Must be rejected!
        future_ts = datetime.fromtimestamp(now_ref + 3600, tz=timezone.utc).isoformat()
        macro_file.write_text(json.dumps({"DXY": 100.0, "timestamp": future_ts}), encoding="utf-8")
        os.utime(macro_file, (now_ref, now_ref))
        assert not is_macro_state_fresh(macro_file, max_age_seconds=3600, max_future_skew_seconds=60.0, now=now_ref)

        # Case 4: No timestamp in payload -> falls back to file mtime
        macro_file.write_text(json.dumps({"DXY": 100.0}), encoding="utf-8")
        # Set file mtime to fresh
        os.utime(macro_file, (now_ref - 300, now_ref - 300))
        assert is_macro_state_fresh(macro_file, max_age_seconds=3600, now=now_ref)


# ─── Test 23: Stale Macro & Sentiment Neutralization in Decisions ─────────────

def test_stale_macro_and_sentiment_neutralization_in_decisions():
    """Validates that stale macro and sentiment inputs degrade to baseline (DXY=100, VIX=20, FG=50) and attach quality status."""
    from btc_scraper.ml_engine.causal_context_bridge import (
        build_world_state_from_ana,
        enhance_signal_with_causal_context,
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        macro_file = data_dir / "macro_state.json"

        # Stale macro state written to disk
        macro_file.write_text(json.dumps({
            "DXY": 105.5,
            "VIX": 35.0,
            "BondYield": 5.2,
            "timestamp": "2020-01-01T00:00:00Z",  # heavily stale
            "stale": True,
        }), encoding="utf-8")

        with patch.dict(os.environ, {"BTC_RUNTIME_ROOT": str(tmp_path), "BTC_DATA_DIR": ""}):
            # Analysis with stale sentiment (e.g. Extreme Fear 10/100 marked stale)
            ana_stale = {
                "coin": "BTC",
                "symbol": "BTCUSDT",
                "signal": "BUY",
                "action": "BUY",
                "close": 50000.0,
                "funding": 0.0001,
                "oi_delta": 10.0,
                "fear_greed": 10.0,
                "sentiment_momentum": -0.9,
                "sentiment": {
                    "raw_value": 10,
                    "label": "Extreme Fear",
                    "stale": True,
                    "status": "stale",
                },
                "prediction_id": "pred-stale-neutralization-test",
                "meta_probability": 0.72,
                "meta_expected_return": 0.005,
                "allow_unbound_research": True,
                "caller_context": "TEST/LEGACY DISPLAY",
            }

            state = build_world_state_from_ana(ana_stale)
            assert state is not None

            # Macro should be neutralized to neutral baselines
            assert state.macro.DXY == 100.0
            assert state.macro.VIX == 20.0
            assert state.macro.BondYield == 4.5
            assert state.macro_quality_status == "STALE_NEUTRALIZED"

            # Sentiment should be neutralized to 50.0 (Neutral)
            assert state.sentiment.FearGreed == 50.0
            assert state.sentiment_quality_status == "STALE_NEUTRALIZED"

            # Decision output from causal bridge must surface quality status & neutral sentiment support
            dec = enhance_signal_with_causal_context(ana_stale, dict(ana_stale), alpha=0.0)
            assert dec.get("macro_quality_status") == "STALE_NEUTRALIZED"
            assert dec.get("sentiment_quality_status") == "STALE_NEUTRALIZED"
            assert dec.get("sentiment_support") == 0.5
            assert "macro_quality=STALE_NEUTRALIZED" in str(dec.get("reason", ""))
            assert "sentiment_quality=STALE_NEUTRALIZED" in str(dec.get("reason", ""))




# ─── Test 24: Simulated Clock Hook for Offline Replay Freshness ───────────────

def test_get_candles_simulated_clock_hook():
    """With main._candle_clock set, freshness is evaluated against the simulated clock (no false REST fallback),
    and a future-skewed candle relative to that clock is still rejected."""
    import asyncio
    from unittest.mock import MagicMock, AsyncMock
    import main as main_module
    from btc_scraper.core.candle_store import CandleStore

    sim_now = 1700000000.0
    store = CandleStore()
    dt_bar = datetime.fromtimestamp(sim_now, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    store.seed("BTC", "15m", [{
        "time": dt_bar, "time_utc": dt_bar + ":00Z",
        "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0,
    }], now=sim_now)

    async def _run():
        ws = MagicMock()
        ws.is_healthy.return_value = True
        rest = AsyncMock(return_value=[{"source": "REST_FALLBACK"}])
        with patch.object(main_module, "_ws_manager", ws), \
             patch.object(main_module, "candle_store", store), \
             patch("btc_scraper.exchanges.binance.fetch_ohlcv", rest):
            # Simulated clock matches bar -> served from store
            with patch.object(main_module, "_candle_clock", lambda: sim_now):
                res = await main_module._get_candles_for_coin("BTC", "15m")
                assert res[0].get("source") != "REST_FALLBACK"
                assert rest.await_count == 0
            # Simulated clock 1h behind bar -> bar is future-skewed -> rejected -> REST fallback
            with patch.object(main_module, "_candle_clock", lambda: sim_now - 3600):
                res2 = await main_module._get_candles_for_coin("BTC", "15m")
                assert res2 == [{"source": "REST_FALLBACK"}]

    asyncio.run(_run())


# ─── Test 25 (P0 #1): Replay Sequence Exact Progression (Zero Skip / Zero Repeat) ─

def test_replay_progression_plan_sequential_bar_ids_no_off_by_one():
    """Proves seed consumes indices 0..209 and 20 replay steps consume 210..229 (210 + (i - 1)),
    with zero skipped bars, zero repeated bars, and identical progression contract across symbols."""
    from scripts.paper_benchmark_support import (
        build_replay_progression_plan,
        merge_and_audit_replay_15m_rows,
    )

    base_open_ts = 1782604800  # 2026-06-28 00:00:00 UTC (divisible by 86400 & 900)
    symbols = ("BTC", "ETH", "SOL")
    plans = {}
    for sym in symbols:
        raw_rows = []
        for bar_id in range(230):
            ts = base_open_ts + bar_id * 900
            dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            price = 1000.0 + bar_id
            raw_rows.append({
                "bar_id": bar_id,
                "time": dt_str,
                "open": price,
                "high": price + 2.0,
                "low": price - 2.0,
                "close": price + 1.0,
                "volume": 50.0 + bar_id,
            })
        audited_bars, _ = merge_and_audit_replay_15m_rows(raw_rows, symbol=sym)
        plans[sym] = build_replay_progression_plan(audited_bars, seed_count=210, replay_cycles=20)

    ref_replay_ts = [b["open_ts"] for b in plans["BTC"]["replay_step_bars"]]
    for sym, plan in plans.items():
        seed_ids = [b["bar_id"] for b in plan["seed_bars"]]
        replay_ids = [b["bar_id"] for b in plan["replay_step_bars"]]
        assert seed_ids == list(range(0, 210)), f"{sym} seed bar IDs mismatch"
        assert replay_ids == list(range(210, 230)), f"{sym} replay bar IDs skipped or repeated: {replay_ids}"
        assert len(replay_ids) == 20
        assert len(set(replay_ids)) == 20
        assert seed_ids[-1] + 1 == replay_ids[0], "First replay bar must immediately follow last seed bar (index 210)"
        assert [b["open_ts"] for b in plan["replay_step_bars"]] == ref_replay_ts

    # Insufficient bars must fail closed instead of clamping/repeating last bar
    with pytest.raises(ValueError, match="Insufficient audited 15m bars"):
        build_replay_progression_plan(plans["BTC"]["seed_bars"][:200], seed_count=210, replay_cycles=20)


# ─── Test 26 (P0 #2): Multi-CSV Global Sort, Dedup, Conflict & Spacing Audit ──

def test_multi_csv_global_sort_dedup_conflict_and_gap_audit(tmp_path):
    """Validates global UTC sorting, overlap deduplication, duplicate OHLCV conflict rejection,
    15m spacing audit (with explicit allowlist support), and missing-file fail-closed behavior."""
    from scripts.paper_benchmark_support import load_and_audit_replay_15m_csvs

    base_ts = 1782604800  # 2026-06-28 00:00:00 UTC
    csv_may = tmp_path / "BTC_15m_part1.csv"
    csv_jun = tmp_path / "BTC_15m_part2.csv"

    def _write_csv(path: Path, rows: list[dict]) -> None:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write("time,open,high,low,close,volume\n")
            for r in rows:
                fh.write(f"{r['time']},{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']}\n")

    # Part 1: bars 0..5 intentionally out of order; Part 2: overlap bars 3..5 + new bars 6..9
    rows_1 = []
    for idx in [2, 0, 4, 1, 5, 3]:
        dt_str = datetime.fromtimestamp(base_ts + idx * 900, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        rows_1.append({"time": dt_str, "open": 100 + idx, "high": 105 + idx, "low": 95 + idx, "close": 102 + idx, "volume": 10 + idx})
    rows_2 = []
    for idx in [3, 4, 5, 6, 7, 8, 9]:
        dt_str = datetime.fromtimestamp(base_ts + idx * 900, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        rows_2.append({"time": dt_str, "open": 100 + idx, "high": 105 + idx, "low": 95 + idx, "close": 102 + idx, "volume": 10 + idx})

    _write_csv(csv_may, rows_1)
    _write_csv(csv_jun, rows_2)

    bars, stats = load_and_audit_replay_15m_csvs([csv_jun, csv_may], symbol="BTC")
    assert stats["raw_rows"] == 13
    assert stats["duplicate_rows"] == 3
    assert stats["unique_rows"] == 10
    assert [b["open_ts"] for b in bars] == [base_ts + i * 900 for i in range(10)]

    # Conflicting duplicate OHLCV (valid OHLC envelope, different close) must fail closed
    conflict_rows = list(rows_2)
    conflict_rows[0] = {**conflict_rows[0], "close": 104.0}
    _write_csv(csv_jun, conflict_rows)
    with pytest.raises(ValueError, match="Conflicting OHLCV on duplicate timestamp"):
        load_and_audit_replay_15m_csvs([csv_may, csv_jun], symbol="BTC")

    # Unallowlisted gap (skipping bar 6) must fail closed, unless explicitly allowlisted
    gap_rows = [r for idx, r in enumerate(rows_2) if idx != 3]  # removes bar 6 (index 3 in rows_2)
    _write_csv(csv_jun, gap_rows)
    with pytest.raises(ValueError, match="Unallowlisted 15m spacing gap"):
        load_and_audit_replay_15m_csvs([csv_may, csv_jun], symbol="BTC")

    bars_allowed, gap_stats = load_and_audit_replay_15m_csvs(
        [csv_may, csv_jun],
        symbol="BTC",
        allowlisted_gaps={(base_ts + 5 * 900, base_ts + 7 * 900)},
    )
    assert len(bars_allowed) == 9
    assert gap_stats["audited_gap_count"] == 1

    # Missing file fails closed (no silent synthetic fallback)
    with pytest.raises(FileNotFoundError):
        load_and_audit_replay_15m_csvs([tmp_path / "NON_EXISTENT.csv"], symbol="BTC")


# ─── Test 27 (P0 #3): Deterministic UTC-Bucket HTF Rollover (1h / 4h / 1d) ────

def test_utc_bucket_htf_aggregation_exact_boundaries_and_no_lookahead():
    """Tests 4x15m -> 1h (:00 UTC), 16x15m -> 4h (00/04/08/12/16/20:00 UTC), 96x15m -> 1d (00:00 UTC):
    - O=first, H=max, L=min, C=last, V=sum;
    - exact bucket open_time_utc & close_time_utc;
    - zero lookahead (future bars in map are ignored);
    - no early/late rollover on non-boundary or incomplete buckets;
    - non-midnight 20-bar window produces 0 daily rollovers regardless of synthetic seed age."""
    from scripts.paper_benchmark_support import aggregate_closed_utc_htf_candle

    day_start = 1782777600  # 2026-06-30 00:00:00 UTC (exact UTC midnight: day_start % 86400 == 0)
    assert day_start % 86400 == 0

    bars_by_ts = {}
    for i in range(96):
        ts = day_start + i * 900
        bars_by_ts[ts] = {
            "open_ts": ts,
            "close_ts": ts + 900,
            "open": 1000.0 + i * 10.0,
            "high": 1005.0 + (5000.0 if i == 37 else i * 10.0),
            "low": (250.0 if i == 11 else 995.0 + i * 10.0),
            "close": 1002.0 + i * 10.0,
            "volume": float(i + 1),
        }
    # Inject an extreme future bar after midnight to prove zero lookahead
    bars_by_ts[day_start + 96 * 900] = {
        "open_ts": day_start + 96 * 900,
        "close_ts": day_start + 97 * 900,
        "open": 999999.0,
        "high": 999999.0,
        "low": 0.01,
        "close": 999999.0,
        "volume": 999999.0,
    }

    # 1) Non-boundary 15m close (:15, :30, :45) -> None for all HTFs
    for i in (0, 1, 2):
        assert aggregate_closed_utc_htf_candle(bars_by_ts, interval="1h", closed_15m_open_ts=day_start + i * 900) is None
        assert aggregate_closed_utc_htf_candle(bars_by_ts, interval="4h", closed_15m_open_ts=day_start + i * 900) is None
        assert aggregate_closed_utc_htf_candle(bars_by_ts, interval="1d", closed_15m_open_ts=day_start + i * 900) is None

    # 2) 4 x 15m (00:00..00:45, closing at 01:00 UTC) -> 1h candle only (not 4h, not 1d)
    c_1h = aggregate_closed_utc_htf_candle(bars_by_ts, interval="1h", closed_15m_open_ts=day_start + 3 * 900)
    assert c_1h is not None
    assert c_1h["open_time_utc"] == "2026-06-30T00:00:00Z"
    assert c_1h["close_time_utc"] == "2026-06-30T01:00:00Z"
    assert c_1h["open"] == 1000.0
    assert c_1h["high"] == 1035.0
    assert c_1h["low"] == 995.0
    assert c_1h["close"] == 1032.0
    assert c_1h["volume"] == float(1 + 2 + 3 + 4)
    assert aggregate_closed_utc_htf_candle(bars_by_ts, interval="4h", closed_15m_open_ts=day_start + 3 * 900) is None
    assert aggregate_closed_utc_htf_candle(bars_by_ts, interval="1d", closed_15m_open_ts=day_start + 3 * 900) is None

    # 3) 16 x 15m (00:00..03:45, closing at 04:00 UTC) -> 4h candle (and 1h, not 1d)
    c_4h = aggregate_closed_utc_htf_candle(bars_by_ts, interval="4h", closed_15m_open_ts=day_start + 15 * 900)
    assert c_4h is not None
    assert c_4h["open_time_utc"] == "2026-06-30T00:00:00Z"
    assert c_4h["close_time_utc"] == "2026-06-30T04:00:00Z"
    assert c_4h["open"] == 1000.0
    assert c_4h["high"] == 1155.0
    assert c_4h["low"] == 250.0  # bar i=11 minimum
    assert c_4h["close"] == 1152.0
    assert c_4h["volume"] == float(sum(range(1, 17)))
    assert aggregate_closed_utc_htf_candle(bars_by_ts, interval="1d", closed_15m_open_ts=day_start + 15 * 900) is None

    # 4) 96 x 15m (00:00..23:45, closing at 2026-07-01 00:00:00Z) -> 1d candle, untouched by future bar 96!
    c_1d = aggregate_closed_utc_htf_candle(bars_by_ts, interval="1d", closed_15m_open_ts=day_start + 95 * 900)
    assert c_1d is not None
    assert c_1d["open_time_utc"] == "2026-06-30T00:00:00Z"
    assert c_1d["close_time_utc"] == "2026-07-01T00:00:00Z"
    assert c_1d["open"] == 1000.0
    assert c_1d["high"] == 6005.0  # bar i=37 max (future bar 999999.0 NOT leaked!)
    assert c_1d["low"] == 250.0    # bar i=11 min (future bar 0.01 NOT leaked!)
    assert c_1d["close"] == 1002.0 + 95 * 10.0
    assert c_1d["volume"] == float(sum(range(1, 97)))

    # 5) Incomplete bucket (missing 1 constituent bar) -> returns None (no partial HTF candle)
    incomplete = dict(bars_by_ts)
    incomplete.pop(day_start + 40 * 900)
    assert aggregate_closed_utc_htf_candle(incomplete, interval="1d", closed_15m_open_ts=day_start + 95 * 900) is None

    # 6) 20-cycle non-midnight window (10:00..14:45 UTC) -> zero 1d rollovers
    daily_rollovers = sum(
        1
        for step_i in range(40, 60)
        if aggregate_closed_utc_htf_candle(bars_by_ts, interval="1d", closed_15m_open_ts=day_start + step_i * 900) is not None
    )
    assert daily_rollovers == 0


# ─── Test 28 (P1 #12a): Differential Stale Neutralization in Analysis, Pure Scoring & Features ─

def test_differential_stale_effectiveness_analysis_scoring_and_features():
    """Proves across analyze_market, score_signal_pure, build_meta_features, build_meta_features_v2,
    and records_to_dataset that extreme stale sentiment produces identical outputs to fresh neutral
    baseline while preserving raw extreme values strictly in raw_observability."""
    from scripts.paper_benchmark_support import make_synthetic_candles
    from btc_scraper.analysis.core import analyze_market
    from btc_scraper.ml_engine.feature_extractor import (
        build_meta_features,
        build_meta_features_v2,
        records_to_dataset,
    )
    from btc_scraper.ml_engine.pure_scoring import score_signal_pure

    candles = make_synthetic_candles(50000.0, n=220, interval="15m", end_time=1782846000.0)

    neutral_sent = {
        "score": 0.0,
        "normalized_score": 0.0,
        "label": "Neutral",
        "raw_value": 50,
        "observed_at": "2026-06-30T00:00:00Z",
        "observation_date": "2026-06-30",
        "status": "success",
        "stale": False,
        "trend": [],
    }
    stale_extreme_sent = {
        "score": -0.92,
        "normalized_score": -0.92,
        "label": "Extreme Fear",
        "raw_value": 4,
        "observed_at": "2025-01-01T00:00:00Z",
        "observation_date": "2025-01-01",
        "status": "stale",
        "stale": True,
        "trend": [],
    }
    neutral_trend = {
        "trend": "STABLE",
        "daily_momentum": 0.0,
        "momentum": 0.0,
        "recovery_signal": False,
        "risk_signal": False,
        "hours_in_extreme": 0,
        "consecutive_extreme_days": 0,
    }

    with patch("btc_scraper.analysis.core.get_market_sentiment", return_value=neutral_sent), \
         patch("btc_scraper.analysis.core.get_sentiment_trend", return_value=neutral_trend), \
         patch("btc_scraper.analysis.core._save_sentiment_to_history"):
        ana_neutral = analyze_market([dict(c) for c in candles], "BTC")

    with patch("btc_scraper.analysis.core.get_market_sentiment", return_value=stale_extreme_sent), \
         patch("btc_scraper.analysis.core._save_sentiment_to_history") as save_hist_mock:
        ana_stale = analyze_market([dict(c) for c in candles], "BTC")
        assert save_hist_mock.call_count == 0, "Stale sentiment must not be re-saved as fresh history"

    assert ana_stale["signal"] == ana_neutral["signal"]
    assert ana_stale["sentiment"]["score"] == 0.0
    assert ana_stale["sentiment"]["raw_value"] == 50
    assert ana_stale["sentiment_quality_status"] == "STALE_NEUTRALIZED"
    assert ana_stale["sentiment"]["raw_observability"]["raw_value"] == 4
    assert ana_stale["sentiment"]["raw_observability"]["normalized_score"] == -0.92

    # Differential check on pure_scoring: fresh extreme triggers ADVERSE_SENTIMENT (-20), stale extreme equals neutral
    buy_data_neutral = {"signal": "BUY", "sentiment": {"score": 0.0, "stale": False}}
    buy_data_fresh_extreme = {"signal": "BUY", "sentiment": {"score": -0.90, "stale": False}}
    buy_data_stale_extreme = {"signal": "BUY", "sentiment": {"score": -0.90, "stale": True, "status": "stale"}}
    s_neu = score_signal_pure(buy_data_neutral, {})
    s_fresh_ext = score_signal_pure(buy_data_fresh_extreme, {})
    s_stale_ext = score_signal_pure(buy_data_stale_extreme, {})
    assert s_fresh_ext.final_score < s_neu.final_score
    assert s_stale_ext.final_score == s_neu.final_score

    # Differential check on feature_extractor & records_to_dataset (no side-channel leakage)
    rec_neu = {**ana_neutral, "fear_greed": 50.0, "sentiment_momentum": 0.0, "result": "WIN"}
    rec_stale = {
        **ana_stale,
        "fear_greed": 4.0,
        "sentiment_raw": 4.0,
        "sentiment_score": -0.92,
        "sentiment_momentum": -0.95,
        "sentiment_risk": 1.0,
        "sentiment_trend_down": 1.0,
        "result": "WIN",
    }
    rec_fresh_ext = {
        **ana_neutral,
        "sentiment_quality_status": "FRESH",
        "sentiment": {"score": -0.92, "raw_value": 4, "stale": False, "status": "success"},
        "fear_greed": 4.0,
        "sentiment_raw": 4.0,
        "sentiment_score": -0.92,
        "sentiment_momentum": -0.95,
        "sentiment_risk": 1.0,
        "sentiment_trend_down": 1.0,
        "result": "WIN",
    }
    assert build_meta_features(rec_stale) == build_meta_features(rec_neu)
    assert build_meta_features_v2(rec_stale) == build_meta_features_v2(rec_neu)
    assert build_meta_features_v2(rec_fresh_ext)["fear_greed"] == 4.0
    X_neu, _, _ = records_to_dataset([rec_neu])
    X_stale, _, _ = records_to_dataset([rec_stale])
    assert X_stale == X_neu


# ─── Test 29 (P1 #12b): Differential Stale Effectiveness Across All Public Decision Paths ─

def test_differential_stale_effectiveness_all_public_decision_paths(tmp_path):
    """Differential test across every public decision path:
    1) MetaDecisionEngine.decide (precomputed _meta_prediction AND live predict_meta_confidence)
    2) MetaDecisionEngine.apply_context
    3) MetaDecisionEngine.decide_with_context
    4) MetaDecisionEngine.decide_with_provider (HybridContextProvider alpha=0.3)
    5) enhance_signal_with_causal_context (persisted to RuntimeEvidenceStore)
    6) main._run_causal_runtime_pass
    Asserts:
    - Fresh extreme macro/sentiment shifts probability/consensus away from neutral baseline;
    - Stale extreme macro/sentiment produces exact neutral baseline probability;
    - Raw extreme values exist strictly inside observability_only;
    - macro_quality_status and sentiment_quality_status appear in both returned and persisted decisions."""
    import asyncio
    import main as main_module
    from btc_scraper.core.world_state import MarketRegime, WorldState
    from btc_scraper.ml_engine import causal_context_bridge as ccb
    from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine
    from btc_scraper.ml_engine.hybrid_context_provider import HybridContextProvider
    from btc_scraper.ml_engine.inference_contract import InferenceArtifact, feature_schema_hash
    from btc_scraper.ml_engine import runtime_evidence_store as res_mod
    from btc_scraper.ml_engine.runtime_evidence_store import get_runtime_evidence_store

    env_overrides = {
        "BTC_RUNTIME_ROOT": str(tmp_path),
        "BTC_DATA_DIR": "",
        "BTC_RUNTIME_ENVIRONMENT": "paper",
        "AUTO_TRADE_DRY_RUN": "true",
        "LIVE_TRADING_ENABLED": "false",
        "BTC_EVIDENCE_ELIGIBLE": "false",
        "PAPER_ECONOMIC_POLICY": "NO_TRADE_SHADOW",
    }

    with patch.dict(os.environ, env_overrides), patch.object(res_mod, "_STORE", None):
        store = get_runtime_evidence_store()
        engine = MetaDecisionEngine()
        provider = HybridContextProvider.build(
            alpha=0.3,
            graph_path=str(REPO_ROOT / "data" / "causal_graph.json"),
            rules_path=str(REPO_ROOT / "data" / "context_rules.json"),
        )

        def _seed_pred(pred_id: str, prob: float = 0.72) -> dict:
            meta_payload = {
                "prediction_id": pred_id,
                "signal_id": f"sig-{pred_id}",
                "symbol": "BTC",
                "probability": prob,
                "model_probability_up": prob,
                "probability_semantics": "P(up)",
                "execution_probability": prob,
                "execution_probability_semantics": "P(win_given_proposed_trade)",
                "expected_return": 0.0040,
                "s3_pass": True,
                "s3_threshold": 0.55,
                "binding_verified": True,
                "inference_contract_version": "inference-v1",
                "model_family": "meta_model",
                "artifact_version": "test-v1",
                "artifact_hash": "abc123",
                "artifact_sha256": "abc123",
                "model_version": "test-v1",
                "feature_schema_version": "v2",
                "feature_schema_hash": "fhash",
                "prediction": prob,
                "evidence_eligible": False,
            }
            store.write_prediction_evidence(
                {**meta_payload, "calibrated_probability": prob},
                {"prediction_id": pred_id, "features": {"fear_greed": 50.0}},
            )
            return meta_payload

        def _base_payload(pred_id: str, *, stale: bool, extreme: bool) -> dict:
            fg = (5.0 if extreme else 50.0)
            mom = (-0.95 if extreme else 0.0)
            dxy = (112.0 if extreme else 100.0)
            vix = (48.0 if extreme else 20.0)
            ry = (3.2 if extreme else 0.0)
            by = (6.0 if extreme else 4.5)
            return {
                "coin": "BTC",
                "symbol": "BTCUSDT",
                "signal": "BUY",
                "action": "BUY",
                "close": 50000.0,
                "atr_pct": 1.0,
                "atr_percentile": 35.0,
                "funding": 0.0001,
                "oi_delta": 0.0,
                "fear_greed": fg,
                "sentiment_momentum": mom,
                "sentiment": {
                    "raw_value": int(fg),
                    "score": (fg - 50.0) / 50.0,
                    "stale": stale,
                    "status": "stale" if stale else "success",
                },
                "macro": {
                    "DXY": dxy,
                    "VIX": vix,
                    "RealYield": ry,
                    "BondYield": by,
                    "stale": stale,
                    "status": "stale" if stale else "ok",
                },
                "allow_unbound_research": True,
                "caller_context": "TEST/LEGACY DISPLAY",
                "_meta_prediction": _seed_pred(pred_id),
            }

        # Path 1A: MetaDecisionEngine.decide()
        d_neu = engine.decide(_base_payload("p1-neu", stale=False, extreme=False), persist_final=True)
        d_fresh_ext = engine.decide(_base_payload("p1-fresh", stale=False, extreme=True), persist_final=True)
        d_stale_ext = engine.decide(_base_payload("p1-stale", stale=True, extreme=True), persist_final=True)

        assert d_fresh_ext["posterior_probability"] != pytest.approx(d_neu["posterior_probability"])
        assert d_stale_ext["posterior_probability"] == pytest.approx(d_neu["posterior_probability"])
        assert d_stale_ext["side_probability"] == pytest.approx(d_neu["side_probability"])
        assert d_stale_ext["sentiment_support"] == pytest.approx(0.5)
        assert d_stale_ext["macro_quality_status"] == "STALE_NEUTRALIZED"
        assert d_stale_ext["sentiment_quality_status"] == "STALE_NEUTRALIZED"
        assert d_stale_ext["observability_only"]["raw_sentiment"]["fear_greed"] == 5.0
        assert d_stale_ext["observability_only"]["raw_macro"]["DXY"] == 112.0
        persisted_d1 = store.get_final_decision_for_prediction("p1-stale")
        assert persisted_d1 is not None
        assert persisted_d1["macro_quality_status"] == "STALE_NEUTRALIZED"
        assert persisted_d1["sentiment_quality_status"] == "STALE_NEUTRALIZED"
        assert persisted_d1["observability_only"]["raw_macro"]["VIX"] == 48.0

        # Path 1B: MetaDecisionEngine.decide() via live predict_meta_confidence feature vector
        seen_fg_vectors = []
        schema = ("fear_greed", "sentiment_momentum")

        def _fg_sensitive_predictor(_sym: str, vec: tuple[float, ...]) -> float:
            seen_fg_vectors.append(vec)
            # Maps fg=50, mom=0 -> 0.70; fg=5, mom=-0.95 -> ~0.35
            return max(0.05, min(0.95, 0.70 + 0.005 * (vec[0] - 50.0) + 0.10 * vec[1]))

        fg_art = InferenceArtifact(
            model_family="meta_model",
            artifact_version="fg-test-v1",
            artifact_hash="a" * 64,
            feature_schema_hash=feature_schema_hash(schema),
            feature_names=schema,
            predictor=_fg_sensitive_predictor,
            feature_schema_version="fg-test-2f",
            artifact_metadata_consistent=True,
            calibration_method="logistic",
            supported_symbols=frozenset({"BTC"}),
        )
        with patch("btc_scraper.ml_engine.meta_model.get_meta_inference_artifact", return_value=fg_art):
            live_neu_in = {k: v for k, v in _base_payload("unused-a", stale=False, extreme=False).items() if k != "_meta_prediction"}
            live_neu_in["signal_id"] = "sig-live-neu"
            live_stale_in = {k: v for k, v in _base_payload("unused-b", stale=True, extreme=True).items() if k != "_meta_prediction"}
            live_stale_in["signal_id"] = "sig-live-stale"
            d_live_neu = engine.decide(live_neu_in, persist_final=False)
            d_live_stale = engine.decide(live_stale_in, persist_final=False)
        assert seen_fg_vectors == [(50.0, 0.0), (50.0, 0.0)], f"Raw stale feature leaked into model: {seen_fg_vectors}"
        assert d_live_stale["posterior_probability"] == pytest.approx(d_live_neu["posterior_probability"])

        # Path 2 & 3: MetaDecisionEngine.apply_context() and decide_with_context()
        ctx_report = {"adjusted_score": 0.68, "adjustments": [], "risk_level": "LOW", "stop_processing": False}
        ac_neu = engine.decide_with_context(_base_payload("p2-neu", stale=False, extreme=False), ctx_report, persist_final=True)
        ac_stale = engine.decide_with_context(_base_payload("p2-stale", stale=True, extreme=True), ctx_report, persist_final=True)
        assert ac_stale["adjusted_posterior"] == pytest.approx(ac_neu["adjusted_posterior"])
        assert ac_stale["posterior_probability"] == pytest.approx(ac_neu["posterior_probability"])
        assert ac_stale["macro_quality_status"] == "STALE_NEUTRALIZED"
        assert ac_stale["sentiment_quality_status"] == "STALE_NEUTRALIZED"
        persisted_p2 = store.get_final_decision_for_prediction("p2-stale")
        assert persisted_p2["macro_quality_status"] == "STALE_NEUTRALIZED"
        assert persisted_p2["sentiment_quality_status"] == "STALE_NEUTRALIZED"

        base_raw_stale = engine.decide(_base_payload("p2b-stale", stale=True, extreme=True), persist_final=False)
        ac_direct = engine.apply_context(
            base_raw_stale,
            ctx_report,
            analysis_info=_base_payload("p2b-stale-info", stale=True, extreme=True),
            persist_final=True,
        )
        assert ac_direct["macro_quality_status"] == "STALE_NEUTRALIZED"
        assert ac_direct["sentiment_quality_status"] == "STALE_NEUTRALIZED"
        assert store.get_final_decision_for_prediction("p2b-stale")["macro_quality_status"] == "STALE_NEUTRALIZED"

        # Path 4: MetaDecisionEngine.decide_with_provider() with direct polluted WorldState
        def _make_ws(*, extreme: bool, stale: bool) -> WorldState:
            ws = WorldState(timestamp=datetime.now(timezone.utc), regime=MarketRegime.RISK_ON)
            ws.macro.DXY = 112.0 if extreme else 100.0
            ws.macro.VIX = 48.0 if extreme else 20.0
            ws.macro.RealYield = 3.2 if extreme else 0.0
            ws.macro.BondYield = 6.0 if extreme else 4.5
            ws.sentiment.FearGreed = 5.0 if extreme else 50.0
            ws.macro_quality_status = "STALE_NEUTRALIZED" if stale else "FRESH"
            ws.sentiment_quality_status = "STALE_NEUTRALIZED" if stale else "FRESH"
            return ws

        dp_neu = engine.decide_with_provider(_base_payload("p4-neu", stale=False, extreme=False), provider, _make_ws(extreme=False, stale=False))
        dp_fresh_ext = engine.decide_with_provider(_base_payload("p4-fresh", stale=False, extreme=True), provider, _make_ws(extreme=True, stale=False))
        dp_stale_ext = engine.decide_with_provider(_base_payload("p4-stale", stale=True, extreme=True), provider, _make_ws(extreme=True, stale=True))

        assert dp_fresh_ext["adjusted_posterior"] != pytest.approx(dp_neu["adjusted_posterior"])
        assert dp_stale_ext["adjusted_posterior"] == pytest.approx(dp_neu["adjusted_posterior"])
        assert dp_stale_ext["posterior_probability"] == pytest.approx(dp_neu["posterior_probability"])
        assert dp_stale_ext["macro_quality_status"] == "STALE_NEUTRALIZED"
        assert dp_stale_ext["sentiment_quality_status"] == "STALE_NEUTRALIZED"
        assert dp_stale_ext["observability_only"]["raw_macro"]["DXY"] == 112.0
        persisted_p4 = store.get_final_decision_for_prediction("p4-stale")
        assert persisted_p4["adjusted_posterior"] == pytest.approx(dp_neu["adjusted_posterior"])
        assert persisted_p4["macro_quality_status"] == "STALE_NEUTRALIZED"
        assert persisted_p4["sentiment_quality_status"] == "STALE_NEUTRALIZED"

        # Path 5: enhance_signal_with_causal_context()
        ccb._HYBRID_PROVIDER = None
        ccb._DECISION_ENGINE = None
        pred5_neu = _seed_pred("p5-neu")
        pred5_stale = _seed_pred("p5-stale")
        ana5_neu = {
            **_base_payload("p5-neu-tmp", stale=False, extreme=False),
            "prediction_id": "p5-neu",
            "meta_probability": 0.72,
            "meta_expected_return": 0.0040,
        }
        ana5_neu.pop("_meta_prediction", None)
        ana5_stale = {
            **_base_payload("p5-stale-tmp", stale=True, extreme=True),
            "prediction_id": "p5-stale",
            "meta_probability": 0.72,
            "meta_expected_return": 0.0040,
        }
        ana5_stale.pop("_meta_prediction", None)
        _ = (pred5_neu, pred5_stale)

        e5_neu = ccb.enhance_signal_with_causal_context(ana5_neu, dict(ana5_neu), alpha=0.3)
        e5_stale = ccb.enhance_signal_with_causal_context(ana5_stale, dict(ana5_stale), alpha=0.3)
        assert e5_stale["adjusted_posterior"] == pytest.approx(e5_neu["adjusted_posterior"])
        assert e5_stale["macro_quality_status"] == "STALE_NEUTRALIZED"
        assert e5_stale["sentiment_quality_status"] == "STALE_NEUTRALIZED"
        assert e5_stale["observability_only"]["raw_macro"]["DXY"] == 112.0
        assert e5_stale["observability_only"]["raw_sentiment"]["FearGreed"] == 5.0
        persisted_p5 = store.get_final_decision_for_prediction("p5-stale")
        assert persisted_p5["macro_quality_status"] == "STALE_NEUTRALIZED"
        assert persisted_p5["sentiment_quality_status"] == "STALE_NEUTRALIZED"

        # Path 6: main._run_causal_runtime_pass()
        c_neu = asyncio.run(main_module._run_causal_runtime_pass({
            "signal": "BUY",
            "macro": {"DXY": 100.0, "VIX": 20.0, "RealYield": 0.0, "BondYield": 4.5, "stale": False},
            "macro_quality_status": "FRESH",
            "sentiment": {"FearGreed": 50.0, "stale": False},
            "sentiment_quality_status": "FRESH",
            "crypto": {"BTC_Price": 50000.0},
            "liquidity": {"BTC_Funding": 0.0, "OI_Delta": 0.0},
        }, {}))
        c_stale = asyncio.run(main_module._run_causal_runtime_pass({
            "signal": "BUY",
            "macro": {"DXY": 115.0, "VIX": 55.0, "RealYield": 3.5, "BondYield": 6.2, "stale": True},
            "raw_macro": {"DXY": 115.0, "VIX": 55.0, "RealYield": 3.5, "BondYield": 6.2},
            "macro_quality_status": "STALE_NEUTRALIZED",
            "sentiment": {"FearGreed": 3.0, "stale": True},
            "raw_sentiment": {"FearGreed": 3.0},
            "sentiment_quality_status": "STALE_NEUTRALIZED",
            "crypto": {"BTC_Price": 50000.0},
            "liquidity": {"BTC_Funding": 0.0, "OI_Delta": 0.0},
        }, {}))
        assert c_stale["consensus"] == c_neu["consensus"]
        assert c_stale["macro_quality_status"] == "STALE_NEUTRALIZED"
        assert c_stale["sentiment_quality_status"] == "STALE_NEUTRALIZED"
        assert c_stale["observability_only"]["raw_macro"]["DXY"] == 115.0
        assert c_stale["observability_only"]["raw_sentiment"]["FearGreed"] == 3.0

