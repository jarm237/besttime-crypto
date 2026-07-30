from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from btc_scraper.analysis.core import calculate_tp_sl
from btc_scraper.backtesting.config import BacktestConfig
from btc_scraper.backtesting.engine import atr_percent_to_price_distance
from btc_scraper.core.world_state import MarketRegime, risk_appetite_from_signal
from btc_scraper.feature_engineering.regime_features import RegimeFeatureBuilder
from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine
from btc_scraper.ml_engine.signal_score import score_signal
from btc_scraper.regime.config import (
    RegimeConfigError,
    atomic_write_regime_config,
    compute_regime_config_sha256,
    default_regime_config,
    load_regime_config,
    load_runtime_regime_config,
    regime_decision_weight_enabled,
    regime_position_sizing_enabled,
    regime_tp_sl_enabled,
    resolve_regime_config_path,
)
from btc_scraper.regime.contract import (
    MappingQuality,
    RegimeDirection,
    RegimeFamily,
    RegimeSnapshot,
    map_legacy_regime,
    snapshot_from_legacy,
)
from btc_scraper.regime.market_regime import (
    _classify_regime,
    calculate_adx,
    detect_regime,
    regime_from_values,
    stabilize_regime_sequence,
)
from btc_scraper.regime.regime_tuner import (
    RegimeTunerConfig,
    tune_regime_multipliers,
    walk_forward_split,
    write_immutable_tuning_artifact,
)


def _ohlc_frame(rows: int = 220, *, datetime_index: bool = False) -> pd.DataFrame:
    close = pd.Series([100.0 + index * 0.1 + math.sin(index) for index in range(rows)])
    frame = pd.DataFrame({"open": close - 0.1, "high": close + 1.0, "low": close - 1.0, "close": close})
    if datetime_index:
        frame.index = pd.date_range("2026-01-01", periods=rows, freq="15min", tz="UTC")
    return frame


def test_atr_percent_uses_atr_threshold_not_adx_threshold():
    config = load_regime_config()
    result = _classify_regime(100, 90, 95, 92, 30, 0.8, config)
    assert result["regime"] == "BREAKOUT_BULL"
    config = {**config, "adx_threshold": 80.0, "strong_adx_threshold": 90.0}
    result = _classify_regime(100, 90, 95, 92, 10, 0.8, config)
    assert result["regime"] == "MEAN_REVERSION"


def test_atr_percent_units_are_consistent():
    assert atr_percent_to_price_distance(100.0, 0.84) == pytest.approx(0.84)
    assert regime_from_values(100, 90, 95, 92, 30, 0.8)["atr_percent"] == pytest.approx(0.8)


def test_adx_preserves_datetime_index():
    frame = _ohlc_frame(datetime_index=True)
    adx = calculate_adx(frame)
    assert adx.index.equals(frame.index)
    assert adx.notna().sum() > 0


def test_adx_range_and_datetime_index_match():
    plain = _ohlc_frame()
    dated = plain.copy()
    dated.index = pd.date_range("2026-01-01", periods=len(dated), freq="15min", tz="UTC")
    assert calculate_adx(plain).to_numpy() == pytest.approx(calculate_adx(dated).to_numpy(), nan_ok=True)


def test_insufficient_history_returns_explicit_unknown():
    result = detect_regime(_ohlc_frame(20))
    assert result["regime"] == "UNKNOWN"
    assert result["warmup_complete"] is False
    assert result["reason"] == "INSUFFICIENT_HISTORY"


def test_nan_tail_fails_visible():
    frame = _ohlc_frame()
    frame.loc[frame.index[-1], "close"] = float("nan")
    with pytest.raises(ValueError, match="INVALID_OHLC_VALUES"):
        detect_regime(frame)


def test_detector_is_deterministic():
    frame = _ohlc_frame()
    assert detect_regime(frame) == detect_regime(frame.copy())


def test_hysteresis_prevents_single_bar_flip():
    assert stabilize_regime_sequence(["RANGING", "RANGING", "BREAKOUT_BULL", "RANGING"], 3) == [
        "RANGING", "RANGING", "RANGING", "RANGING"
    ]


def test_minimum_regime_duration():
    candidates = ["RANGING", "BREAKOUT_BULL", "BREAKOUT_BULL", "BREAKOUT_BULL"]
    assert stabilize_regime_sequence(candidates, 3) == [
        "RANGING", "RANGING", "RANGING", "BREAKOUT_BULL"
    ]


def test_bull_bear_synthetic_symmetry():
    config = load_regime_config()
    bull = _classify_regime(110, 100, 105, 102, 30, 0.8, config)
    bear = _classify_regime(90, 100, 95, 98, 30, 0.8, config)
    assert bull["regime"] == "BREAKOUT_BULL"
    assert bear["regime"] == "BREAKOUT_BEAR"
    assert bull["confidence"] == bear["confidence"]


def test_invalid_time_order_fails_visible():
    frame = _ohlc_frame()
    frame["time"] = pd.date_range("2026-01-01", periods=len(frame), freq="15min", tz="UTC")
    frame.loc[1, "time"], frame.loc[2, "time"] = frame.loc[2, "time"], frame.loc[1, "time"]
    with pytest.raises(ValueError, match="NON_MONOTONIC_TIME"):
        detect_regime(frame, source_timeframe="15m")


def test_unsupported_timeframe_fails_visible():
    with pytest.raises(ValueError, match="UNSUPPORTED_TIMEFRAME"):
        detect_regime(_ohlc_frame(), source_timeframe="13m")


@pytest.mark.parametrize(
    ("regime", "signal", "expected"),
    [
        ("STRONG_TREND_BULL", "BUY", 0.9),
        ("STRONG_TREND_BULL", "SELL", 0.1),
        ("STRONG_TREND_BEAR", "BUY", 0.1),
        ("STRONG_TREND_BEAR", "SELL", 0.9),
        ("PANIC_SELL", "BUY", 0.05),
        ("PANIC_SELL", "SELL", 0.75),
        ("PUMP_RISK", "BUY", 0.1),
        ("PUMP_RISK", "SELL", 0.6),
        ("RANGING", "BUY", 0.5),
        ("COMPRESSION", "SELL", 0.5),
    ],
)
def test_every_regime_has_exact_direction_truth_table(regime, signal, expected):
    assert MetaDecisionEngine()._regime_support({"regime": regime, "signal": signal}) == expected


def test_regime_observe_mode_zeroes_decision_weight(monkeypatch):
    monkeypatch.setenv("REGIME_RUNTIME_ENFORCEMENT_MODE", "observe")
    monkeypatch.setenv("REGIME_DECISION_WEIGHT_ENABLED", "true")
    engine = MetaDecisionEngine()
    assert engine.proposed_weights["regime"] == 0.15
    assert engine.weights["regime"] == 0.0
    bull = engine.compute_posterior(0.6, 0.5, 0.9, 0.5)
    bear = engine.compute_posterior(0.6, 0.5, 0.1, 0.5)
    assert bull == bear


def test_shadow_mode_cannot_enable_live_effects(monkeypatch):
    monkeypatch.setenv("REGIME_RUNTIME_ENFORCEMENT_MODE", "shadow_effect")
    monkeypatch.setenv("REGIME_DECISION_WEIGHT_ENABLED", "true")
    monkeypatch.setenv("REGIME_POSITION_SIZING_ENABLED", "true")
    monkeypatch.setenv("REGIME_TP_SL_ENABLED", "true")
    assert regime_decision_weight_enabled() is False
    assert regime_position_sizing_enabled() is False
    assert regime_tp_sl_enabled() is False


def test_enforcement_requires_promotion_and_exactly_one_effect(monkeypatch):
    monkeypatch.setenv("REGIME_RUNTIME_ENFORCEMENT_MODE", "enforce")
    monkeypatch.setenv("REGIME_DECISION_WEIGHT_ENABLED", "true")
    assert regime_decision_weight_enabled() is False
    monkeypatch.setenv("REGIME_PROMOTION_APPROVED", "true")
    assert regime_decision_weight_enabled() is True
    monkeypatch.setenv("REGIME_POSITION_SIZING_ENABLED", "true")
    assert regime_decision_weight_enabled() is False
    assert regime_position_sizing_enabled() is False


def test_regime_observe_mode_does_not_change_tp_sl(monkeypatch):
    monkeypatch.setenv("REGIME_RUNTIME_ENFORCEMENT_MODE", "observe")
    monkeypatch.setenv("REGIME_TP_SL_ENABLED", "true")
    common = dict(
        close=100.0,
        signal="BUY",
        atr=1.0,
        support=0.0,
        resistance=0.0,
        bb_upper=0.0,
        bb_middle=0.0,
        bb_lower=0.0,
    )
    baseline = calculate_tp_sl(**common)
    regime = calculate_tp_sl(**common, regime="BREAKOUT_BULL")
    assert (regime["sl"], regime["tp1"], regime["tp2"]) == (
        baseline["sl"],
        baseline["tp1"],
        baseline["tp2"],
    )
    assert regime["applied_regime_tp_scale"] == 1.0
    assert regime["regime_effect_reason"] == "REGIME_OBSERVE_ONLY"


def test_regime_observe_mode_does_not_change_position_size(monkeypatch):
    from btc_scraper.ml_engine import signal_score as module

    monkeypatch.setenv("REGIME_RUNTIME_ENFORCEMENT_MODE", "observe")
    monkeypatch.setenv("REGIME_POSITION_SIZING_ENABLED", "true")
    monkeypatch.setattr(
        module,
        "_get_cached_risk_metrics",
        lambda: {"risk_multiplier": 1.0, "blocked": False, "drawdown_pct": 0.0},
    )
    module._REGIME_MULTIPLIERS = None
    result = score_signal(
        "BUY",
        {"regime": "STRONG_TREND_BEAR", "strategy": "EMA_Crossover"},
        {"disable_ml": True},
    )
    assert result["proposed_regime_multiplier"] == 0.25
    assert result["applied_regime_multiplier"] == 1.0
    assert result["regime_effect_reason"] == "REGIME_OBSERVE_ONLY"
    assert result["regime_snapshot"]["direction"] == "BEAR"


def test_canonical_snapshot_serialization_round_trip():
    snapshot = snapshot_from_legacy(
        "STRONG_TREND_BEAR",
        confidence=0.82,
        config_sha256=compute_regime_config_sha256(),
    )
    assert RegimeSnapshot.from_dict(snapshot.to_dict()) == snapshot


def test_lossy_mapping_is_marked():
    _, mapped = map_legacy_regime("STRONG_TREND")
    assert mapped.quality is MappingQuality.LOSSY
    assert mapped.family is RegimeFamily.TREND
    assert mapped.direction is RegimeDirection.UNKNOWN


def test_world_state_does_not_default_to_risk_off():
    assert risk_appetite_from_signal(None) is MarketRegime.UNKNOWN
    assert risk_appetite_from_signal("NEUTRAL (BULLISH)") is MarketRegime.TRANSITIONING
    assert risk_appetite_from_signal("BUY (Crossover)") is MarketRegime.RISK_ON
    assert risk_appetite_from_signal("SELL (Break)") is MarketRegime.RISK_OFF


def test_all_components_resolve_same_config_path():
    from btc_scraper.regime import market_regime
    from btc_scraper.ui import dashboard

    assert resolve_regime_config_path() == dashboard.REGIME_CONFIG
    assert market_regime._load_config() == load_regime_config()


def test_missing_config_fails_closed(tmp_path):
    with pytest.raises(RegimeConfigError, match="REGIME_CONFIG_MISSING"):
        load_regime_config(path=tmp_path / "missing.json")


def test_missing_config_degrades_shadow_but_enforce_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("REGIME_CONFIG_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setenv("REGIME_RUNTIME_ENFORCEMENT_MODE", "shadow_effect")
    degraded = load_runtime_regime_config()
    assert degraded["_config_health"] == "DEGRADED_CONFIG_UNAVAILABLE"
    assert regime_decision_weight_enabled() is False
    monkeypatch.setenv("REGIME_RUNTIME_ENFORCEMENT_MODE", "enforce")
    with pytest.raises(RegimeConfigError, match="REGIME_CONFIG_MISSING"):
        load_runtime_regime_config()


def test_config_write_is_atomic_and_hash_changes(tmp_path):
    path = tmp_path / "regime.json"
    config = default_regime_config()
    _, first_hash = atomic_write_regime_config(config, path=path)
    config["adx_threshold"] = 26.0
    _, second_hash = atomic_write_regime_config(config, path=path)
    assert first_hash != second_hash
    assert not list(tmp_path.glob("*.tmp"))
    audit = tmp_path / "regime_config_audit.jsonl"
    assert audit.exists()
    records = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert [record["config_sha256"] for record in records] == [first_hash, second_hash]


def test_transition_probability_is_grouped_by_coin():
    frame = pd.DataFrame(
        [
            {"coin": "B", "entry_time": "2026-01-01 00:15", "regime": "BEARISH"},
            {"coin": "A", "entry_time": "2026-01-01 00:15", "regime": "BEARISH"},
            {"coin": "B", "entry_time": "2026-01-01 00:00", "regime": "BULLISH"},
            {"coin": "A", "entry_time": "2026-01-01 00:00", "regime": "BULLISH"},
        ]
    )
    result = RegimeFeatureBuilder().build(frame)
    first_rows = result.groupby("coin", sort=False).head(1)
    assert set(first_rows["regime_transition_probability"]) == {0.0}
    assert list(result["coin"]) == ["A", "A", "B", "B"]
    assert list(result["regime_duration_bars"]) == [1, 1, 1, 1]


def test_signal_confidence_is_not_regime_confidence():
    frame = pd.DataFrame(
        [{"coin": "BTC", "entry_time": "2026-01-01", "regime": "RANGING", "confidence": 0.99}]
    )
    result = RegimeFeatureBuilder().build(frame)
    assert pd.isna(result.iloc[0]["regime_confidence"])
    assert result.iloc[0]["regime_confidence_missing"] == 1


def test_unknown_regime_remains_unknown():
    frame = pd.DataFrame([{"coin": "BTC", "entry_time": "2026-01-01"}])
    result = RegimeFeatureBuilder().build(frame)
    assert result.iloc[0]["regime"] == "UNKNOWN"
    assert result.iloc[0]["regime_unknown"] == 1


def test_position_persists_immutable_entry_regime(monkeypatch):
    from btc_scraper.trading import position_tracker

    class DummyCollection:
        def __init__(self):
            self.document = None

        def find_one(self, query, projection=None):
            if self.document and self.document.get("id") == query.get("id"):
                return dict(self.document)
            return None

        def insert_one(self, document):
            self.document = dict(document)

    collection = DummyCollection()
    monkeypatch.setattr(position_tracker, "positions_col", collection)
    snapshot = snapshot_from_legacy(
        "STRONG_TREND_BEAR",
        confidence=0.8,
        config_sha256=compute_regime_config_sha256(),
    ).to_dict()
    position = position_tracker.add_position(
        "BTC",
        100.0,
        position_id="position-regime-1",
        regime_snapshot=snapshot,
    )
    assert position["entry_regime_snapshot"] == snapshot
    assert position["entry_regime_direction"] == "BEAR"

    conflicting = snapshot_from_legacy(
        "STRONG_TREND_BULL",
        confidence=0.8,
        config_sha256=compute_regime_config_sha256(),
    ).to_dict()
    with pytest.raises(ValueError, match="QUARANTINED"):
        position_tracker.add_position(
            "BTC",
            100.0,
            position_id="position-regime-1",
            regime_snapshot=conflicting,
        )


def test_adaptive_logger_preserves_explicit_snapshot(monkeypatch):
    from btc_scraper.ml_engine import adaptive_scoring

    saved = {}
    monkeypatch.setattr(adaptive_scoring, "_load_log", lambda: [])
    monkeypatch.setattr(adaptive_scoring, "_save_log", lambda records: saved.update(record=records[-1]))
    snapshot = snapshot_from_legacy(
        "RANGING",
        confidence=0.7,
        config_sha256=compute_regime_config_sha256(),
    ).to_dict()
    adaptive_scoring.log_trade_outcome(
        {
            "coin": "BTC",
            "pnl_pct": 1.0,
            "result": "WIN",
            "entry_regime_snapshot": snapshot,
            "entry_regime_lineage_status": "NATIVE_RUNTIME",
        }
    )
    assert saved["record"]["regime"] == "RANGING"
    assert saved["record"]["entry_regime_snapshot"] == snapshot
    assert saved["record"]["regime_lineage_status"] == "NATIVE_RUNTIME"


def test_same_candle_policy_is_explicit():
    assert BacktestConfig().same_candle_policy == "CONSERVATIVE_SL_FIRST"
    assert BacktestConfig.from_dict({"same_candle_policy": "AMBIGUOUS_EXCLUDE"}).same_candle_policy == "AMBIGUOUS_EXCLUDE"
    with pytest.raises(ValueError):
        BacktestConfig.from_dict({"same_candle_policy": "UNSPECIFIED"})


def test_tuner_uses_walk_forward_and_low_sample_defaults_to_one():
    records = [
        {
            "entry_time": f"2026-01-{day:02d}T00:00:00Z",
            "regime": "STRONG_TREND_BULL",
            "pnl_pct": 1.0 if day % 2 else -0.5,
        }
        for day in range(1, 21)
    ]
    config = RegimeTunerConfig(min_samples_per_regime=30, bootstrap_samples=10)
    report = tune_regime_multipliers(records, config)
    proposal = report["proposals"]["STRONG_TREND_BULL"]
    assert proposal["selected_multiplier"] == 1.0
    assert proposal["status"] == "INSUFFICIENT_EVIDENCE"
    assert report["promotion_gate_passed"] is False

    frame = pd.DataFrame(records)
    splits = walk_forward_split(frame, RegimeTunerConfig())
    assert len(splits["train"]) < len(frame)
    assert len(splits["holdout"]) > 0


def test_tuning_artifact_is_immutable(tmp_path):
    report = {
        "created_at": "2026-07-30T00:00:00+00:00",
        "approval_status": "RESEARCH_ONLY",
    }
    write_immutable_tuning_artifact(report, tmp_path)
    with pytest.raises(FileExistsError):
        write_immutable_tuning_artifact(report, tmp_path)
