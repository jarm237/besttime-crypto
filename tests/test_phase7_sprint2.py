import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from btc_scraper.collectors.alternative_data import collect_alternative_data
from btc_scraper.collectors.binance_collector import BinanceCollector
from btc_scraper.collectors.defillama_collector import DefiLlamaCollector
from btc_scraper.collectors.fred_collector import FredCollector
from btc_scraper.collectors.yahoo_collector import YahooCollector


class Phase7Sprint2Tests(unittest.TestCase):
    def test_binance_collector_parses_funding_and_oi(self):
        fake_payload = [
            {"fundingRate": "0.0001"},
            {"openInterest": "12345"},
        ]

        with patch("btc_scraper.collectors.binance_collector._fetch_json", return_value=fake_payload):
            collector = BinanceCollector(output_path=str(Path(tempfile.gettempdir()) / "binance.json"))
            data = collector.collect(force=True)

        self.assertEqual(data["funding_rate"], 0.0001)
        self.assertEqual(data["open_interest"], 12345.0)

    def test_defillama_collector_parses_stablecoin_and_tvl(self):
        stable_payload = {
            "data": {
                "totalStablecoins": {"value": 250000000000},
            }
        }
        chains_payload = [{"tvlUsd": 60000000000}, {"tvlUsd": 90000000000}]
        protocols_payload = [{"tvlUsd": 50000000000}]

        with patch("btc_scraper.collectors.defillama_collector._fetch_json", side_effect=[stable_payload, chains_payload, protocols_payload]):
            collector = DefiLlamaCollector(output_path=str(Path(tempfile.gettempdir()) / "defillama.json"))
            data = collector.collect(force=True)

        self.assertEqual(data["stablecoin_supply"], 250000000000.0)
        self.assertEqual(data["stablecoin_supply_total"], 250000000000.0)
        self.assertEqual(data["chain_tvl"], 150000000000.0)
        self.assertEqual(data["protocol_tvl"], 50000000000.0)
        self.assertEqual(data["tvl"], 150000000000.0)

    def test_fred_collector_parses_macro_series(self):
        fake_payload = {
            "observations": [
                {"value": "4.25"},
                {"value": "4.3"},
            ]
        }

        with patch("btc_scraper.collectors.fred_collector._fetch_json", return_value=fake_payload):
            collector = FredCollector(output_path=str(Path(tempfile.gettempdir()) / "fred.json"))
            data = collector.collect(force=True)

        self.assertEqual(data["us10y"], 4.3)
        self.assertEqual(data["gold"], 0.0)

    def test_yahoo_collector_parses_macro_tickers(self):
        fake_hist = {
            "DXY": {"Close": [101.5]},
            "VIX": {"Close": [18.2]},
            "Gold": {"Close": [2030.0]},
        }

        with patch("btc_scraper.collectors.yahoo_collector._fetch_history", side_effect=lambda ticker, period: fake_hist[ticker]):
            collector = YahooCollector(output_path=str(Path(tempfile.gettempdir()) / "yahoo.json"))
            data = collector.collect(force=True)

        self.assertEqual(data["dxy"], 101.5)
        self.assertEqual(data["vix"], 18.2)
        self.assertEqual(data["gold"], 2030.0)

    def test_collect_alternative_data_merges_sprint2_features(self):
        def defillama_side_effect(*args, **kwargs):
            url = args[0] if args else None
            if url and url.endswith("/stablecoins"):
                return {"data": {"totalStablecoins": {"value": 123}}}
            if url and url.endswith("/chains"):
                return [{"tvlUsd": 300}, {"tvlUsd": 153}]
            if url and url.endswith("/protocols"):
                return [{"tvlUsd": 456}]
            return None

        with patch("btc_scraper.collectors.binance_collector._fetch_json", return_value=[{"fundingRate": "0.0002"}, {"openInterest": "999"}]), \
             patch("btc_scraper.collectors.defillama_collector._fetch_json", side_effect=defillama_side_effect), \
             patch("btc_scraper.collectors.fred_collector._fetch_json", return_value={"observations": [{"value": "4.1"}]}), \
             patch("btc_scraper.collectors.yahoo_collector._fetch_history", side_effect=lambda ticker, period: {"DXY": {"Close": [100.1]}, "VIX": {"Close": [20.1]}, "Gold": {"Close": [1900.0]}}[ticker]):
            payload = collect_alternative_data(output_path=str(Path(tempfile.gettempdir()) / "merged.json"), force=True)

        self.assertEqual(payload["funding_rate"], 0.0002)
        self.assertEqual(payload["open_interest"], 999.0)
        self.assertEqual(payload["stablecoin_supply"], 123.0)
        self.assertEqual(payload["stablecoin_supply_total"], 123.0)
        self.assertEqual(payload["chain_tvl"], 453.0)
        self.assertEqual(payload["protocol_tvl"], 456.0)
        self.assertEqual(payload["tvl"], 456.0)
        self.assertEqual(payload["dxy"], 100.1)
        self.assertEqual(payload["vix"], 20.1)
        self.assertEqual(payload["gold"], 1900.0)
        self.assertEqual(payload["us10y"], 4.1)


if __name__ == "__main__":
    unittest.main()
