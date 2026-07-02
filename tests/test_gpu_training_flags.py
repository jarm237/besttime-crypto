import argparse
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_train_many_coins_uses_gpu_flags_for_training(monkeypatch):
    train_many_coins = load_module("train_many_coins", ROOT / "scripts" / "train_many_coins.py")

    class DummyProc:
        def poll(self):
            return 0

    captured = {}

    def fake_popen(cmd, cwd=None, env=None):
        return DummyProc()

    def fake_run(cmd, cwd=None, check=False):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["check"] = check
        return 0

    monkeypatch.setattr(train_many_coins, "parse_args", lambda: argparse.Namespace(
        coins="BTC,ETH",
        jobs=1,
        months="april_2025",
        train=True,
        gpu=True,
        device_id=2,
    ))
    monkeypatch.setattr(train_many_coins.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(train_many_coins.subprocess, "run", fake_run)

    train_many_coins.main()

    assert captured["cmd"][0].endswith("python.exe") or "python" in captured["cmd"][0]
    assert str(ROOT / "scripts" / "build_and_train.py") in captured["cmd"][1]
    assert "--skip-build" in captured["cmd"]
    assert "--use-gpu" in captured["cmd"]
    assert "--device-id" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--device-id") + 1] == "2"
