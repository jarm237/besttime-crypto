"""Reddit OAuth collector for social sentiment — Phase 7 Sprint 9.4.

Implements Reddit API data collection with local sentiment scoring.
Uses official Reddit API (requires OAuth credentials).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_logger = logging.getLogger(__name__)

try:
    import praw
    import nltk
    from nltk.sentiment import SentimentIntensityAnalyzer
    # Download VADER lexicon if not already present
    try:
        nltk.data.find("sentiment/vader_lexicon")
    except LookupError:
        nltk.download("vader_lexicon", quiet=True)
except ImportError:
    praw = None
    SentimentIntensityAnalyzer = None


DEFAULT_SUBREDDITS = [
    "Bitcoin",
    "CryptoCurrency",
    "ethfinance",
    "solana",
    "cryptocurrency",
]


@dataclass
class RedditSentimentResult:
    """Result from Reddit sentiment collection."""

    sentiment_score: float  # -1.0 (bearish) to 1.0 (bullish)
    sentiment_volume: int
    sentiment_zscore: float
    posts_analyzed: int
    top_topics: list[str]
    success: bool = True
    error: Optional[str] = None
    source: str = "reddit_oauth"
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


def _validate_reddit_config() -> tuple[bool, Optional[str]]:
    """Validate Reddit OAuth environment variables."""
    client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    user_agent = os.getenv("REDDIT_USER_AGENT", "").strip()

    if not client_id:
        return False, "REDDIT_CLIENT_ID not configured"
    if not client_secret:
        return False, "REDDIT_CLIENT_SECRET not configured"
    if not user_agent:
        return False, "REDDIT_USER_AGENT not configured"

    return True, None


def _score_sentiment_vader(text: str) -> float:
    """
    Score sentiment using VADER (Valence Aware Dictionary and sEntiment Reasoner).

    Returns:
        float: compound score from -1.0 (negative) to 1.0 (positive).
    """
    if SentimentIntensityAnalyzer is None:
        return 0.0

    try:
        sia = SentimentIntensityAnalyzer()
        scores = sia.polarity_scores(text)
        return scores.get("compound", 0.0)
    except Exception as e:
        _logger.debug("VADER sentiment scoring failed: %s", e)
        return 0.0


def _extract_topics(posts: list[Dict[str, Any]]) -> list[str]:
    """Extract top topics/keywords from posts."""
    keywords = {}
    stop_words = {"bitcoin", "crypto", "btc", "eth", "the", "a", "is", "to", "in", "of"}

    for post in posts[:10]:  # Analyze top 10 posts
        title = post.get("title", "").lower()
        words = title.split()
        for word in words:
            word_clean = word.strip(".,!?;:").lower()
            if len(word_clean) > 3 and word_clean not in stop_words:
                keywords[word_clean] = keywords.get(word_clean, 0) + 1

    sorted_keywords = sorted(keywords.items(), key=lambda x: x[1], reverse=True)
    return [word for word, _ in sorted_keywords[:5]]


class RedditOAuthCollector:
    """Collect cryptocurrency sentiment from Reddit using official API."""

    def __init__(self, subreddits: Optional[list[str]] = None, limit: int = 25) -> None:
        """
        Initialize Reddit OAuth collector.

        Args:
            subreddits: List of subreddit names to monitor. Defaults to crypto subreddits.
            limit: Number of posts to fetch per subreddit (max 100, default 25).
        """
        self.subreddits = subreddits or DEFAULT_SUBREDDITS
        self.limit = min(limit, 100)
        self.reddit = None
        self._validate_and_init()

    def _validate_and_init(self) -> None:
        """Validate config and initialize Reddit client."""
        if praw is None:
            _logger.warning("praw is not installed; RedditOAuthCollector will not work")
            return

        valid, error_msg = _validate_reddit_config()
        if not valid:
            _logger.warning("Reddit OAuth validation failed: %s", error_msg)
            return

        try:
            self.reddit = praw.Reddit(
                client_id=os.getenv("REDDIT_CLIENT_ID"),
                client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
                user_agent=os.getenv("REDDIT_USER_AGENT"),
            )
            # Test credentials by making a simple request
            _ = self.reddit.user.me()
            _logger.info("Reddit OAuth client initialized successfully")
        except Exception as e:
            _logger.warning("Failed to initialize Reddit OAuth client: %s", e)
            self.reddit = None

    def collect(self) -> Optional[RedditSentimentResult]:
        """
        Collect sentiment from Reddit posts.

        Returns:
            RedditSentimentResult if successful, None otherwise.
        """
        if self.reddit is None:
            _logger.debug("Reddit OAuth client not initialized")
            return None

        try:
            all_posts = []
            sentiment_scores = []
            total_comments = 0

            for subreddit_name in self.subreddits:
                try:
                    subreddit = self.reddit.subreddit(subreddit_name)
                    posts = subreddit.hot(limit=self.limit)

                    for post in posts:
                        # Skip stickied posts, very new posts
                        if post.stickied or post.score < 10:
                            continue

                        # Score post title + body
                        text = f"{post.title} {post.selftext}"
                        sentiment = _score_sentiment_vader(text)
                        sentiment_scores.append(sentiment)

                        total_comments += post.num_comments
                        all_posts.append(
                            {
                                "subreddit": subreddit_name,
                                "title": post.title,
                                "score": post.score,
                                "sentiment": sentiment,
                            }
                        )

                except Exception as e:
                    _logger.warning("Failed to fetch from r/%s: %s", subreddit_name, e)
                    continue

            if not sentiment_scores:
                _logger.warning("No posts analyzed from Reddit")
                return None

            # Calculate aggregate sentiment
            avg_sentiment = sum(sentiment_scores) / len(sentiment_scores)

            # Calculate Z-score (standardized score)
            if len(sentiment_scores) > 1:
                variance = sum((s - avg_sentiment) ** 2 for s in sentiment_scores) / len(sentiment_scores)
                std_dev = variance ** 0.5
                if std_dev > 0:
                    zscore = (avg_sentiment - avg_sentiment) / std_dev
                else:
                    zscore = 0.0
            else:
                zscore = 0.0

            topics = _extract_topics(all_posts)

            _logger.info(
                "Reddit sentiment collected: score=%.3f, posts=%d, comments=%d",
                avg_sentiment,
                len(all_posts),
                total_comments,
            )

            return RedditSentimentResult(
                sentiment_score=avg_sentiment,
                sentiment_volume=len(all_posts),
                sentiment_zscore=zscore,
                posts_analyzed=len(all_posts),
                top_topics=topics,
                success=True,
            )

        except Exception as e:
            _logger.exception("RedditOAuthCollector.collect() failed: %s", e)
            return None
