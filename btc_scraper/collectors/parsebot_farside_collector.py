"""Parse.bot Farside ETF Flow Collector — Phase 7 Frequency Improvement.

Kiến trúc đúng:
  Scheduled Job → fetch() → lưu cache JSON
  Trading scan  → get_etf_feature_for_scoring() → chỉ đọc cache

Không bao giờ gọi API trong vòng scan 15 phút.
Khi API fail → status='failed', etf_flow_weight=0, không fake 0.0.

Endpoints được hỗ trợ:
  BTC: get_bitcoin_etf_flows_recent, get_bitcoin_etf_flows_all
  ETH: get_ethereum_etf_flows_recent, get_ethereum_etf_flows_all
  SOL: get_solana_etf_flows
  FUND: get_fund_info

Usage:
  # Trong job script (scheduled):
  from btc_scraper.collectors.parsebot_farside_collector import ParsebotFarsideETFCollector
  collector = ParsebotFarsideETFCollector()
  result = collector.fetch(symbol="BTC", mode="recent")

  # Trong trading scan (read-only):
  from btc_scraper.collectors.parsebot_farside_collector import get_etf_feature_for_scoring
  feature = get_etf_feature_for_scoring("BTC")
  # feature["etf_flow_status"] in {"ok", "stale", "failed", "missing", "unsupported", "disabled"}
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CACHE_DIR = _REPO_ROOT / "logs" / "etf_flow_cache"

# ---------------------------------------------------------------------------
# Endpoint mapping (đọc từ env, fallback về tên mặc định)
# ---------------------------------------------------------------------------

def _build_endpoint_map() -> Dict[str, Dict[str, Optional[str]]]:
    return {
        "BTC": {
            "recent": os.getenv("PARSEBOT_ENDPOINT_BTC_RECENT", "get_bitcoin_etf_flows_recent"),
            "all": os.getenv("PARSEBOT_ENDPOINT_BTC_ALL", "get_bitcoin_etf_flows_all"),
        },
        "ETH": {
            "recent": os.getenv("PARSEBOT_ENDPOINT_ETH_RECENT", "get_ethereum_etf_flows_recent"),
            "all": os.getenv("PARSEBOT_ENDPOINT_ETH_ALL", "get_ethereum_etf_flows_all"),
        },
        "SOL": {
            "recent": os.getenv("PARSEBOT_ENDPOINT_SOL_FLOWS", "get_solana_etf_flows"),
            "all": None,  # SOL không có all endpoint
        },
        "FUND": {
            "info": os.getenv("PARSEBOT_ENDPOINT_FUND_INFO", "get_fund_info"),
        },
    }


def get_parsebot_endpoint(symbol: str, mode: str) -> Optional[str]:
    """Resolve tên endpoint Parse.bot từ symbol + mode.

    Returns:
        Tên endpoint (ví dụ 'get_bitcoin_etf_flows_recent'), hoặc None nếu không hỗ trợ.
    """
    ep_map = _build_endpoint_map()
    symbol_config = ep_map.get(symbol.upper())
    if not symbol_config:
        return None
    return symbol_config.get(mode)


# ---------------------------------------------------------------------------
# Feature flag helpers
# ---------------------------------------------------------------------------

_FEATURE_FLAG_MAP = {
    ("BTC", "recent"): "ENABLE_PARSEBOT_BTC_RECENT",
    ("BTC", "all"):    "ENABLE_PARSEBOT_BTC_ALL",
    ("ETH", "recent"): "ENABLE_PARSEBOT_ETH_RECENT",
    ("ETH", "all"):    "ENABLE_PARSEBOT_ETH_ALL",
    ("SOL", "recent"): "ENABLE_PARSEBOT_SOL_FLOWS",
    ("FUND", "info"):  "ENABLE_PARSEBOT_FUND_INFO",
}


def _is_endpoint_enabled(symbol: str, mode: str) -> bool:
    key = (symbol.upper(), mode.lower())
    env_var = _FEATURE_FLAG_MAP.get(key)
    if env_var is None:
        return True  # không có flag → mặc định bật
    return os.getenv(env_var, "true").strip().lower() == "true"


# ---------------------------------------------------------------------------
# Scoring function
# ---------------------------------------------------------------------------

def compute_etf_flow_score(total_flow_usd_m: float) -> float:
    """Chuyển tổng ETF flow (USD million) sang score [-1.0, 1.0].

    Ngưỡng theo §13 của kế hoạch:
      >= +500M  → 1.0  (inflow rất mạnh)
      >= +250M  → 0.7
      >= +100M  → 0.4
      > -100M   → 0.0  (trung tính)
      > -250M   → -0.4
      > -500M   → -0.7
      <= -500M  → -1.0 (outflow rất mạnh)
    """
    if total_flow_usd_m >= 500:
        return 1.0
    if total_flow_usd_m >= 250:
        return 0.7
    if total_flow_usd_m >= 100:
        return 0.4
    if total_flow_usd_m > -100:
        return 0.0
    if total_flow_usd_m > -250:
        return -0.4
    if total_flow_usd_m > -500:
        return -0.7
    return -1.0


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_path(symbol: str, mode: str) -> Path:
    """Trả về đường dẫn tới file cache JSON cho (symbol, mode)."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{symbol.upper()}_{mode.lower()}.json"


def _save_cache(result: Dict[str, Any]) -> None:
    """Lưu kết quả fetch vào cache JSON."""
    symbol = result.get("symbol", "UNKNOWN")
    mode = result.get("mode", "unknown")
    path = _cache_path(symbol, mode)
    try:
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        _logger.debug("ETF cache saved: %s", path)
    except Exception as e:
        _logger.warning("Failed to save ETF cache %s: %s", path, e)


def _load_cache(symbol: str, mode: str) -> Optional[Dict[str, Any]]:
    """Đọc cache JSON cho (symbol, mode). Trả None nếu không tồn tại."""
    path = _cache_path(symbol, mode)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        _logger.warning("Failed to load ETF cache %s: %s", path, e)
        return None


def _is_stale(result: Dict[str, Any], max_hours: Optional[int] = None) -> bool:
    """Kiểm tra xem cache có quá cũ không."""
    if max_hours is None:
        max_hours = int(os.getenv("ETF_FLOW_MAX_STALE_HOURS", "36"))
    fetched_at = result.get("fetched_at")
    if not fetched_at:
        return True
    try:
        dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age_hours = (now - dt).total_seconds() / 3600
        return age_hours > max_hours
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Main collector
# ---------------------------------------------------------------------------

class ParsebotFarsideETFCollector:
    """Collector cho Parse.bot Farside ETF Flows.

    Phương thức `fetch()` dùng trong scheduled jobs để gọi API và lưu cache.
    Không bao giờ gọi phương thức này trong trading scan 15 phút.
    """

    def __init__(self) -> None:
        self.enabled = os.getenv("PARSEBOT_ENABLED", "false").strip().lower() == "true"
        self.base_url = (os.getenv("PARSEBOT_BASE_URL") or "").strip().rstrip("/")
        self.api_key = (os.getenv("PARSEBOT_API_KEY") or "").strip()
        self.timeout = int(os.getenv("PARSEBOT_TIMEOUT_SECONDS", "20"))
        self.max_retries = int(os.getenv("PARSEBOT_MAX_RETRIES", "2"))
        self.retry_delay = int(os.getenv("PARSEBOT_RETRY_DELAY_SECONDS", "5"))

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    def _build_url(self, endpoint: str) -> str:
        return f"{self.base_url}/{endpoint}"

    def _result(
        self,
        symbol: str,
        mode: str,
        status: str,
        value: Any,
        data_quality: float,
        error: Optional[str],
        endpoint: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "source": "parsebot_farside",
            "endpoint": endpoint,
            "symbol": symbol.upper(),
            "mode": mode,
            "status": status,
            "value": value,
            "data_quality": data_quality,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "error": error,
        }

    def fetch(self, symbol: str, mode: str) -> Dict[str, Any]:
        """Gọi Parse.bot API, retry khi cần, lưu kết quả vào cache.

        Args:
            symbol: "BTC", "ETH", "SOL", "FUND"
            mode: "recent", "all", "info"

        Returns:
            Dict với keys: source, endpoint, symbol, mode, status,
                           value, data_quality, fetched_at, error
        """
        symbol = symbol.upper()

        if not self.enabled:
            result = self._result(symbol, mode, "disabled", None, 0.0, "PARSEBOT_ENABLED=false")
            _logger.debug("parsebot_farside disabled for %s/%s", symbol, mode)
            return result

        if not self.base_url or not self.api_key:
            result = self._result(symbol, mode, "disabled", None, 0.0, "Missing PARSEBOT_BASE_URL or PARSEBOT_API_KEY")
            _logger.warning("parsebot_farside: missing config for %s/%s", symbol, mode)
            return result

        if not _is_endpoint_enabled(symbol, mode):
            result = self._result(symbol, mode, "disabled", None, 0.0, f"ENABLE_PARSEBOT_{symbol}_{mode.upper()}=false")
            _logger.debug("parsebot_farside endpoint disabled: %s/%s", symbol, mode)
            return result

        endpoint = get_parsebot_endpoint(symbol, mode)
        if not endpoint:
            result = self._result(
                symbol, mode, "unsupported", None, 0.0,
                f"ETF flow is only supported for BTC/ETH/SOL (recent/all) and FUND (info)",
            )
            _logger.info("parsebot_farside: unsupported symbol/mode %s/%s", symbol, mode)
            return result

        url = self._build_url(endpoint)
        last_error: Optional[str] = None

        try:
            import requests as _requests
        except ImportError:
            result = self._result(symbol, mode, "failed", None, 0.0, "requests library not available", endpoint)
            _save_cache(result)
            return result

        for attempt in range(self.max_retries + 1):
            try:
                response = _requests.get(url, headers=self._headers(), timeout=self.timeout)
                response.raise_for_status()
                data = response.json()

                result = self._result(symbol, mode, "ok", data, 1.0, None, endpoint)
                _save_cache(result)
                _logger.info(
                    "parsebot_farside %s.%s.ok (attempt=%d)",
                    symbol, mode, attempt + 1,
                )
                return result

            except Exception as exc:
                last_error = str(exc)
                _logger.warning(
                    "parsebot_farside %s.%s attempt %d/%d failed: %s",
                    symbol, mode, attempt + 1, self.max_retries + 1, last_error,
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

        result = self._result(symbol, mode, "failed", None, 0.0, last_error, endpoint)
        _save_cache(result)
        _logger.error("parsebot_farside %s.%s.failed: %s", symbol, mode, last_error)
        return result


# ---------------------------------------------------------------------------
# Scoring interface (dùng trong trading scan — chỉ đọc cache)
# ---------------------------------------------------------------------------

def get_etf_feature_for_scoring(symbol: str, mode: str = "recent") -> Dict[str, Any]:
    """Load ETF flow feature từ cache cho trading scan.

    Không bao giờ gọi API. Chỉ đọc file cache JSON.
    Trả weight=0 khi data không usable (missing/failed/stale/unsupported/disabled).

    Args:
        symbol: "BTC", "ETH", "SOL"
        mode: "recent" (default) hoặc "all"

    Returns:
        {
            "etf_flow_score": float | None,
            "etf_flow_weight": 0 | 1,
            "etf_flow_status": "ok" | "stale" | "failed" | "missing" | "unsupported" | "disabled",
            "etf_flow_source": str,
            "total_flow_usd_m": float | None,
            "fetched_at": str | None,
        }
    """
    def _no_data(status: str, reason: Optional[str] = None) -> Dict[str, Any]:
        return {
            "etf_flow_score": None,
            "etf_flow_weight": 0,
            "etf_flow_status": status,
            "etf_flow_source": "parsebot_farside",
            "total_flow_usd_m": None,
            "fetched_at": None,
            "error": reason,
        }

    # Kiểm tra symbol có được hỗ trợ không
    supported = [s.strip() for s in os.getenv("SUPPORTED_ETF_FLOW_SYMBOLS", "BTC,ETH,SOL").split(",")]
    if symbol.upper() not in supported:
        _logger.debug("ETF flow unsupported for %s", symbol)
        return _no_data("unsupported", f"ETF flow not supported for {symbol}")

    latest = _load_cache(symbol, mode)

    if latest is None:
        _logger.debug("ETF flow cache missing for %s/%s", symbol, mode)
        return _no_data("missing")

    cache_status = latest.get("status", "")

    if cache_status not in ("ok",):
        _logger.debug("ETF flow cache status=%s for %s/%s", cache_status, symbol, mode)
        return _no_data(cache_status, latest.get("error"))

    if _is_stale(latest):
        _logger.info("ETF flow cache stale for %s/%s (fetched_at=%s)", symbol, mode, latest.get("fetched_at"))
        if os.getenv("ETF_FLOW_DISABLE_WEIGHT_ON_STALE", "true").strip().lower() == "true":
            return _no_data("stale", f"Data older than {os.getenv('ETF_FLOW_MAX_STALE_HOURS', '36')} hours")

    # Trích xuất total_flow_usd_m từ value
    value = latest.get("value") or {}
    total_flow_usd_m = _extract_total_flow(value, symbol)

    if total_flow_usd_m is None:
        _logger.warning("ETF flow: cannot extract total_flow_usd_m from cache for %s/%s", symbol, mode)
        return _no_data("failed", "Cannot parse total_flow_usd_m from API response")

    score = compute_etf_flow_score(total_flow_usd_m)
    _logger.info(
        "ETF flow feature ok: %s/%s flow=%.1fM score=%.2f",
        symbol, mode, total_flow_usd_m, score,
    )

    return {
        "etf_flow_score": score,
        "etf_flow_weight": 1,
        "etf_flow_status": "ok",
        "etf_flow_source": "parsebot_farside",
        "total_flow_usd_m": total_flow_usd_m,
        "fetched_at": latest.get("fetched_at"),
        "error": None,
    }


def _extract_total_flow(value: Any, symbol: str) -> Optional[float]:
    """Trích xuất tổng flow (USD M) từ API response.

    Parse.bot có thể trả về nhiều format khác nhau. Hàm này xử lý
    các format phổ biến theo thứ tự ưu tiên.
    """
    if not isinstance(value, (dict, list)):
        return None

    # Format 1: {"total_flow": 123.4}
    if isinstance(value, dict):
        for key in ("total_flow", "total_flow_usd_m", "net_flow", "flow"):
            v = value.get(key)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue

        # Format 2: {"data": [{"flow": 123.4, "date": "..."}, ...]}
        data = value.get("data")
        if isinstance(data, list) and data:
            latest_record = data[-1]
            if isinstance(latest_record, dict):
                for key in ("flow", "net_flow", "total_flow"):
                    v = latest_record.get(key)
                    if v is not None:
                        try:
                            return float(v)
                        except (TypeError, ValueError):
                            continue

    # Format 3: list of records directly
    if isinstance(value, list) and value:
        latest_record = value[-1]
        if isinstance(latest_record, dict):
            for key in ("flow", "net_flow", "total_flow"):
                v = latest_record.get(key)
                if v is not None:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        continue

    return None
