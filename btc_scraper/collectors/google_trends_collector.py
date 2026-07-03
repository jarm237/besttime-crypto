"""Google Trends collector for search interest sentiment proxy."""
from __future__ import annotations
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from btc_scraper.collectors.collector_base import CollectorBase
from btc_scraper.core.paths import build_data_path
import logging
import json

_logger = logging.getLogger(__name__)

try:
    import requests
except Exception:  # pragma: no cover
    requests = None
try:
    from pytrends.request import TrendReq
except Exception:  # pragma: no cover
    TrendReq = None


CACHE_DIR = build_data_path("google_trends_cache")
CACHE_FRESHNESS_SECONDS = 6 * 3600  # 6 hours


def _get_cache_path(keyword: str) -> Path:
    """Get cache file path for a keyword."""
    cache_dir = Path(CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{keyword.replace(' ', '_')}.json"


def _read_cache(keyword: str) -> Optional[Dict[str, Any]]:
    """Read cached trend data if fresh."""
    cache_path = _get_cache_path(keyword)
    if not cache_path.exists():
        return None
    
    try:
        with open(cache_path, "r") as f:
            cache = json.load(f)
        
        # Check if cache is still fresh
        cached_at = datetime.fromisoformat(cache.get("cached_at", ""))
        age_seconds = (datetime.now(timezone.utc) - cached_at.replace(tzinfo=timezone.utc)).total_seconds()
        
        if age_seconds < CACHE_FRESHNESS_SECONDS:
            _logger.debug("Using cached Google Trends data for '%s' (age=%.0fs)", keyword, age_seconds)
            return cache
        else:
            _logger.debug("Google Trends cache expired for '%s' (age=%.0fs)", keyword, age_seconds)
            return None
    except Exception as e:
        _logger.warning("Failed to read Google Trends cache: %s", e)
        return None


def _write_cache(keyword: str, data: Dict[str, Any]) -> None:
    """Write trend data to cache."""
    cache_path = _get_cache_path(keyword)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(data, f)
        _logger.debug("Wrote Google Trends cache for '%s'", keyword)
    except Exception as e:
        _logger.warning("Failed to write Google Trends cache: %s", e)


class GoogleTrendsCollector(CollectorBase):
    name = "google_trends"

    def __init__(
        self,
        output_path: Optional[str | os.PathLike[str]] = None,
        retries: int = 1,  # Reduced retries for 429 handling
        delay_seconds: float = 2.0,  # Increased delay
    ) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)
        # Disabled by default: pytrends is unofficial and prone to 429
        self.enabled = os.getenv("ENABLE_GOOGLE_TRENDS", "false").strip().lower() == "true"
        if not self.enabled:
            _logger.info(
                "GoogleTrendsCollector is disabled by default. "
                "Set ENABLE_GOOGLE_TRENDS=true and ensure minimum 6h interval between collections. "
                "pytrends is unofficial and prone to rate-limiting (429 errors)."
            )
        self.keyword = "bitcoin"

    def collect(self, force: bool = False) -> Dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "source": self.name,
            "status": "success",
            "reason": None,
            "timestamp": timestamp,
            "data": {"sentiment_score": 0.0},
            "sentiment_score": 0.0,
            "search_interest_confidence": 0.0,
        }

        if not self.enabled:
            payload["status"] = "skipped"
            payload["reason"] = "disabled_by_env"
            payload["data"] = None
            if self.output_path is not None:
                self._write_json(payload, self.output_path)
            return payload

        # Try cache first (Sprint 9.5 hardening)
        if not force:
            cached = _read_cache(self.keyword)
            if cached is not None:
                payload["sentiment_score"] = cached.get("sentiment_score", 0.0)
                payload["search_interest_confidence"] = cached.get("confidence", 0.35)
                payload["data"]["sentiment_score"] = payload["sentiment_score"]
                payload["status"] = "cached"
                payload["reason"] = "served_from_cache"
                if self.output_path is not None:
                    self._write_json(payload, self.output_path)
                return payload

        try:
            # Prefer pytrends library
            if TrendReq is not None:
                try:
                    pytrends = TrendReq(hl="en-US", tz=0, requests_args={'timeout': (10, 15)})
                    pytrends.build_payload([self.keyword], timeframe="now 7-d")
                    
                    # Add random delay to avoid being detected as bot
                    time.sleep(1 + (os.urandom(1)[0] % 3))
                    
                    df = pytrends.interest_over_time()
                    if df is not None and not df.empty and self.keyword in df.columns:
                        last_val = float(df[self.keyword].iloc[-1])
                        payload["sentiment_score"] = last_val / 100.0  # Normalize to 0-1
                        payload["search_interest_confidence"] = 0.35  # Low confidence due to unofficial source
                        payload["data"]["sentiment_score"] = payload["sentiment_score"]
                        payload["status"] = "success"
                        
                        # Write to cache
                        _write_cache(
                            self.keyword,
                            {
                                "sentiment_score": payload["sentiment_score"],
                                "confidence": 0.35,
                                "cached_at": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                        _logger.info("Google Trends collected: score=%.2f", payload["sentiment_score"])
                    else:
                        _logger.debug("pytrends returned empty dataframe or missing column")
                        payload["status"] = "fallback"
                        payload["reason"] = "empty_response"

                except Exception as py_err:
                    # Handle 429 gracefully
                    if "429" in str(py_err):
                        _logger.warning("Google Trends 429 Too Many Requests; using cache or default")
                        payload["status"] = "rate_limited"
                        payload["reason"] = "429_too_many_requests"
                        payload["search_interest_confidence"] = 0.0  # No confidence when rate-limited
                    else:
                        _logger.warning("pytrends failed: %s", py_err)
                        payload["status"] = "error"
                        payload["reason"] = str(py_err)
                        
            else:
                _logger.warning("pytrends not installed")
                payload["status"] = "error"
                payload["reason"] = "pytrends_not_installed"

        except Exception as e:
            _logger.warning("GoogleTrendsCollector failed: %s", e)
            payload = {
                "source": self.name,
                "status": "error",
                "reason": repr(e),
                "timestamp": timestamp,
                "data": None,
                "sentiment_score": 0.0,
                "search_interest_confidence": 0.0,
            }

        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
