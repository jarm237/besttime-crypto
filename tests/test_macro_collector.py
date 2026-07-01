import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from btc_scraper.collectors import macro_collector


class FakeSeries:
    def __init__(self, values):
        self.values = values

    @property
    def iloc(self):
        return self

    def __getitem__(self, idx):
        if idx == -1:
            return self.values[-1]
        return self.values[idx]


class FakeHistory(dict):
    empty = False


class DummyTicker:
    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, period="2d"):
        if self.symbol == "DX-Y.NYB":
            return FakeHistory({"Close": FakeSeries([100.5, 101.2])})
        if self.symbol == "^VIX":
            return FakeHistory({"Close": FakeSeries([18.1, 19.0])})
        if self.symbol == "^TNX":
            return FakeHistory({"Close": FakeSeries([4.4, 4.6])})
        return FakeHistory({"Close": FakeSeries([0.0, 0.0])})


class DummyYFModule:
    @staticmethod
    def Ticker(symbol):
        return DummyTicker(symbol)


def test_fetch_and_save_macro_writes_json(tmp_path, monkeypatch):
    output_path = tmp_path / "macro_state.json"
    monkeypatch.setattr(macro_collector, "DATA_FILE", str(output_path))
    monkeypatch.setattr(macro_collector, "yf", DummyYFModule())

    result = macro_collector.fetch_and_save_macro()

    assert result["DXY"] == 101.2
    assert result["VIX"] == 19.0
    assert result["BondYield"] == 4.6

    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted["DXY"] == 101.2
    assert persisted["timestamp"]


def test_load_macro_state_reads_existing_file(tmp_path, monkeypatch):
    output_path = tmp_path / "macro_state.json"
    output_path.write_text(json.dumps({"DXY": 103.0, "VIX": 21.0, "BondYield": 4.2}), encoding="utf-8")

    monkeypatch.setattr(macro_collector, "DATA_FILE", str(output_path))

    loaded = macro_collector.load_macro_state()

    assert loaded["DXY"] == 103.0
    assert loaded["VIX"] == 21.0
    assert loaded["BondYield"] == 4.2
