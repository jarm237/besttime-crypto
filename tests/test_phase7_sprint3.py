import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from btc_scraper.collectors.glassnode_collector import GlassnodeCollector
from btc_scraper.collectors.blockchain_collector import BlockchainCollector
from btc_scraper.collectors.blockchair_collector import BlockchairCollector
from btc_scraper.collectors.whalealert_collector import WhaleAlertCollector
from btc_scraper.collectors.deribit_collector import DeribitCollector
from btc_scraper.collectors.etf_collector import ETFCollector


class Phase7Sprint3Tests(unittest.TestCase):
    def test_glassnode_collector_parses_metrics(self):
        fake_payload = {"data": [{"x": 1710000000, "y": 1200000}]}
        with patch("btc_scraper.collectors.glassnode_collector._fetch_json", return_value=fake_payload):
            collector = GlassnodeCollector(output_path=str(Path(tempfile.gettempdir()) / "glassnode.json"))
            data = collector.collect(force=True)
        self.assertEqual(data["active_addresses"], 1200000.0)

    def test_blockchain_collector_parses_hashrate(self):
        fake_payload = {"hash_rate": "5000000000000"}
        with patch("btc_scraper.collectors.blockchain_collector._fetch_json", return_value=fake_payload):
            collector = BlockchainCollector(output_path=str(Path(tempfile.gettempdir()) / "blockchain.json"))
            data = collector.collect(force=True)
        self.assertEqual(data["hashrate"], 5000000000000.0)

    def test_blockchair_collector_parses_netflow(self):
        fake_payload = {"data": [{"value": -100000}]}
        with patch("btc_scraper.collectors.blockchair_collector._fetch_json", return_value=fake_payload):
            collector = BlockchairCollector(output_path=str(Path(tempfile.gettempdir()) / "blockchair.json"))
            data = collector.collect(force=True)
        self.assertEqual(data["exchange_netflow"], -100000.0)

    def test_whalealert_collector_parses_whale_score(self):
        fake_payload = {"data": [{"amount_usd": 50000000}]}
        with patch("btc_scraper.collectors.whalealert_collector._fetch_json", return_value=fake_payload):
            collector = WhaleAlertCollector(output_path=str(Path(tempfile.gettempdir()) / "whalealert.json"))
            data = collector.collect(force=True)
        self.assertEqual(data["whale_score"], 50.0)

    def test_deribit_collector_parses_iv(self):
        fake_payload = {"result": [{"mark_iv": 0.6, "best_ask_iv": 0.65, "best_bid_iv": 0.55}]}
        with patch("btc_scraper.collectors.deribit_collector._fetch_json", return_value=fake_payload):
            collector = DeribitCollector(output_path=str(Path(tempfile.gettempdir()) / "deribit.json"))
            data = collector.collect(force=True)
        self.assertEqual(data["options_iv"], 0.6)
        self.assertEqual(data["iv_skew"], 0.1)

    def test_etf_collector_parses_flow(self):
        fake_payload = {"data": [{"net_flow": 1200000}]}
        with patch("btc_scraper.collectors.etf_collector._fetch_json", return_value=fake_payload):
            collector = ETFCollector(output_path=str(Path(tempfile.gettempdir()) / "etf.json"))
            data = collector.collect(force=True)
        self.assertEqual(data["etf_flow"], 1200000.0)


if __name__ == "__main__":
    unittest.main()
