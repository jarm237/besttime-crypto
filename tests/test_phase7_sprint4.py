import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from btc_scraper.collectors.google_trends_collector import GoogleTrendsCollector
from btc_scraper.collectors.reddit_collector import RedditCollector


class Phase7Sprint4Tests(unittest.TestCase):
    def test_google_trends_collector_parses_interest(self):
        fake_payload = {"default": {"timelineData": [{"value": [42]}]}}
        with patch("btc_scraper.collectors.google_trends_collector._fetch_json", return_value=fake_payload):
            collector = GoogleTrendsCollector(output_path=str(Path(tempfile.gettempdir()) / "google.json"))
            data = collector.collect(force=True)
        self.assertEqual(data["sentiment_score"], 42.0)

    def test_reddit_collector_parses_sentiment(self):
        fake_payload = {"data": [{"score": 0.8}]}
        with patch("btc_scraper.collectors.reddit_collector._fetch_json", return_value=fake_payload):
            collector = RedditCollector(output_path=str(Path(tempfile.gettempdir()) / "reddit.json"))
            data = collector.collect(force=True)
        self.assertEqual(data["sentiment_score"], 0.8)


if __name__ == "__main__":
    unittest.main()
