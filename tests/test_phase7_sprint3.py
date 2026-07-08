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
from btc_scraper.collectors.alternative_me_collector import AlternativeMeCollector
from btc_scraper.collectors.binance_collector import BinanceCollector
from btc_scraper.collectors.defillama_collector import DefiLlamaCollector
from btc_scraper.collectors.fred_collector import FredCollector
from btc_scraper.collectors.yahoo_collector import YahooCollector
from btc_scraper.collectors.blockchain_collector import BlockchainCollector
from btc_scraper.collectors.blockchair_collector import BlockchairCollector
from btc_scraper.collectors.google_trends_collector import GoogleTrendsCollector
from btc_scraper.collectors.reddit_collector import RedditCollector


class Phase7Sprint3Tests(unittest.TestCase):
    def test_glassnode_collector_parses_metrics(self):
        fake_payload = {"data": [{"x": 1710000000, "y": 1200000}]}
        with patch.dict("os.environ", {"ENABLE_GLASSNODE": "true", "GLASSNODE_API_KEY": "testkey"}):
            with patch("btc_scraper.collectors.glassnode_collector._fetch_json", return_value=fake_payload):
                collector = GlassnodeCollector(output_path=str(Path(tempfile.gettempdir()) / "glassnode.json"))
                data = collector.collect(force=True)
        self.assertEqual(data["active_addresses"], 1200000.0)

    def test_blockchain_collector_parses_hashrate(self):
        fake_payload = {
            "status": "success",
            "reason": None,
            "data": {
                "values": [{"y": 5000000000000.0}]
            }
        }
        with patch("btc_scraper.collectors.blockchain_collector._fetch_json", return_value=fake_payload):
            collector = BlockchainCollector(output_path=str(Path(tempfile.gettempdir()) / "blockchain.json"))
            data = collector.collect(force=True)
        self.assertEqual(data["hashrate"], 5000000000000.0)

    def test_blockchair_collector_parses_netflow(self):
        fake_payload = {"data": {"transactions_24h": 100, "market_price_usd": 60000}}
        with patch("btc_scraper.collectors.blockchair_collector.requests.get") as mock_get:
            mock_response = mock_get.return_value
            mock_response.json.return_value = fake_payload
            mock_response.status_code = 200
            
            collector = BlockchairCollector(output_path=str(Path(tempfile.gettempdir()) / "blockchair.json"))
            data = collector.collect(force=True)
        self.assertIsNone(data["exchange_netflow"])

    def test_whalealert_collector_parses_whale_score(self):
        fake_payload = {"data": [{"amount_usd": 50000000}]}
        with patch.dict("os.environ", {"ENABLE_WHALE_ALERT": "true", "WHALE_ALERT_API_KEY": "testkey"}):
            with patch("btc_scraper.collectors.whalealert_collector._fetch_json", return_value=fake_payload):
                collector = WhaleAlertCollector(output_path=str(Path(tempfile.gettempdir()) / "whalealert.json"))
                data = collector.collect(force=True)
        self.assertEqual(data["whale_score"], 50.0)

    def test_alternative_me_collector_parses_fear_greed(self):
        fake_payload = {"data": [{"value": "78", "value_classification": "greed"}]}
        with patch("btc_scraper.collectors.alternative_me_collector._fetch_json", return_value=fake_payload):
            collector = AlternativeMeCollector(output_path=str(Path(tempfile.gettempdir()) / "alternative_me.json"))
            data = collector.collect(force=True)
        self.assertEqual(data["fear_greed_raw"], 78.0)
        self.assertEqual(data["fear_greed_score"], 0.78)
        self.assertEqual(data["fear_greed_regime"], "greed")

    def test_alternative_me_collector_skips_when_disabled(self):
        with patch.dict("os.environ", {"ENABLE_ALTERNATIVE_ME": "false"}):
            collector = AlternativeMeCollector(output_path=str(Path(tempfile.gettempdir()) / "alternative_me_disabled.json"))
            data = collector.collect(force=True)
        self.assertEqual(data["status"], "skipped")
        self.assertEqual(data["reason"], "disabled_by_env")

    def test_deribit_collector_parses_iv(self):
        fake_payload = {"result": [{"mark_iv": 0.6, "best_ask_iv": 0.65, "best_bid_iv": 0.55}]}
        with patch("btc_scraper.collectors.deribit_collector._fetch_json", return_value=fake_payload):
            collector = DeribitCollector(output_path=str(Path(tempfile.gettempdir()) / "deribit.json"))
            data = collector.collect(force=True)
        self.assertEqual(data["options_iv"], 0.6)
        self.assertEqual(data["iv_skew"], 0.1)

    def test_etf_collector_parses_flow(self):
        from btc_scraper.collectors.etf_providers import ETFFlowResult
        fake_result = ETFFlowResult(
            provider_name="test",
            etf_flow=1200000.0,
            etf_flow_confidence=1.0,
            etf_flow_source="test_source",
            etf_flow_scope="us_spot_btc_etf",
            success=True
        )
        with patch.dict("os.environ", {"ENABLE_ETF": "true", "PARSEBOT_ENABLED": "false"}):
            with patch("btc_scraper.collectors.etf_collector.ETFProviderChain.fetch", return_value=fake_result):
                collector = ETFCollector(output_path=str(Path(tempfile.gettempdir()) / "etf.json"))
                data = collector.collect(force=True)
        self.assertEqual(data["etf_flow"], 1200000.0)


if __name__ == "__main__":
    unittest.main()
