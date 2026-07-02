import importlib.util
import json
from pathlib import Path


def load_signal_tracker_module():
    module_path = Path(__file__).resolve().parents[1] / "btc_scraper" / "analysis" / "signal_tracker.py"
    spec = importlib.util.spec_from_file_location("signal_tracker_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_register_signal_stores_current_price(tmp_path: Path):
    signal_tracker_module = load_signal_tracker_module()
    SignalTracker = signal_tracker_module.SignalTracker
    tracker = SignalTracker(filepath=str(tmp_path / "tracked_signals.json"))

    tracker.register_signal(
        coin="NEAR",
        signal_time="2026-07-02 11:00",
        signal="BUY (Crossover)",
        entry=1.9070,
        tp_sl={"sl": 1.7219, "tp1": 2.2155, "tp2": 2.5240},
        reason="test reason",
        current_price=1.9070,
    )

    saved = tracker.signals["NEAR"][0]
    assert saved["current_price"] == 1.9070

    persisted = json.loads((tmp_path / "tracked_signals.json").read_text(encoding="utf-8"))
    assert persisted["NEAR"][0]["current_price"] == 1.9070
