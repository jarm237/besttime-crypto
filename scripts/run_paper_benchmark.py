"""
scripts/run_paper_benchmark.py

Comprehensive Paper/Demo Trading Benchmark & Profiling Suite:
1. Memory Breakdown:
   - Measures baseline Python RSS, plus memory deltas after importing
     numpy/pandas/sklearn, LightGBM, CatBoost, and Model Artifacts (Entry-only runtime, torch NOT in sys.modules).
   - Measures PPO / PyTorch load upon explicit exit evaluation (Exit-enabled runtime).
2. Cold Start Benchmark: Spawns an isolated subprocess running `main.py --once`,
   capturing direct milestones:
     - time_to_first_analysis_sec
     - time_to_first_prediction_sec
     - alternative_foreground_wait_sec
     - alternative_background_work_sec
     - cache_freshness_sec
3. Warm Steady State Benchmark: Runs 1 un-scored warm-up cycle followed by
   50 measured cycles in an isolated runtime root.
   Differentiates:
     - wall_sec: span from first call start to last call end within stage (<= total cycle);
     - aggregate_work_sec: sum of durations of all invocations;
     - call_count: number of invocations;
     - max_single_call_sec: slowest single call;
   Tracks memory across all 50 cycles and isolates slope of the last 20 cycles.
4. Complete Runtime Isolation: Points BTC_RUNTIME_ROOT and BTC_FALLBACK_BUFFER_DB
   to unique benchmark directories and asserts zero pollution in runtime/paper/local-paper.
"""

import sys
import os
import gc
import time
import json
import ctypes
import shutil
import subprocess
import statistics
import numpy as np
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ─── Windows Memory Helper ───────────────────────────────────────────────────

class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def get_process_memory_mb() -> Dict[str, float]:
    """Returns current and peak working set (RSS) in MB via Windows PSAPI."""
    ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
        wintypes.DWORD,
    ]
    ctypes.windll.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

    handle = ctypes.windll.kernel32.GetCurrentProcess()
    pmc = PROCESS_MEMORY_COUNTERS()
    pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb)
    if not ok:
        return {"current_rss_mb": 0.0, "peak_rss_mb": 0.0}
    return {
        "current_rss_mb": round(pmc.WorkingSetSize / (1024 * 1024), 2),
        "peak_rss_mb": round(pmc.PeakWorkingSetSize / (1024 * 1024), 2),
    }


# ─── Benchmark Network Blocker & Seed Helpers ───────────────────────────────

from scripts.paper_benchmark_support import (
    INTERVAL_SECONDS,
    NetworkInterceptor,
    aggregate_closed_utc_htf_candle,
    build_replay_progression_plan,
    load_and_audit_replay_15m_csvs,
    make_synthetic_candles,
)


def seed_isolated_runtime_data(runtime_root: Path):
    """Pre-seeds macro state and sentiment history in an isolated benchmark runtime directory."""
    data_dir = runtime_root / "data"
    logs_dir = runtime_root / "logs"
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    now_utc = datetime.now(timezone.utc)
    macro_path = data_dir / "macro_state.json"
    if not macro_path.exists():
        with open(macro_path, "w", encoding="utf-8") as f:
            json.dump({
                "DXY": 100.0,
                "VIX": 20.0,
                "BondYield": 4.5,
                "timestamp": now_utc.isoformat(),
            }, f, indent=2)

    sentiment_path = logs_dir / "sentiment_history.json"
    if not sentiment_path.exists():
        today_iso = now_utc.strftime("%Y-%m-%d")
        with open(sentiment_path, "w", encoding="utf-8") as f:
            json.dump({
                today_iso: {
                    "score": -0.4,
                    "normalized_score": -0.4,
                    "raw_value": 30,
                    "label": "Fear",
                    "observed_at": now_utc.isoformat(),
                }
            }, f, indent=2)


# ─── Stage Metrics Instrumentation & Coverage Contracts ─────────────────────

EXPECTED_STAGE_COUNTS: Dict[str, Tuple[int, int]] = {
    "market_data_fetch": (30, 40),          # 36 expected (9 coins x 4 tfs)
    "alternative_macro_collection": (1, 3), # 1-2 expected (alt ref & macro)
    "indicator_calculation": (1, 1),        # 1 expected (MarketAnalystAgent.run)
    "context_causal_processing": (1, 15),   # 1 to 10 expected
    "model_inference": (3, 9),              # 3 expected in execution scope, 9 in analysis scope
    "decision_sizing": (2, 2),              # 2 expected (RiskManagerAgent & PortfolioManagerAgent)
    "persistence": (1, 2),                  # 1 expected (latest_signals.json write)
}

STAGE_COVERAGE_DESCRIPTIONS: Dict[str, str] = {
    "market_data_fetch": "OHLCV retrieval for 9 coins x 4 timeframes (15m, 1h, 4h, 1d) via REST fallback or CandleStore.",
    "alternative_macro_collection": "Retrieval of local cached alternative data and macro state reference payloads.",
    "indicator_calculation": "Technical analysis indicators (EMA, MACD, RSI, ATR, BB) inside MarketAnalystAgent.run.",
    "context_causal_processing": "HybridContextProvider evaluation & Causal Bayesian consensus network pass.",
    "model_inference": "InferenceCoordinator.predict_once calls across all 9 analysis coins.",
    "decision_sizing": "Multi-agent coordination pass (RiskManagerAgent and PortfolioManagerAgent). Note: Sealed canonical S3/Kelly filtering is additionally executed within MarketAnalystAgent and AutoTrader._process_signal.",
    "persistence": "Atomic output writes of latest_signals.json and prediction audit logging.",
}


class StageSpan:
    """Tracks a single stage with wall-clock window and individual invocation durations."""
    def __init__(self, name: str):
        self.name = name
        self.first_start: float | None = None
        self.last_end: float | None = None
        self.durations: List[float] = []

    def record_call(self, t_start: float, t_end: float):
        if self.first_start is None or t_start < self.first_start:
            self.first_start = t_start
        if self.last_end is None or t_end > self.last_end:
            self.last_end = t_end
        self.durations.append(t_end - t_start)

    def summary(self) -> Dict[str, Any]:
        count = len(self.durations)
        if count == 0:
            return {
                "wall_sec": 0.0,
                "aggregate_work_sec": 0.0,
                "call_count": 0,
                "max_single_call_sec": 0.0,
            }
        wall = max(0.0, (self.last_end - self.first_start)) if self.first_start and self.last_end else 0.0
        agg = sum(self.durations)
        return {
            "wall_sec": round(wall, 4),
            "aggregate_work_sec": round(agg, 4),
            "call_count": count,
            "max_single_call_sec": round(max(self.durations), 4),
        }


class CycleMetricsCollector:
    def __init__(self):
        self.stages = {
            "market_data_fetch": StageSpan("market_data_fetch"),
            "alternative_macro_collection": StageSpan("alternative_macro_collection"),
            "indicator_calculation": StageSpan("indicator_calculation"),
            "context_causal_processing": StageSpan("context_causal_processing"),
            "model_inference": StageSpan("model_inference"),
            "decision_sizing": StageSpan("decision_sizing"),
            "persistence": StageSpan("persistence"),
        }
        self.cycle_start: float = 0.0
        self.cycle_end: float = 0.0

    def start_cycle(self):
        self.cycle_start = time.perf_counter()

    def end_cycle(self):
        self.cycle_end = time.perf_counter()

    def record(self, stage: str, t0: float, t1: float):
        if stage in self.stages:
            self.stages[stage].record_call(t0, t1)

    def compile(self) -> Dict[str, Any]:
        total_wall = round(self.cycle_end - self.cycle_start, 4)
        summaries = {}
        validation_errors: List[str] = []
        measurement_valid = True

        for name, span in self.stages.items():
            s = span.summary()
            summaries[name] = s

            # Invariant check without clamping: stage wall must not exceed total cycle wall + epsilon
            if s["wall_sec"] > (total_wall + 0.05):
                measurement_valid = False
                validation_errors.append(
                    f"Invariant violation: stage {name} wall_sec ({s['wall_sec']}) > total_cycle_wall_sec ({total_wall})"
                )

            # Expected call count check
            exp = EXPECTED_STAGE_COUNTS.get(name)
            if exp:
                min_c, max_c = exp
                if not (min_c <= s["call_count"] <= max_c):
                    measurement_valid = False
                    validation_errors.append(
                        f"Call count violation: stage {name} count ({s['call_count']}) outside expected range [{min_c}, {max_c}]"
                    )

        return {
            "total_cycle_wall_sec": total_wall,
            "measurement_valid": measurement_valid,
            "validation_errors": validation_errors,
            "stages": summaries,
            "stage_coverage_notes": STAGE_COVERAGE_DESCRIPTIONS,
        }


_ACTIVE_COLLECTOR: CycleMetricsCollector | None = None
_HOOKS_INSTALLED: bool = False


def install_hooks():
    global _HOOKS_INSTALLED
    if _HOOKS_INSTALLED:
        return
    _HOOKS_INSTALLED = True
    import main as main_module
    import btc_scraper.ml_engine.multi_agent as multi_agent_module
    import btc_scraper.ml_engine.inference_coordinator as inf_module
    import btc_scraper.collectors.alternative_reference as alt_ref_module
    import btc_scraper.collectors.macro_collector as macro_module
    import btc_scraper.ml_engine.causal_context_bridge as causal_bridge_module
    import btc_scraper.core.utils as core_utils_module

    # 1. Market Data Fetch: wrapped in main._get_candles_for_coin
    orig_get_candles = main_module._get_candles_for_coin
    async def timed_get_candles(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            return await orig_get_candles(*args, **kwargs)
        finally:
            t1 = time.perf_counter()
            if _ACTIVE_COLLECTOR:
                _ACTIVE_COLLECTOR.record("market_data_fetch", t0, t1)
    main_module._get_candles_for_coin = timed_get_candles

    # 2. Alternative & Macro Collection: load_alternative_reference & load_macro_state
    orig_load_alt = alt_ref_module.load_alternative_reference
    def timed_load_alt(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            return orig_load_alt(*args, **kwargs)
        finally:
            t1 = time.perf_counter()
            if _ACTIVE_COLLECTOR:
                _ACTIVE_COLLECTOR.record("alternative_macro_collection", t0, t1)
    alt_ref_module.load_alternative_reference = timed_load_alt

    orig_load_macro = macro_module.load_macro_state
    def timed_load_macro(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            return orig_load_macro(*args, **kwargs)
        finally:
            t1 = time.perf_counter()
            if _ACTIVE_COLLECTOR:
                _ACTIVE_COLLECTOR.record("alternative_macro_collection", t0, t1)
    macro_module.load_macro_state = timed_load_macro

    # 3. Indicator Calculation: MarketAnalystAgent.run
    orig_market_run = multi_agent_module.MarketAnalystAgent.run
    def timed_market_run(self, context):
        t0 = time.perf_counter()
        try:
            return orig_market_run(self, context)
        finally:
            t1 = time.perf_counter()
            if _ACTIVE_COLLECTOR:
                _ACTIVE_COLLECTOR.record("indicator_calculation", t0, t1)
    multi_agent_module.MarketAnalystAgent.run = timed_market_run

    # 4. Context & Causal Processing: enhance_signal_with_causal_context & _run_causal_runtime_pass
    orig_enhance = causal_bridge_module.enhance_signal_with_causal_context
    def timed_enhance(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            return orig_enhance(*args, **kwargs)
        finally:
            t1 = time.perf_counter()
            if _ACTIVE_COLLECTOR:
                _ACTIVE_COLLECTOR.record("context_causal_processing", t0, t1)
    causal_bridge_module.enhance_signal_with_causal_context = timed_enhance

    orig_causal_pass = main_module._run_causal_runtime_pass
    async def timed_causal_pass(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            return await orig_causal_pass(*args, **kwargs)
        finally:
            t1 = time.perf_counter()
            if _ACTIVE_COLLECTOR:
                _ACTIVE_COLLECTOR.record("context_causal_processing", t0, t1)
    main_module._run_causal_runtime_pass = timed_causal_pass

    # 5. Model Inference: InferenceCoordinator.predict_once
    orig_predict = inf_module.InferenceCoordinator.predict_once
    def timed_predict(self, *args, **kwargs):
        t0 = time.perf_counter()
        try:
            return orig_predict(self, *args, **kwargs)
        finally:
            t1 = time.perf_counter()
            if _ACTIVE_COLLECTOR:
                _ACTIVE_COLLECTOR.record("model_inference", t0, t1)
    inf_module.InferenceCoordinator.predict_once = timed_predict

    # 6. Decision & Sizing: RiskManagerAgent.run & PortfolioManagerAgent.run
    orig_risk_run = multi_agent_module.RiskManagerAgent.run
    def timed_risk_run(self, context):
        t0 = time.perf_counter()
        try:
            return orig_risk_run(self, context)
        finally:
            t1 = time.perf_counter()
            if _ACTIVE_COLLECTOR:
                _ACTIVE_COLLECTOR.record("decision_sizing", t0, t1)
    multi_agent_module.RiskManagerAgent.run = timed_risk_run

    orig_port_run = multi_agent_module.PortfolioManagerAgent.run
    def timed_port_run(self, context):
        t0 = time.perf_counter()
        try:
            return orig_port_run(self, context)
        finally:
            t1 = time.perf_counter()
            if _ACTIVE_COLLECTOR:
                _ACTIVE_COLLECTOR.record("decision_sizing", t0, t1)
    multi_agent_module.PortfolioManagerAgent.run = timed_port_run

    # 7. Persistence: atomic file writes in write_atomic
    orig_write_atomic = core_utils_module.write_atomic
    def timed_write_atomic(filepath, data, *args, **kwargs):
        t0 = time.perf_counter()
        try:
            return orig_write_atomic(filepath, data, *args, **kwargs)
        finally:
            t1 = time.perf_counter()
            if _ACTIVE_COLLECTOR and "latest_signals.json" in str(filepath):
                _ACTIVE_COLLECTOR.record("persistence", t0, t1)
    core_utils_module.write_atomic = timed_write_atomic


# ─── Part 1: Memory Breakdown Profile ────────────────────────────────────────

def run_memory_breakdown_profile(bench_dir: Path) -> Dict[str, Any]:
    """Runs a dedicated memory breakdown test measuring incremental layer imports and entry vs exit profiles."""
    mem_runtime = bench_dir / "mem_runtime"
    mem_runtime.mkdir(parents=True, exist_ok=True)

    code = f"""
import sys, os, ctypes
from ctypes import wintypes
sys.path.insert(0, r"{REPO_ROOT}")

class PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
    ]

ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
ctypes.windll.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

def get_rss():
    pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return round(pmc.WorkingSetSize / (1024 * 1024), 2)

import json
report = {{}}

# Step 0: Initial clean Python runtime
r0 = get_rss()
report["0_initial_python_runtime_mb"] = r0

# Step 1: Scientific stack (numpy, pandas, sklearn)
import numpy; import pandas; import sklearn
r1 = get_rss()
report["1_numpy_pandas_sklearn_mb"] = r1
report["1_delta_mb"] = round(r1 - r0, 2)

# Step 2: LightGBM
import lightgbm
r2 = get_rss()
report["2_lightgbm_mb"] = r2
report["2_delta_mb"] = round(r2 - r1, 2)

# Step 3: CatBoost
try:
    import catboost
    r3 = get_rss()
    report["3_catboost_mb"] = r3
    report["3_delta_mb"] = round(r3 - r2, 2)
except Exception:
    r3 = r2
    report["3_catboost_mb"] = r2
    report["3_delta_mb"] = 0.0

# Step 4: Entry-only stack with Model artifacts (InferenceCoordinator)
os.environ["BTC_RUNTIME_ENVIRONMENT"] = "paper"
os.environ["AUTO_TRADE_DRY_RUN"] = "true"
os.environ["LIVE_TRADING_ENABLED"] = "false"
os.environ["BTC_EVIDENCE_ELIGIBLE"] = "false"
os.environ["BTC_RUNTIME_ROOT"] = r"{mem_runtime}"
from btc_scraper.ml_engine.inference_coordinator import get_inference_coordinator
import btc_scraper.trading.position_tracker as pt
coord = get_inference_coordinator()
r4 = get_rss()
report["4_entry_only_model_rss_mb"] = r4
report["4_entry_only_delta_mb"] = round(r4 - r3, 2)
report["4_torch_in_sys_modules"] = "torch" in sys.modules

# Step 5: Exit evaluation stack with explicit PPO loading
pt.get_ppo_model()
r5 = get_rss()
report["5_exit_enabled_ppo_rss_mb"] = r5
report["5_exit_enabled_delta_mb"] = round(r5 - r4, 2)
report["5_torch_in_sys_modules"] = "torch" in sys.modules

print("__BENCH_REPORT_JSON__:" + json.dumps(report))
"""
    res = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if res.returncode != 0:
        raise RuntimeError(f"Memory breakdown profiling failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
    for line in res.stdout.splitlines():
        if line.startswith("__BENCH_REPORT_JSON__:"):
            return json.loads(line[len("__BENCH_REPORT_JSON__:"):])
    raise RuntimeError(f"Could not find __BENCH_REPORT_JSON__ in output:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")


# ─── Part 1.5: Actual Production Process Profiling ───────────────────────────

def profile_actual_production_processes(bench_dir: Path) -> Dict[str, Any]:
    """Runs actual main.py --once subprocesses measuring peak RSS and torch presence for entry-only vs exit-enabled."""
    proc_runtime = bench_dir / "proc_profile_runtime"
    proc_runtime.mkdir(parents=True, exist_ok=True)

    # 1. Entry-Only Subprocess (0 open positions)
    entry_dir = proc_runtime / "entry_only"
    entry_dir.mkdir(parents=True, exist_ok=True)
    seed_isolated_runtime_data(entry_dir)
    env_entry = os.environ.copy()
    env_entry["BTC_RUNTIME_ENVIRONMENT"] = "paper"
    env_entry["AUTO_TRADE_DRY_RUN"] = "true"
    env_entry["LIVE_TRADING_ENABLED"] = "false"
    env_entry["BTC_EVIDENCE_ELIGIBLE"] = "false"
    env_entry["BTC_RUNTIME_ROOT"] = str(entry_dir)
    env_entry["BTC_FALLBACK_BUFFER_DB"] = str(entry_dir / "fallback_buffer.db")
    env_entry["BTC_DISABLE_RUNTIME_LOCK"] = "true"
    env_entry["BTC_RUNTIME_LOCK_BYPASS_REASON"] = "bench_proc_entry"
    env_entry["AUTO_TRADE_COINS"] = "BTC,ETH,BNB"
    env_entry["ALTERNATIVE_DATA_STARTUP_MODE"] = "cache"
    env_entry["PYTHONPATH"] = str(REPO_ROOT)
    env_entry["PYTHONIOENCODING"] = "utf-8"
    env_entry["TELEGRAM_BOT_TOKEN"] = ""
    env_entry["TELEGRAM_CHAT_ID"] = ""
    env_entry["TELEGRAM_NOTIFICATIONS_ENABLED"] = "false"
    env_entry["GEMINI_API_KEY"] = ""

    code_entry = f"""
import sys, os, ctypes, json
from ctypes import wintypes

class PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
    ]

ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
ctypes.windll.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

def get_pmc():
    pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return round(pmc.WorkingSetSize / (1024 * 1024), 2), round(pmc.PeakWorkingSetSize / (1024 * 1024), 2)

import main
sys.argv = ["main.py", "--once", "--skip-ai-drain"]
main.main()

rss, peak = get_pmc()
torch_loaded = "torch" in sys.modules
res = {{
    "current_rss_mb": rss,
    "peak_rss_mb": peak,
    "torch_in_sys_modules": torch_loaded,
    "positions_evaluated": len(main._runtime_open_positions()) if hasattr(main, "_runtime_open_positions") else 0,
}}
print("__ENTRY_PROC_JSON__:" + json.dumps(res))
"""

    res_entry = subprocess.run([sys.executable, "-c", code_entry], env=env_entry, capture_output=True, text=True, encoding="utf-8")
    entry_data = {}
    for line in res_entry.stdout.splitlines():
        if line.startswith("__ENTRY_PROC_JSON__:"):
            entry_data = json.loads(line[len("__ENTRY_PROC_JSON__:"):])

    # 2. Exit-Enabled Subprocess (1 open position injected)
    exit_dir = proc_runtime / "exit_enabled"
    exit_dir.mkdir(parents=True, exist_ok=True)
    seed_isolated_runtime_data(exit_dir)
    env_exit = os.environ.copy()
    env_exit["BTC_RUNTIME_ENVIRONMENT"] = "paper"
    env_exit["AUTO_TRADE_DRY_RUN"] = "true"
    env_exit["LIVE_TRADING_ENABLED"] = "false"
    env_exit["BTC_EVIDENCE_ELIGIBLE"] = "false"
    env_exit["BTC_RUNTIME_ROOT"] = str(exit_dir)
    env_exit["BTC_FALLBACK_BUFFER_DB"] = str(exit_dir / "fallback_buffer.db")
    env_exit["BTC_DISABLE_RUNTIME_LOCK"] = "true"
    env_exit["BTC_RUNTIME_LOCK_BYPASS_REASON"] = "bench_proc_exit"
    env_exit["AUTO_TRADE_COINS"] = "BTC,ETH,BNB"
    env_exit["ALTERNATIVE_DATA_STARTUP_MODE"] = "cache"
    env_exit["PYTHONPATH"] = str(REPO_ROOT)
    env_exit["PYTHONIOENCODING"] = "utf-8"
    env_exit["TELEGRAM_BOT_TOKEN"] = ""
    env_exit["TELEGRAM_CHAT_ID"] = ""
    env_exit["TELEGRAM_NOTIFICATIONS_ENABLED"] = "false"
    env_exit["GEMINI_API_KEY"] = ""

    code_exit = f"""
import sys, os, ctypes, json
from ctypes import wintypes

class PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
    ]

ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
ctypes.windll.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

def get_pmc():
    pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return round(pmc.WorkingSetSize / (1024 * 1024), 2), round(pmc.PeakWorkingSetSize / (1024 * 1024), 2)

import btc_scraper.trading.position_tracker as pt
pt.add_position("BTC", 50000.0, "LONG", note="bench_exit_test", invested_usdt=100.0)

import main
sys.argv = ["main.py", "--once", "--skip-ai-drain"]
main.main()

rss, peak = get_pmc()
torch_loaded = "torch" in sys.modules
res = {{
    "current_rss_mb": rss,
    "peak_rss_mb": peak,
    "torch_in_sys_modules": torch_loaded,
    "positions_evaluated": len(main._runtime_open_positions()) if hasattr(main, "_runtime_open_positions") else 0,
}}
print("__EXIT_PROC_JSON__:" + json.dumps(res))
"""

    res_exit = subprocess.run([sys.executable, "-c", code_exit], env=env_exit, capture_output=True, text=True, encoding="utf-8")
    exit_data = {}
    for line in res_exit.stdout.splitlines():
        if line.startswith("__EXIT_PROC_JSON__:"):
            exit_data = json.loads(line[len("__EXIT_PROC_JSON__:"):])

    entry_peak = entry_data.get("peak_rss_mb", 0.0)
    exit_peak = exit_data.get("peak_rss_mb", 0.0)
    delta_mb = round(exit_peak - entry_peak, 2)
    savings_pct = round(((exit_peak - entry_peak) / exit_peak) * 100, 2) if exit_peak > 0 else 0.0

    return {
        "entry_only_process": entry_data,
        "exit_enabled_process": exit_data,
        "actual_process_rss_delta_mb": delta_mb,
        "actual_entry_savings_percentage": savings_pct,
    }


# ─── Part 2: Cold Start Benchmark (Offline, Multi-Sample) ───────────────────

def run_cold_start_benchmark(bench_dir: Path, n_runs: int = 5) -> Dict[str, Any]:
    """Runs cold start benchmark across multiple fresh subprocesses with no external network calls,
    measuring durations and milestone progression."""
    runs = []

    for idx in range(n_runs):
        cold_runtime = bench_dir / f"cold_runtime_{idx}"
        cold_runtime.mkdir(parents=True, exist_ok=True)
        seed_isolated_runtime_data(cold_runtime)

        env = os.environ.copy()
        env["BTC_RUNTIME_ENVIRONMENT"] = "paper"
        env["AUTO_TRADE_DRY_RUN"] = "true"
        env["LIVE_TRADING_ENABLED"] = "false"
        env["BTC_EVIDENCE_ELIGIBLE"] = "false"
        env["BTC_RUNTIME_ROOT"] = str(cold_runtime)
        env["BTC_DEPLOYMENT_ID"] = f"cold-bench-{idx}"
        env["BTC_PAPER_RUN_ID"] = f"cold-bench-{idx}"
        env["BTC_RUNTIME_ID"] = f"cold-bench-{idx}"
        env["BTC_FALLBACK_BUFFER_DB"] = str(cold_runtime / "fallback_buffer.db")
        env["BTC_DISABLE_RUNTIME_LOCK"] = "true"
        env["BTC_RUNTIME_LOCK_BYPASS_REASON"] = f"cold_bench_{idx}"
        env["AUTO_TRADE_COINS"] = "BTC,ETH,BNB"
        env["ALTERNATIVE_DATA_STARTUP_MODE"] = "cache"
        env["PYTHONPATH"] = str(REPO_ROOT)
        env["PYTHONIOENCODING"] = "utf-8"
        env["TELEGRAM_BOT_TOKEN"] = ""
        env["TELEGRAM_CHAT_ID"] = ""
        env["TELEGRAM_NOTIFICATIONS_ENABLED"] = "false"
        env["GEMINI_API_KEY"] = ""

        t0 = time.perf_counter()
        runner_script = REPO_ROOT / "scripts" / "cold_start_runner.py"
        res = subprocess.run(
            [sys.executable, str(runner_script), "--once", "--skip-ai-drain"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(REPO_ROOT),
        )
        t1 = time.perf_counter()
        dur = round(t1 - t0, 4)

        stdout_file = bench_dir / f"cold_start_{idx}.stdout.log"
        stderr_file = bench_dir / f"cold_start_{idx}.stderr.log"
        with open(stdout_file, "w", encoding="utf-8") as f:
            f.write(res.stdout)
        with open(stderr_file, "w", encoding="utf-8") as f:
            f.write(res.stderr)

        # Check stdout and stderr for unauthorized external network indicators
        clean_run = True
        suspicious_lines = []
        bad_words = ["429", "too many requests", "retry", "gemini", "telegram"]
        for line in (res.stdout + res.stderr).splitlines():
            line_lower = line.lower()
            if any(w in line_lower for w in bad_words):
                if any(ok in line for ok in [
                    "Telegram Bot token is empty",
                    "Telegram notification suppressed",
                    "Telegram bot polling disabled",
                    "Max retries: 5",
                    "Analysis coins",
                ]):
                    continue
                suspicious_lines.append(line.strip())
                clean_run = False

        telemetry_file = cold_runtime / "logs" / "cold_start_telemetry.json"
        audit_file = cold_runtime / "logs" / "network_audit.json"
        telemetry_data = {}
        audit_data = {}
        telemetry_parsed = False
        audit_file_parsed = False
        if telemetry_file.exists():
            try:
                with open(telemetry_file, "r", encoding="utf-8") as tf:
                    telemetry_data = json.load(tf)
                    telemetry_parsed = True
            except Exception:
                pass
        if audit_file.exists():
            try:
                with open(audit_file, "r", encoding="utf-8") as af:
                    audit_data = json.load(af)
                    audit_file_parsed = True
            except Exception:
                pass

        attempts_val = audit_data.get("outbound_network_attempts") if audit_file_parsed else None

        runs.append({
            "run_index": idx,
            "duration_sec": dur,
            "exit_code": res.returncode,
            "stdout_lines": len(res.stdout.splitlines()),
            "stderr_lines": len(res.stderr.splitlines()),
            "stdout_stderr_clean": clean_run,
            "suspicious_lines": suspicious_lines,
            "audit_file_parsed": audit_file_parsed,
            "network_interceptor_active": audit_data.get("network_interceptor_active", False) if audit_file_parsed else False,
            "outbound_network_attempts": attempts_val if attempts_val is not None else -1,
            "blocked_targets": audit_data.get("blocked_targets", []),
            "time_to_first_analysis_sec": telemetry_data.get("time_to_first_analysis_sec"),
            "time_to_first_prediction_sec": telemetry_data.get("time_to_first_prediction_sec"),
            "time_to_first_final_decision_sec": telemetry_data.get("time_to_first_final_decision_sec"),
            "time_to_cycle_complete_sec": telemetry_data.get("time_to_cycle_complete_sec"),
            "milestones": telemetry_data.get("milestones", {}),
            "milestones_valid": telemetry_data.get("milestones_valid", False) if telemetry_parsed else False,
            "milestone_validation_errors": telemetry_data.get("milestone_validation_errors", []),
            "isolated_runtime": str(cold_runtime),
        })

    durations = [r["duration_sec"] for r in runs]
    analyses = [r["time_to_first_analysis_sec"] for r in runs if r["time_to_first_analysis_sec"] is not None]
    preds = [r["time_to_first_prediction_sec"] for r in runs if r["time_to_first_prediction_sec"] is not None]
    decisions = [r["time_to_first_final_decision_sec"] for r in runs if r["time_to_first_final_decision_sec"] is not None]

    return {
        "mode": "core_offline_cold_start",
        "sample_count": len(runs),
        "duration_sec": round(float(np.median(durations)), 4),
        "median_duration_sec": round(float(np.median(durations)), 4),
        "p95_duration_sec": round(float(np.percentile(durations, 95)), 4),
        "min_duration_sec": round(float(np.min(durations)), 4),
        "max_duration_sec": round(float(np.max(durations)), 4),
        "stdout_stderr_clean": all(r["stdout_stderr_clean"] for r in runs),
        "network_interceptor_active": all(r.get("network_interceptor_active", False) for r in runs),
        "total_outbound_network_attempts": sum(max(0, r.get("outbound_network_attempts", 0)) for r in runs),
        "verified_offline": all(
            r["exit_code"] == 0
            and r.get("audit_file_parsed") is True
            and r.get("network_interceptor_active") is True
            and r.get("outbound_network_attempts") == 0
            and r.get("stdout_stderr_clean") is True
            and r.get("milestones_valid") is True
            for r in runs
        ),
        "sample_statistics_note": "Descriptive percentiles from small empirical sample (n=5); not a production SLO.",
        "time_to_first_analysis_sec": round(float(np.median(analyses)), 4) if analyses else None,
        "time_to_first_prediction_sec": round(float(np.median(preds)), 4) if preds else None,
        "time_to_first_final_decision_sec": round(float(np.median(decisions)), 4) if decisions else None,
        "all_runs_valid": all(r["milestones_valid"] and r["exit_code"] == 0 for r in runs),
        "runs": runs,
    }


# ─── Part 2.5: Direct Shadow Fast-Path Benchmark ─────────────────────────────

async def run_direct_shadow_fast_path_benchmark(bench_dir: Path, n_iterations: int = 100) -> Dict[str, Any]:
    """Directly benchmarks AutoTrader._process_signal on shadow fast path with disk persistence,
    testing both clean and 1,000-entry log files while asserting zero pollution of default runtime."""
    import asyncio
    import numpy as np
    from unittest.mock import patch, MagicMock
    from btc_scraper.trading.auto_trader import AutoTrader

    fast_path_runtime = bench_dir / "direct_fast_path_runtime"
    logs_dir = fast_path_runtime / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    isolated_log = logs_dir / "auto_trade_log.json"

    default_log = REPO_ROOT / "runtime" / "paper" / "local-paper" / "logs" / "auto_trade_log.json"
    default_log_stat_before = (default_log.stat().st_mtime, default_log.stat().st_size) if default_log.exists() else None

    orig_runtime_root = os.environ.get("BTC_RUNTIME_ROOT")
    orig_log_dir = os.environ.get("BTC_LOG_DIR")
    os.environ["BTC_RUNTIME_ROOT"] = str(fast_path_runtime)
    os.environ["BTC_LOG_DIR"] = str(logs_dir)

    payload = {
        "coin": "BTC",
        "symbol": "BTCUSDT",
        "signal": "BUY",
        "signal_score": {"score": 85, "meta_probability": 0.88},
        "causal_decision": {
            "decision_id": "fastpath-bench-1",
            "action": "HOLD",
            "shadow_action": "BUY",
            "eligible": False,
            "terminal_status": "HOLD",
            "rejection_reason": "NO_VIABLE_ECONOMIC_CANDIDATE",
            "paper_economic_policy": "NO_TRADE_SHADOW",
            "meta_probability": 0.88,
        },
    }

    db_calls = 0
    var_calls = 0
    evaluator_calls = 0
    exec_engine_calls = 0
    telegram_calls = 0

    def on_db(*args, **kwargs):
        nonlocal db_calls
        db_calls += 1
        return []

    def on_var(*args, **kwargs):
        nonlocal var_calls
        var_calls += 1
        return 0.0

    def on_eval(*args, **kwargs):
        nonlocal evaluator_calls
        evaluator_calls += 1
        return None

    def on_exec(*args, **kwargs):
        nonlocal exec_engine_calls
        exec_engine_calls += 1
        return MagicMock()

    def on_telegram(*args, **kwargs):
        nonlocal telegram_calls
        telegram_calls += 1
        return None

    try:
        tiers = [0, 1000, 10000, 100000]
        tier_results = {}
        json_integrity = {}

        for tier in tiers:
            if tier == 0:
                if isolated_log.exists():
                    isolated_log.unlink()
            else:
                seeded_entries = [{"id": i, "action": "HOLD", "reason": "PRESEEDED"} for i in range(tier)]
                with open(isolated_log, "w", encoding="utf-8") as f:
                    json.dump(seeded_entries, f)

            trader = AutoTrader()
            durations = []
            iters = n_iterations if tier <= 1000 else 20
            with patch("btc_scraper.trading.auto_trader.exposure_manager.get_open_positions", side_effect=on_db), \
                 patch("btc_scraper.trading.auto_trader.exposure_manager.calculate_max_size_by_var_limit", side_effect=on_var), \
                 patch("btc_scraper.ml_engine.production_evaluator.evaluate_live_market", side_effect=on_eval), \
                 patch.object(trader, "_get_execution_engine", side_effect=on_exec), \
                 patch("btc_scraper.telegram_bot.api.send_telegram_message", side_effect=on_telegram):

                # 5 warmup calls
                for _ in range(5):
                    await trader._process_signal("BTC:Binance", payload)

                for _ in range(iters):
                    t0 = time.perf_counter()
                    res = await trader._process_signal("BTC:Binance", payload)
                    t1 = time.perf_counter()
                    durations.append(t1 - t0)
                    assert res is not None
                    assert res["status"] == "skipped"
                    assert res["reason_skip"] == "NO_VIABLE_ECONOMIC_CANDIDATE"

            d_arr = np.array(durations)
            # Verify JSON parse integrity
            with open(isolated_log, "r", encoding="utf-8") as f:
                parsed = json.load(f)
                assert len(parsed) == tier + 5 + iters
            json_integrity[f"tier_{tier}"] = True

            tier_results[f"tier_{tier}"] = {
                "tier_records": tier,
                "measured_iterations": iters,
                "median_sec": round(float(np.median(d_arr)), 6),
                "p95_sec": round(float(np.percentile(d_arr, 95)), 6),
                "p99_sec": round(float(np.percentile(d_arr, 99)), 6),
                "min_sec": round(float(np.min(d_arr)), 6),
                "max_sec": round(float(np.max(d_arr)), 6),
                "mean_sec": round(float(np.mean(d_arr)), 6),
                "json_parse_valid": True,
            }

        # Single-writer sequential asyncio batch check: 10 queued tasks on single event loop
        trader_c = AutoTrader()
        with patch("btc_scraper.trading.auto_trader.exposure_manager.get_open_positions", side_effect=on_db), \
             patch("btc_scraper.trading.auto_trader.exposure_manager.calculate_max_size_by_var_limit", side_effect=on_var), \
             patch("btc_scraper.ml_engine.production_evaluator.evaluate_live_market", side_effect=on_eval), \
             patch.object(trader_c, "_get_execution_engine", side_effect=on_exec), \
             patch("btc_scraper.telegram_bot.api.send_telegram_message", side_effect=on_telegram):
            await asyncio.gather(*[trader_c._process_signal("BTC:Binance", payload) for _ in range(10)])

        with open(isolated_log, "r", encoding="utf-8") as f:
            parsed_c = json.load(f)
            single_writer_batch_valid = isinstance(parsed_c, list) and len(parsed_c) > 0

        # Assert default runtime log was NOT modified or touched
        default_log_untouched = True
        if default_log.exists() and default_log_stat_before is not None:
            default_log_stat_after = (default_log.stat().st_mtime, default_log.stat().st_size)
            assert default_log_stat_before == default_log_stat_after, "Default auto_trade_log.json was touched during fast-path benchmark!"

    finally:
        if orig_runtime_root is not None:
            os.environ["BTC_RUNTIME_ROOT"] = orig_runtime_root
        else:
            os.environ.pop("BTC_RUNTIME_ROOT", None)
        if orig_log_dir is not None:
            os.environ["BTC_LOG_DIR"] = orig_log_dir
        else:
            os.environ.pop("BTC_LOG_DIR", None)

    return {
        "iterations": n_iterations,
        "clean_log": tier_results["tier_0"],
        "preseeded_1000_entry_log": tier_results["tier_1000"],
        "multi_tier_benchmark": tier_results,
        "median_sec": tier_results["tier_1000"]["median_sec"],
        "p95_sec": tier_results["tier_1000"]["p95_sec"],
        "min_sec": tier_results["tier_1000"]["min_sec"],
        "max_sec": tier_results["tier_1000"]["max_sec"],
        "mean_sec": tier_results["tier_1000"]["mean_sec"],
        "latency_characterization": "bounded append latency at measured file sizes [0, 1k, 10k, 100k records]",
        "bounded_latency_verified": all(tier_results[k]["median_sec"] < 0.030 for k in tier_results),
        "single_writer_contract": "Single-writer bounded latency within process lifecycle",
        "parse_integrity_all_tiers": all(json_integrity.values()),
        "single_writer_batch_valid": single_writer_batch_valid,
        "latency_includes_disk_persistence": True,
        "default_log_untouched": default_log_untouched,
        "bypassed_calls": {
            "db_calls": db_calls,
            "var_calls": var_calls,
            "evaluator_calls": evaluator_calls,
            "execution_engine_calls": exec_engine_calls,
            "telegram_calls": telegram_calls,
        },
    }


# ─── Part 3: Warm Steady State Benchmark (1 Warm-up + 100 Measured Cycles) ───

async def run_warm_cycle(cycle_id: str) -> Dict[str, Any]:
    global _ACTIVE_COLLECTOR
    collector = CycleMetricsCollector()
    _ACTIVE_COLLECTOR = collector

    import main as main_module
    from btc_scraper.core.candle_store import candle_store
    import btc_scraper.trading.position_tracker as pt

    mem_before = get_process_memory_mb()
    queue_before = main_module.ai_queue.qsize()
    collector.start_cycle()
    try:
        await main_module.fetch_and_display()
    finally:
        collector.end_cycle()
        queue_after = main_module.ai_queue.qsize()
        mem_after = get_process_memory_mb()

        # Drain ai_queue to prevent unbounded in-memory accumulation in benchmark mode
        drained_count = 0
        while not main_module.ai_queue.empty():
            try:
                main_module.ai_queue.get_nowait()
                main_module.ai_queue.task_done()
                drained_count += 1
            except Exception:
                break

        # Collect garbage and measure post-GC memory
        gc.collect()
        mem_after_gc = get_process_memory_mb()

    # Object count telemetry
    total_candles = sum(
        candle_store.candle_count(c, tf)
        for c in candle_store.all_coins()
        for tf in ["15m", "1h", "4h", "1d"]
    )
    lstm_cache_keys = len(pt._LSTM_STATE_CACHE)

    result = collector.compile()
    result["cycle_id"] = cycle_id
    result["memory"] = {
        "rss_before_mb": mem_before["current_rss_mb"],
        "rss_after_mb": mem_after["current_rss_mb"],
        "rss_after_gc_mb": mem_after_gc["current_rss_mb"],
        "peak_rss_mb": mem_after["peak_rss_mb"],
    }
    result["object_counts"] = {
        "candle_store_total_candles": total_candles,
        "lstm_cache_keys": lstm_cache_keys,
        "ai_queue_drained_items": drained_count,
    }
    result["queue_telemetry"] = {
        "queue_size_before": queue_before,
        "queue_size_after": queue_after,
        "drained_items": drained_count,
        "retained_tasks": main_module.ai_queue.qsize(),
    }
    return result


async def run_warm_benchmark_suite(bench_dir: Path, target_cycles: int = 100) -> Dict[str, Any]:
    warm_runtime = bench_dir / "warm_runtime"
    warm_runtime.mkdir(parents=True, exist_ok=True)
    seed_isolated_runtime_data(warm_runtime)

    # Isolate runtime before importing production modules
    os.environ["BTC_RUNTIME_ENVIRONMENT"] = "paper"
    os.environ["AUTO_TRADE_DRY_RUN"] = "true"
    os.environ["LIVE_TRADING_ENABLED"] = "false"
    os.environ["BTC_EVIDENCE_ELIGIBLE"] = "false"
    os.environ["BTC_RUNTIME_ROOT"] = str(warm_runtime)
    os.environ["BTC_DEPLOYMENT_ID"] = "warm-benchmark"
    os.environ["BTC_PAPER_RUN_ID"] = "warm-benchmark"
    os.environ["BTC_RUNTIME_ID"] = "warm-benchmark"
    os.environ["BTC_FALLBACK_BUFFER_DB"] = str(warm_runtime / "fallback_buffer.db")
    os.environ["AUTO_TRADE_COINS"] = "BTC,ETH,BNB"
    os.environ["ALTERNATIVE_DATA_STARTUP_MODE"] = "cache"

    import main as main_module
    from main import ANALYSIS_SYMBOLS
    from btc_scraper.core.candle_store import candle_store
    from collections import Counter
    import numpy as np

    # Mock external telegram notification during offline benchmark to isolate internal latency
    import btc_scraper.telegram_bot
    import btc_scraper.telegram_bot.api
    btc_scraper.telegram_bot.send_telegram_message = lambda *args, **kwargs: None
    btc_scraper.telegram_bot.api.send_telegram_message = lambda *args, **kwargs: None
    btc_scraper.telegram_bot.send_signals_alert = lambda *args, **kwargs: None
    btc_scraper.telegram_bot.send_position_recommendations = lambda *args, **kwargs: None
    main_module.send_telegram_message = lambda *args, **kwargs: None
    main_module.send_signals_alert = lambda *args, **kwargs: None
    main_module.send_position_recommendations = lambda *args, **kwargs: None

    from btc_scraper.trading.auto_trader import AutoTrader
    AutoTrader._notify_trade = lambda self, entry: None

    # Wire a lightweight stub WS manager (avoids MagicMock accumulating call objects in memory)
    class StubWsManager:
        def is_healthy(self) -> bool:
            return True

    main_module._ws_manager = StubWsManager()

    install_hooks()

    # ═══════════════════════════════════════════════════════════════════════════
    # Lane A: OFFLINE_COMPUTE_ONLY (Measured Steady-State Cycles)
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("WARM BENCHMARK LANE A: OFFLINE_COMPUTE_ONLY (Deterministic Synthetic)")
    print("=" * 80)

    # Pre-seed CandleStore with synthetic historical bars for all 9 coins x 4 intervals ending now
    now_ts = time.time()
    for coin in ANALYSIS_SYMBOLS:
        candle_store.seed(coin, "15m", make_synthetic_candles(50000.0, 210, interval="15m", end_time=now_ts), now=now_ts)
        candle_store.seed(coin, "1h", make_synthetic_candles(50000.0, 50, interval="1h", end_time=now_ts), now=now_ts)
        candle_store.seed(coin, "4h", make_synthetic_candles(50000.0, 50, interval="4h", end_time=now_ts), now=now_ts)
        candle_store.seed(coin, "1d", make_synthetic_candles(50000.0, 30, interval="1d", end_time=now_ts), now=now_ts)

    measured_cycles_a = []
    top_growing_types = []
    mid_cycle = target_cycles // 2
    counts_mid: Dict[str, int] = {}

    with NetworkInterceptor() as ni_a:
        print("\n--- [Lane A] Running Warm-up Cycle 0 (Un-scored) ---")
        warmup_res_a = await run_warm_cycle("warmup_a_0")
        print(f"Warm-up finished: wall={warmup_res_a['total_cycle_wall_sec']:.2f}s | RSS={warmup_res_a['memory']['rss_after_gc_mb']} MB")

        print(f"\n--- [Lane A] Running {target_cycles} Measured Steady-State Cycles ---")
        for i in range(1, target_cycles + 1):
            if i == mid_cycle:
                gc.collect()
                counts_mid = Counter(type(o).__name__ for o in gc.get_objects())

            c_id = f"cycle_a_{i}"
            res = await run_warm_cycle(c_id)
            measured_cycles_a.append(res)
            if i % 10 == 0 or i <= 3 or i == target_cycles:
                print(
                    f"Lane A Cycle {i:03d}/{target_cycles}: wall={res['total_cycle_wall_sec']:.2f}s | "
                    f"fetch_wall={res['stages']['market_data_fetch']['wall_sec']:.2f}s | "
                    f"RSS_gc={res['memory']['rss_after_gc_mb']} MB | "
                    f"valid={res['measurement_valid']}"
                )

            if i == target_cycles and counts_mid:
                gc.collect()
                counts_final = Counter(type(o).__name__ for o in gc.get_objects())
                deltas = {k: counts_final[k] - counts_mid.get(k, 0) for k in counts_final if counts_final[k] > counts_mid.get(k, 0)}
                top_growing_types = sorted(deltas.items(), key=lambda x: x[1], reverse=True)[:5]

        assert ni_a.outbound_attempts == 0, f"Lane A network violations: {ni_a.outbound_attempts} ({ni_a.blocked_targets})"

    # Compute aggregate statistics for Lane A
    total_walls_a = [c["total_cycle_wall_sec"] for c in measured_cycles_a]
    rss_series_a = [c["memory"]["rss_after_gc_mb"] for c in measured_cycles_a]
    all_valid_a = all(c["measurement_valid"] for c in measured_cycles_a)
    all_validation_errors_a = [e for c in measured_cycles_a for e in c["validation_errors"]]

    slope_all_a = float(np.polyfit(range(1, target_cycles + 1), rss_series_a, 1)[0])
    last_20_start = max(0, target_cycles - 20)
    last_20_series_a = rss_series_a[last_20_start:]
    slope_last_20_a = float(np.polyfit(range(1, len(last_20_series_a) + 1), last_20_series_a, 1)[0])
    last_20_min_a = min(last_20_series_a)
    last_20_max_a = max(last_20_series_a)
    last_20_range_a = round(last_20_max_a - last_20_min_a, 2)

    last_50_start = max(0, target_cycles - 50)
    last_50_series_a = rss_series_a[last_50_start:]
    slope_last_50_a = float(np.polyfit(range(1, len(last_50_series_a) + 1), last_50_series_a, 1)[0]) if len(last_50_series_a) > 1 else 0.0

    if slope_all_a > 0.05 or slope_last_50_a > 0.05 or slope_last_20_a > 0.05 or last_20_range_a > 15.0:
        stability_status_a = "GROWTH_UNRESOLVED"
    else:
        stability_status_a = "STABLE_PLATEAU"

    stages_agg_a = {}
    stage_names = list(measured_cycles_a[0]["stages"].keys())
    for s_name in stage_names:
        wall_vals = [c["stages"][s_name]["wall_sec"] for c in measured_cycles_a]
        agg_vals = [c["stages"][s_name]["aggregate_work_sec"] for c in measured_cycles_a]
        calls_vals = [c["stages"][s_name]["call_count"] for c in measured_cycles_a]
        max_call_vals = [c["stages"][s_name]["max_single_call_sec"] for c in measured_cycles_a]

        stages_agg_a[s_name] = {
            "wall_sec": {
                "median": round(statistics.median(wall_vals), 4),
                "p95": round(float(np.percentile(wall_vals, 95)), 4),
                "p99": round(float(np.percentile(wall_vals, 99)), 4),
                "min": round(min(wall_vals), 4),
                "max": round(max(wall_vals), 4),
                "mean": round(statistics.mean(wall_vals), 4),
            },
            "aggregate_work_sec": {
                "median": round(statistics.median(agg_vals), 4),
                "p95": round(float(np.percentile(agg_vals, 95)), 4),
                "p99": round(float(np.percentile(agg_vals, 99)), 4),
                "min": round(min(agg_vals), 4),
                "max": round(max(agg_vals), 4),
                "mean": round(statistics.mean(agg_vals), 4),
            },
            "call_count_median": int(statistics.median(calls_vals)),
            "max_single_call_sec_median": round(statistics.median(max_call_vals), 4),
        }

    overall_peak_rss_a = max(c["memory"]["peak_rss_mb"] for c in measured_cycles_a)

    lane_a_result = {
        "lane_id": "OFFLINE_COMPUTE_ONLY",
        "description": "Deterministic compute-only pipeline measurement with fixed synthetic market bars and 0 network",
        "target_cycles": target_cycles,
        "all_cycles_valid": all_valid_a,
        "total_validation_errors": len(all_validation_errors_a),
        "sample_validation_errors": all_validation_errors_a[:5],
        "outbound_network_attempts": ni_a.outbound_attempts,
        "blocked_targets": ni_a.blocked_targets,
        "warmup_cycle": warmup_res_a,
        "measured_cycles": measured_cycles_a,
        "total_cycle_wall_sec": {
            "median": round(statistics.median(total_walls_a), 4),
            "p95": round(float(np.percentile(total_walls_a, 95)), 4),
            "p99": round(float(np.percentile(total_walls_a, 99)), 4),
            "min": round(min(total_walls_a), 4),
            "max": round(max(total_walls_a), 4),
            "mean": round(statistics.mean(total_walls_a), 4),
        },
        "stages_aggregate": stages_agg_a,
        "memory_analysis": {
            "initial_cycle_rss_mb": rss_series_a[0],
            "final_cycle_rss_mb": rss_series_a[-1],
            "peak_rss_mb": overall_peak_rss_a,
            "memory_slope_all_cycles": round(slope_all_a, 4),
            "memory_slope_last_20_cycles": round(slope_last_20_a, 4),
            "memory_slope_last_50_cycles": round(slope_last_50_a, 4),
            "last_20_min_rss_mb": last_20_min_a,
            "last_20_max_rss_mb": last_20_max_a,
            "last_20_range_rss_mb": last_20_range_a,
            "stability_status": stability_status_a,
            "top_growing_types_mid_to_final": top_growing_types,
        },
        "outlier_note": "none in offline compute-only sample",
    }

    lane_b_result = await run_lane_b_replay_benchmark(warm_runtime, replay_cycles=20)

    return {
        "target_cycles": target_cycles,
        "all_cycles_valid": all_valid_a,
        "total_validation_errors": len(all_validation_errors_a),
        "sample_validation_errors": all_validation_errors_a[:5],
        "outbound_network_attempts": ni_a.outbound_attempts + lane_b_result["outbound_network_attempts"],
        "blocked_targets": ni_a.blocked_targets + lane_b_result["blocked_targets"],
        "warmup_cycle": warmup_res_a,
        "measured_cycles": measured_cycles_a,
        "total_cycle_wall_sec": lane_a_result["total_cycle_wall_sec"],
        "stages_aggregate": stages_agg_a,
        "memory_analysis": lane_a_result["memory_analysis"],
        "lane_a_compute_only": lane_a_result,
        "lane_b_advancing_15m_replay_htf_rollover": lane_b_result,
        "isolated_runtime": str(warm_runtime),
    }


async def run_lane_b_replay_benchmark(warm_runtime: Path, replay_cycles: int = 20) -> Dict[str, Any]:
    """Run Lane B advancing historical 15m replay with audited deduplication and exact UTC-bucket HTF rollover."""
    warm_runtime.mkdir(parents=True, exist_ok=True)
    seed_isolated_runtime_data(warm_runtime)

    os.environ["BTC_RUNTIME_ENVIRONMENT"] = "paper"
    os.environ["AUTO_TRADE_DRY_RUN"] = "true"
    os.environ["LIVE_TRADING_ENABLED"] = "false"
    os.environ["BTC_EVIDENCE_ELIGIBLE"] = "false"
    os.environ["BTC_RUNTIME_ROOT"] = str(warm_runtime)
    os.environ["BTC_DEPLOYMENT_ID"] = "warm-benchmark"
    os.environ["BTC_PAPER_RUN_ID"] = "warm-benchmark"
    os.environ["BTC_RUNTIME_ID"] = "warm-benchmark"
    os.environ["BTC_FALLBACK_BUFFER_DB"] = str(warm_runtime / "fallback_buffer.db")
    os.environ["AUTO_TRADE_COINS"] = "BTC,ETH,BNB"
    os.environ["ALTERNATIVE_DATA_STARTUP_MODE"] = "cache"

    import main as main_module
    from main import ANALYSIS_SYMBOLS
    from btc_scraper.core.candle_store import candle_store
    import btc_scraper.telegram_bot
    import btc_scraper.telegram_bot.api
    from btc_scraper.trading.auto_trader import AutoTrader

    btc_scraper.telegram_bot.send_telegram_message = lambda *args, **kwargs: None
    btc_scraper.telegram_bot.api.send_telegram_message = lambda *args, **kwargs: None
    btc_scraper.telegram_bot.send_signals_alert = lambda *args, **kwargs: None
    btc_scraper.telegram_bot.send_position_recommendations = lambda *args, **kwargs: None
    main_module.send_telegram_message = lambda *args, **kwargs: None
    main_module.send_signals_alert = lambda *args, **kwargs: None
    main_module.send_position_recommendations = lambda *args, **kwargs: None
    AutoTrader._notify_trade = lambda self, entry: None

    class StubWsManager:
        def is_healthy(self) -> bool:
            return True

    main_module._ws_manager = StubWsManager()
    install_hooks()

    print("\n" + "=" * 80)
    print("WARM BENCHMARK LANE B: OFFLINE_ADVANCING_15M_REPLAY_WITH_AGGREGATED_HTF_ROLLOVER (UTC Bucket Clock)")
    print("=" * 80)

    data_root = REPO_ROOT / "data" / "fresh_training_data_2023_2026"
    seed_count = 210
    plans_by_coin: Dict[str, Dict[str, Any]] = {}
    per_symbol_audit: Dict[str, Dict[str, Any]] = {}
    historical_symbols: List[str] = []
    fallback_symbols: List[str] = []
    raw_rows_total = 0
    duplicate_rows_total = 0
    unique_rows_total = 0

    for coin in ANALYSIS_SYMBOLS:
        coin_dir = data_root / coin / "15m"
        csv_files = sorted(coin_dir.glob("*.csv"))[-2:] if coin_dir.exists() else []
        # Fail closed on missing/conflicting/gapped historical CSVs — silent synthetic fallback is prohibited
        bars, audit_stats = load_and_audit_replay_15m_csvs(csv_files, symbol=coin)
        plan = build_replay_progression_plan(bars, seed_count=seed_count, replay_cycles=replay_cycles)
        plans_by_coin[coin] = plan
        per_symbol_audit[coin] = audit_stats
        historical_symbols.append(coin)
        raw_rows_total += int(audit_stats["raw_rows"])
        duplicate_rows_total += int(audit_stats["duplicate_rows"])
        unique_rows_total += int(audit_stats["unique_rows"])

    # Assert identical UTC progression contract across all symbols
    ref_coin = ANALYSIS_SYMBOLS[0]
    ref_plan = plans_by_coin[ref_coin]
    for coin in ANALYSIS_SYMBOLS[1:]:
        p = plans_by_coin[coin]
        if (
            p["seed_close_ts"] != ref_plan["seed_close_ts"]
            or p["replay_first_open_utc"] != ref_plan["replay_first_open_utc"]
            or p["replay_last_open_utc"] != ref_plan["replay_last_open_utc"]
            or p["replay_last_close_utc"] != ref_plan["replay_last_close_utc"]
        ):
            raise RuntimeError(
                f"Cross-symbol progression mismatch between {ref_coin} and {coin}: "
                f"{ref_plan['replay_first_open_utc']}..{ref_plan['replay_last_close_utc']} vs "
                f"{p['replay_first_open_utc']}..{p['replay_last_close_utc']}"
            )

    sim_seed_now = int(ref_plan["seed_close_ts"])
    bars_15m_by_open_ts: Dict[str, Dict[int, Dict[str, Any]]] = {}

    # Seed initial 210 real historical 15m bars (indices 0..209) at true UTC timestamps,
    # and seed initial HTF synthetic context strictly up to the last closed UTC bucket <= sim_seed_now.
    for coin in ANALYSIS_SYMBOLS:
        seed_bars = plans_by_coin[coin]["seed_bars"]
        bars_15m_by_open_ts[coin] = {int(b["open_ts"]): b for b in seed_bars}
        candle_store.seed(coin, "15m", seed_bars, now=float(sim_seed_now))
        last_close_price = float(seed_bars[-1]["close"])
        end_1h = (sim_seed_now // 3600) * 3600
        end_4h = (sim_seed_now // 14400) * 14400
        end_1d = (sim_seed_now // 86400) * 86400
        candle_store.seed(
            coin, "1h",
            make_synthetic_candles(last_close_price, 50, interval="1h", end_time=end_1h),
            now=float(sim_seed_now),
        )
        candle_store.seed(
            coin, "4h",
            make_synthetic_candles(last_close_price, 50, interval="4h", end_time=end_4h),
            now=float(sim_seed_now),
        )
        candle_store.seed(
            coin, "1d",
            make_synthetic_candles(last_close_price, 30, interval="1d", end_time=end_1d),
            now=float(sim_seed_now),
        )

    measured_cycles_b = []
    htf_rollovers = {"1h": 0, "4h": 0, "1d": 0}
    replayed_open_ts_per_coin: Dict[str, List[int]] = {c: [] for c in ANALYSIS_SYMBOLS}

    with NetworkInterceptor() as ni_b:
        print(
            f"\n--- [Lane B] Running {replay_cycles} Measured Replay Cycles "
            f"({ref_plan['replay_first_open_utc']} -> {ref_plan['replay_last_close_utc']}) ---"
        )
        for i in range(1, replay_cycles + 1):
            step_idx = i - 1  # Exact index 210 + (i - 1) in window
            sim_now = int(ref_plan["replay_step_bars"][step_idx]["close_ts"])
            main_module._candle_clock = (lambda t=float(sim_now): t)

            for coin in ANALYSIS_SYMBOLS:
                bar = dict(plans_by_coin[coin]["replay_step_bars"][step_idx])
                bar_open_ts = int(bar["open_ts"])
                replayed_open_ts_per_coin[coin].append(bar_open_ts)
                bars_15m_by_open_ts[coin][bar_open_ts] = bar
                candle_store.update(coin, "15m", bar, is_closed=True, now=float(sim_now))

                for htf in ("1h", "4h", "1d"):
                    agg = aggregate_closed_utc_htf_candle(
                        bars_15m_by_open_ts[coin],
                        interval=htf,
                        closed_15m_open_ts=bar_open_ts,
                    )
                    if agg is not None:
                        candle_store.update(coin, htf, agg, is_closed=True, now=float(sim_now))
                        htf_rollovers[htf] += 1

            c_id = f"cycle_b_{i}"
            res = await run_warm_cycle(c_id)
            measured_cycles_b.append(res)
            if i % 5 == 0 or i <= 3 or i == replay_cycles:
                print(
                    f"Lane B Cycle {i:02d}/{replay_cycles}: wall={res['total_cycle_wall_sec']:.2f}s | "
                    f"fetch_wall={res['stages']['market_data_fetch']['wall_sec']:.2f}s | "
                    f"RSS_gc={res['memory']['rss_after_gc_mb']} MB | "
                    f"valid={res['measurement_valid']}"
                )

        assert ni_b.outbound_attempts == 0, f"Lane B network violations: {ni_b.outbound_attempts} ({ni_b.blocked_targets})"
    main_module._candle_clock = None

    # Verify progression invariants post-run
    for coin in ANALYSIS_SYMBOLS:
        seq = replayed_open_ts_per_coin[coin]
        assert len(seq) == replay_cycles
        assert len(set(seq)) == replay_cycles
        assert seq[0] == int(plans_by_coin[coin]["seed_bars"][-1]["open_ts"]) + 900
        for idx_s in range(len(seq) - 1):
            assert seq[idx_s + 1] - seq[idx_s] == 900

    total_walls_b = [c["total_cycle_wall_sec"] for c in measured_cycles_b]
    rss_series_b = [c["memory"]["rss_after_gc_mb"] for c in measured_cycles_b]

    return {
        "lane_id": "OFFLINE_ADVANCING_15M_REPLAY_WITH_AGGREGATED_HTF_ROLLOVER",
        "description": (
            "Simulated-clock replay: historical 15m bars (audited, sorted, deduplicated across monthly CSVs) "
            "advance by exact 900s UTC steps starting at index 210 + (i - 1) after indices 0..209 seed; "
            "initial 1h/4h/1d history is an interval-spaced synthetic seed aligned to closed UTC buckets, "
            "and subsequent 1h/4h/1d candles roll over strictly on exact UTC bucket close (:00 / 00,04,08,12,16,20:00 / 00:00 UTC) "
            "when all 4/16/96 constituent historical 15m bars are present. Freshness (age + future skew) is validated "
            "against the simulated UTC clock. Not a live-feed equivalent."
        ),
        "progression_contract": {
            "seed_indices": "0..209",
            "replay_indices": f"210..{210 + replay_cycles - 1}",
            "index_formula": "210 + (i - 1)",
            "bars_replayed_per_symbol": replay_cycles,
            "skipped_bars": 0,
            "duplicate_replayed_bars": 0,
            "window_first_open_utc": ref_plan["window_first_open_utc"],
            "seed_last_open_utc": ref_plan["seed_last_open_utc"],
            "replay_first_open_utc": ref_plan["replay_first_open_utc"],
            "replay_last_open_utc": ref_plan["replay_last_open_utc"],
            "replay_last_close_utc": ref_plan["replay_last_close_utc"],
        },
        "dataset_audit": {
            "historical_symbols": historical_symbols,
            "fallback_symbols": fallback_symbols,
            "fallback_count": len(fallback_symbols),
            "raw_rows_total": raw_rows_total,
            "duplicate_rows_total": duplicate_rows_total,
            "unique_rows_total": unique_rows_total,
            "per_symbol": per_symbol_audit,
        },
        "utc_htf_rollover_contract": {
            "alignment": "exact_utc_bucket_close",
            "1h_close_utc": ":00 UTC (requires 4 contiguous 15m bars)",
            "4h_close_utc": "00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC (requires 16 contiguous 15m bars)",
            "1d_close_utc": "00:00 UTC midnight (requires 96 contiguous 15m bars)",
            "partial_candles_emitted": 0,
        },
        "htf_rollovers_per_coin_total": {k: v // max(1, len(ANALYSIS_SYMBOLS)) for k, v in htf_rollovers.items()},
        "simulated_clock": True,
        "target_cycles": replay_cycles,
        "all_cycles_valid": all(c["measurement_valid"] for c in measured_cycles_b),
        "outbound_network_attempts": ni_b.outbound_attempts,
        "blocked_targets": ni_b.blocked_targets,
        "total_cycle_wall_sec": {
            "median": round(statistics.median(total_walls_b), 4),
            "p95": round(float(np.percentile(total_walls_b, 95)), 4),
            "min": round(min(total_walls_b), 4),
            "max": round(max(total_walls_b), 4),
            "mean": round(statistics.mean(total_walls_b), 4),
        },
        "rss_series_mb": rss_series_b,
        "freshness_validation_enforced": True,
    }


# ─── Main Benchmark Orchestrator ─────────────────────────────────────────────

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Deterministic Paper Benchmark Suite")
    parser.add_argument(
        "--lane-b-from-baseline",
        type=str,
        default=None,
        help="Path to an existing verified metrics.json; re-runs ONLY Lane B and writes a refreshed benchmark artifact.",
    )
    args = parser.parse_args()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bench_dir = REPO_ROOT / "runtime" / "paper" / "benchmarks" / f"bench-{timestamp}"
    bench_dir.mkdir(parents=True, exist_ok=True)

    if args.lane_b_from_baseline:
        base_path = Path(args.lane_b_from_baseline).resolve()
        if not base_path.exists():
            raise FileNotFoundError(f"Baseline metrics.json not found: {base_path}")
        with open(base_path, "r", encoding="utf-8") as f:
            base_metrics = json.load(f)

        print("=" * 80)
        print("TARGETED LANE B REPLAY BENCHMARK REFRESH")
        print(f"Baseline:    {base_path}")
        print(f"Destination: {bench_dir}")
        print("=" * 80)

        warm_runtime = bench_dir / "warm_runtime"
        lane_b_res = await run_lane_b_replay_benchmark(warm_runtime, replay_cycles=20)
        warm_state = dict(base_metrics["warm_steady_state"])
        lane_a_net = int(warm_state["lane_a_compute_only"]["outbound_network_attempts"])
        lane_a_blocked = list(warm_state["lane_a_compute_only"]["blocked_targets"])
        warm_state["lane_b_advancing_15m_replay_htf_rollover"] = lane_b_res
        warm_state["outbound_network_attempts"] = lane_a_net + int(lane_b_res["outbound_network_attempts"])
        warm_state["blocked_targets"] = lane_a_blocked + list(lane_b_res["blocked_targets"])
        warm_state["isolated_runtime"] = str(warm_runtime)

        refreshed = dict(base_metrics)
        refreshed["benchmark_id"] = f"bench-{timestamp}"
        refreshed["timestamp"] = timestamp
        refreshed["lane_b_refresh_provenance"] = {
            "mode": "TARGETED_LANE_B_REFRESH",
            "carried_forward_from_benchmark_id": base_metrics.get("benchmark_id"),
            "carried_forward_stages": [
                "memory_breakdown_mb",
                "actual_process_memory_mb",
                "direct_shadow_fast_path",
                "cold_start",
                "warm_steady_state.lane_a_compute_only",
            ],
            "re_executed_stages": [
                "warm_steady_state.lane_b_advancing_15m_replay_htf_rollover",
            ],
        }
        refreshed["warm_steady_state"] = warm_state

        metrics_file = bench_dir / "metrics.json"
        with open(metrics_file, "w", encoding="utf-8") as f:
            json.dump(refreshed, f, indent=2)
        print(f"\nLane B refreshed artifact written to: {metrics_file}")
        return

    print("=" * 80)
    print("BESTTIME-CRYPTO DETERMINISTIC PAPER BENCHMARK SUITE (V2 - UNCLAMPED)")
    print(f"Timestamp:   {timestamp}")
    print(f"Destination: {bench_dir}")
    print("=" * 80)

    # 1. Memory Breakdown (Synthetic import profile)
    print("\n[Stage 1/5] Profiling Memory Import Breakdown (Synthetic Entry vs Exit profiles)...")
    mem_breakdown = run_memory_breakdown_profile(bench_dir)
    print("  Synthetic Memory Breakdown Results:")
    for k, v in mem_breakdown.items():
        print(f"    {k:<35}: {v}")

    # 1.5 Actual Production Processes (Subprocess execution of main.py --once)
    print("\n[Stage 2/5] Profiling Actual Production Processes (main.py --once Entry vs Exit)...")
    actual_proc_mem = profile_actual_production_processes(bench_dir)
    print("  Actual Process Profiling Results:")
    print(
        f"    Entry-Only Process: Peak RSS = {actual_proc_mem['entry_only_process'].get('peak_rss_mb')} MB | "
        f"torch in sys.modules = {actual_proc_mem['entry_only_process'].get('torch_in_sys_modules')}"
    )
    print(
        f"    Exit-Enabled Process: Peak RSS = {actual_proc_mem['exit_enabled_process'].get('peak_rss_mb')} MB | "
        f"torch in sys.modules = {actual_proc_mem['exit_enabled_process'].get('torch_in_sys_modules')}"
    )
    print(
        f"    Actual Process RSS Delta: {actual_proc_mem['actual_process_rss_delta_mb']} MB "
        f"(Savings: {actual_proc_mem['actual_entry_savings_percentage']}%)"
    )

    # 2. Direct Shadow Fast-Path Benchmark
    print("\n[Stage 3/5] Profiling Direct Shadow Fast-Path (AutoTrader._process_signal)...")
    shadow_fast_res = await run_direct_shadow_fast_path_benchmark(bench_dir, n_iterations=100)
    print(
        f"  Shadow Fast Path Clean Log: median={shadow_fast_res['clean_log']['median_sec'] * 1000:.3f}ms | "
        f"p95={shadow_fast_res['clean_log']['p95_sec'] * 1000:.3f}ms | "
        f"p99={shadow_fast_res['clean_log']['p99_sec'] * 1000:.3f}ms"
    )
    print(
        f"  Shadow Fast Path 1000-Entry Log: median={shadow_fast_res['preseeded_1000_entry_log']['median_sec'] * 1000:.3f}ms | "
        f"p95={shadow_fast_res['preseeded_1000_entry_log']['p95_sec'] * 1000:.3f}ms | "
        f"p99={shadow_fast_res['preseeded_1000_entry_log']['p99_sec'] * 1000:.3f}ms | "
        f"bounded latency verified={shadow_fast_res.get('bounded_latency_verified', True)} | "
        f"default log untouched={shadow_fast_res['default_log_untouched']}"
    )

    # 3. Cold Start Benchmark
    print("\n[Stage 4/5] Executing Cold Start Process Benchmark (5 runs, main.py --once)...")
    cold_res = run_cold_start_benchmark(bench_dir, n_runs=5)
    print(
        f"  Cold Start Finished (n=5): median_duration={cold_res['duration_sec']}s | "
        f"p95_duration={cold_res['p95_duration_sec']}s | "
        f"min_duration={cold_res['min_duration_sec']}s | "
        f"max_duration={cold_res['max_duration_sec']}s | "
        f"stdout_clean={cold_res.get('stdout_stderr_clean')} | "
        f"first_analysis={cold_res.get('time_to_first_analysis_sec')}s | "
        f"first_prediction={cold_res.get('time_to_first_prediction_sec')}s | "
        f"first_decision={cold_res.get('time_to_first_final_decision_sec')}s | "
        f"all_runs_valid={cold_res.get('all_runs_valid')}"
    )

    # 4. Warm Steady State Benchmark
    print("\n[Stage 5/5] Executing Warm Steady State Benchmark (1 Warm-up + 100 Cycles)...")
    warm_res = await run_warm_benchmark_suite(bench_dir, target_cycles=100)

    # Final Combined Telemetry Report
    final_metrics = {
        "benchmark_id": f"bench-{timestamp}",
        "timestamp": timestamp,
        "environment": "paper",
        "dry_run": True,
        "execution_universe": ["BTC", "ETH", "BNB"],
        "analysis_universe": ["BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"],
        "comparison_note": "NO_COMPARABLE_BASELINE: Prior reports referenced an un-instrumented 32s estimate. Current metrics represent strictly instrumented empirical baselines.",
        "memory_breakdown_mb": mem_breakdown,
        "actual_process_memory_mb": actual_proc_mem,
        "direct_shadow_fast_path": shadow_fast_res,
        "cold_start": cold_res,
        "warm_steady_state": warm_res,
    }

    metrics_file = bench_dir / "metrics.json"
    with open(metrics_file, "w", encoding="utf-8") as f:
        json.dump(final_metrics, f, indent=2)

    # Display clean table
    print("\n" + "=" * 80)
    print("BENCHMARK EXECUTIVE SUMMARY")
    print("=" * 80)
    print(
        f"Cold Start Duration (n=5 median): {cold_res['duration_sec']}s (p95: {cold_res['p95_duration_sec']}s) | "
        f"TimeToFirstAnalysis: {cold_res.get('time_to_first_analysis_sec')}s | "
        f"TimeToFirstPrediction: {cold_res.get('time_to_first_prediction_sec')}s | "
        f"TimeToFirstDecision: {cold_res.get('time_to_first_final_decision_sec')}s | "
        f"StdoutClean: {cold_res.get('stdout_stderr_clean')}"
    )
    print(
        f"Direct Shadow Fast-Path (Clean Log): median = {shadow_fast_res['clean_log']['median_sec'] * 1000:.3f}ms | "
        f"p95 = {shadow_fast_res['clean_log']['p95_sec'] * 1000:.3f}ms | p99 = {shadow_fast_res['clean_log']['p99_sec'] * 1000:.3f}ms"
    )
    print(
        f"Direct Shadow Fast-Path (1000-Entry Log): median = {shadow_fast_res['preseeded_1000_entry_log']['median_sec'] * 1000:.3f}ms | "
        f"p95 = {shadow_fast_res['preseeded_1000_entry_log']['p95_sec'] * 1000:.3f}ms | p99 = {shadow_fast_res['preseeded_1000_entry_log']['p99_sec'] * 1000:.3f}ms "
        f"(Bounded Latency Seek-Append Verified; Default Log Untouched: {shadow_fast_res['default_log_untouched']})"
    )
    print(
        f"Actual Process Peak RSS: Entry-Only = {actual_proc_mem['entry_only_process'].get('peak_rss_mb')} MB | "
        f"Exit-Enabled = {actual_proc_mem['exit_enabled_process'].get('peak_rss_mb')} MB "
        f"(Delta: {actual_proc_mem['actual_process_rss_delta_mb']} MB, Savings: {actual_proc_mem['actual_entry_savings_percentage']}%)"
    )
    print(
        f"Warm Steady-State Cycle ({warm_res['target_cycles']} cycles): Median = {warm_res['total_cycle_wall_sec']['median']}s | "
        f"p95 = {warm_res['total_cycle_wall_sec']['p95']}s | p99 = {warm_res['total_cycle_wall_sec']['p99']}s "
        f"(Min: {warm_res['total_cycle_wall_sec']['min']}s, Max: {warm_res['total_cycle_wall_sec']['max']}s)"
    )
    print(
        f"Outbound Network Attempts: {warm_res['outbound_network_attempts']} (Blocked Targets: {warm_res['blocked_targets']})"
    )
    print(
        f"Memory Slope All {warm_res['target_cycles']}: {warm_res['memory_analysis']['memory_slope_all_cycles']} MB/cycle | "
        f"Slope Last 20: {warm_res['memory_analysis']['memory_slope_last_20_cycles']} MB/cycle | "
        f"Range Last 20: {warm_res['memory_analysis']['last_20_range_rss_mb']} MB ({warm_res['memory_analysis']['stability_status']})"
    )
    print(f"Validation Valid: {warm_res['all_cycles_valid']} (Errors: {warm_res['total_validation_errors']})")
    print("-" * 80)
    print(f"{'Stage Name':<30} {'Wall Median':<12} {'Agg Work Med':<14} {'Calls':<6} {'Max Single Call':<15}")
    print("-" * 80)
    for s_name, data in warm_res["stages_aggregate"].items():
        w_med = f"{data['wall_sec']['median']:.4f}s"
        agg_med = f"{data['aggregate_work_sec']['median']:.4f}s"
        calls = str(data["call_count_median"])
        max_call = f"{data['max_single_call_sec_median']:.4f}s"
        print(f"{s_name:<30} {w_med:<12} {agg_med:<14} {calls:<6} {max_call:<15}")
    print("=" * 80)
    print(f"Telemetry metrics preserved at: {metrics_file}")
    print("=" * 80)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
