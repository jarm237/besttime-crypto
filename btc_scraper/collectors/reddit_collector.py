"""Reddit collector for sentiment proxy."""
from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from btc_scraper.collectors.collector_base import CollectorBase
from btc_scraper.collectors.reddit_oauth import RedditOAuthCollector
import logging

_logger = logging.getLogger(__name__)


class RedditCollector(CollectorBase):
    name = "reddit"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)
        # Disabled by default: placeholder endpoint requires Reddit OAuth implementation
        self.enabled = os.getenv("ENABLE_REDDIT", "false").strip().lower() == "true"
        if not self.enabled:
            _logger.info(
                "RedditCollector is disabled by default. "
                "Set ENABLE_REDDIT=true and configure REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT before enabling."
            )

    def collect(self, force: bool = False) -> Dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "source": self.name,
            "status": "success",
            "reason": None,
            "timestamp": timestamp,
            "data": {"sentiment_score": None},
            "sentiment_score": None,
            "sentiment_volume": 0,
            "sentiment_zscore": None,
            "field_statuses": {},
        }

        if not self.enabled:
            payload["status"] = "skipped"
            payload["reason"] = "collector_disabled_or_no_samples"
            payload["data"] = None
            payload["field_statuses"]["social_sentiment"] = {
                "status": "missing", "reason": "collector_disabled_or_no_samples"
            }
            if self.output_path is not None:
                self._write_json(payload, self.output_path)
            return payload

        try:
            # Use Reddit OAuth collector
            collector = RedditOAuthCollector()
            result = collector.collect()

            minimum_samples = max(1, int(os.getenv("REDDIT_MIN_SENTIMENT_SAMPLES", "10")))
            if result is not None and result.posts_analyzed >= minimum_samples:
                payload["sentiment_score"] = result.sentiment_score
                payload["sentiment_volume"] = result.sentiment_volume
                payload["sentiment_zscore"] = result.sentiment_zscore
                payload["data"]["sentiment_score"] = result.sentiment_score
                payload["data"]["sentiment_volume"] = result.sentiment_volume
                payload["data"]["sentiment_zscore"] = result.sentiment_zscore
                payload["status"] = "success"
                _logger.info(
                    "Reddit sentiment collected: score=%.3f, posts=%d",
                    result.sentiment_score,
                    result.posts_analyzed,
                )
            else:
                payload["status"] = "fallback"
                payload["reason"] = "collector_disabled_or_no_samples"
                payload["field_statuses"]["social_sentiment"] = {
                    "status": "missing", "reason": "collector_disabled_or_no_samples"
                }
                _logger.warning("Reddit OAuth collection failed or returned too few samples")

        except Exception as e:
            _logger.exception("RedditCollector failed")
            payload = {
                "source": self.name,
                "status": "error",
                "reason": repr(e),
                "timestamp": timestamp,
                "data": None,
                "sentiment_score": None,
                "sentiment_volume": 0,
                "sentiment_zscore": None,
                "field_statuses": {
                    "social_sentiment": {"status": "error", "reason": repr(e)}
                },
            }
        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
