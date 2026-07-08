import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import pandas as pd

from btc_scraper.collectors.google_trends_collector import GoogleTrendsCollector
from btc_scraper.collectors.reddit_collector import RedditCollector


class Phase7Sprint4Tests(unittest.TestCase):
    def test_google_trends_collector_parses_interest(self):
        fake_df = pd.DataFrame({"bitcoin": [42.0]})
        with patch.dict("os.environ", {"ENABLE_GOOGLE_TRENDS": "true"}):
            with patch("btc_scraper.collectors.google_trends_collector.TrendReq") as mock_trendreq_class:
                mock_instance = mock_trendreq_class.return_value
                mock_instance.interest_over_time.return_value = fake_df
                
                collector = GoogleTrendsCollector(output_path=str(Path(tempfile.gettempdir()) / "google.json"))
                data = collector.collect(force=True)
        self.assertEqual(data["sentiment_score"], 0.42)

    def test_reddit_collector_parses_sentiment(self):
        fake_result = MagicMock()
        fake_result.sentiment_score = 0.8
        fake_result.sentiment_volume = 150
        fake_result.sentiment_zscore = 1.2
        fake_result.posts_analyzed = 150
        
        with patch.dict("os.environ", {"ENABLE_REDDIT": "true"}):
            with patch("btc_scraper.collectors.reddit_collector.RedditOAuthCollector") as mock_oauth_class:
                mock_instance = mock_oauth_class.return_value
                mock_instance.collect.return_value = fake_result
                
                collector = RedditCollector(output_path=str(Path(tempfile.gettempdir()) / "reddit.json"))
                data = collector.collect(force=True)
        self.assertEqual(data["sentiment_score"], 0.8)


if __name__ == "__main__":
    unittest.main()
