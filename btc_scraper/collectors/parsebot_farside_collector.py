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
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _REPO_ROOT / "logs" / "etf_flow_cache"
_REQUEST_USAGE_PATH = _REPO_ROOT / "logs" / "parsebot_request_usage.json"
_REQUEST_USAGE_LOCK = threading.Lock()


def _reserve_parsebot_request(now: Optional[datetime] = None) -> tuple[bool, int, int]:
    """Atomically reserve one request from the configured monthly allowance.

    Usage is persisted so scheduler restarts and manual CLI jobs share the same
    quota. A corrupt counter fails closed to avoid accidentally exceeding the
    external API limit.
    """
    try:
        limit = max(1, int(os.getenv("PARSEBOT_MONTHLY_REQUEST_LIMIT", "180")))
    except ValueError:
        limit = 180

    usage_path = Path(os.getenv("PARSEBOT_REQUEST_USAGE_PATH", str(_REQUEST_USAGE_PATH)))
    month = (now or datetime.now(timezone.utc)).strftime("%Y-%m")
    usage_path.parent.mkdir(parents=True, exist_ok=True)

    with _REQUEST_USAGE_LOCK:
        with usage_path.open("a+", encoding="utf-8") as handle:
            try:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except ImportError:  # pragma: no cover - Windows uses process lock only
                pass

            handle.seek(0)
            raw = handle.read().strip()
            try:
                state = json.loads(raw) if raw else {}
                count = int(state.get("count", 0)) if state.get("month") == month else 0
            except (TypeError, ValueError, json.JSONDecodeError):
                _logger.error("Invalid Parse.bot request usage file; refusing API request: %s", usage_path)
                return False, limit, limit

            if count >= limit:
                return False, count, limit

            count += 1
            handle.seek(0)
            handle.truncate()
            json.dump({"month": month, "count": count}, handle)
            handle.flush()
            os.fsync(handle.fileno())
            return True, count, limit

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


def _save_fetch_log_to_db(result: Dict[str, Any]) -> None:
    """Lưu lịch sử gọi API vào MongoDB collection alternative_data_fetch_logs."""
    try:
        from btc_scraper.core.db import db
        logs_col = db["alternative_data_fetch_logs"]
        doc = {
            "source": "parsebot_farside",
            "endpoint": result.get("endpoint"),
            "symbol": result.get("symbol"),
            "mode": result.get("mode"),
            "status": result.get("status"),
            "error": result.get("error"),
            "fetched_at": result.get("fetched_at"),
        }
        logs_col.insert_one(doc)
    except Exception as e:
        _logger.warning("Failed to save fetch log to MongoDB: %s", e)


def _parse_and_save_records_to_db(result: Dict[str, Any]) -> None:
    """Phân tách raw response của Parse.bot và lưu/upsert từng ngày vào MongoDB alternative_data_etf_flows."""
    if result.get("status") != "ok":
        _save_fetch_log_to_db(result)
        return

    _save_fetch_log_to_db(result)

    value = result.get("value")
    symbol = result.get("symbol", "").upper()
    mode = result.get("mode", "")
    endpoint = result.get("endpoint", "")
    fetched_at = result.get("fetched_at")

    try:
        from btc_scraper.core.db import db
        flows_col = db["alternative_data_etf_flows"]
    except Exception as e:
        _logger.warning("MongoDB not available for saving ETF flows: %s", e)
        return

    # Extract list of records
    records = []
    if isinstance(value, list):
        records = value
    elif isinstance(value, dict):
        if isinstance(value.get("data"), list):
            records = value["data"]
        else:
            records = [value]

    saved_count = 0
    for rec in records:
        if not isinstance(rec, dict):
            continue
        
        # Extract date
        flow_date = rec.get("date") or rec.get("flow_date") or rec.get("Date")
        if not flow_date:
            continue
            
        # Extract flow value (USDM)
        flow_val = None
        for key in (
            "total_flow",
            "total_flow_usd_m",
            "net_flow",
            "flow",
            "total",
            "net",
            "Total",
            "Net",
        ):
            v = rec.get(key)
            if v is not None:
                try:
                    flow_val = float(v)
                    break
                except (TypeError, ValueError):
                    continue
        
        if flow_val is None:
            continue

        doc = {
            "source": "parsebot_farside",
            "symbol": symbol,
            "mode": mode,
            "endpoint": endpoint,
            "status": "ok",
            "flow_date": str(flow_date),
            "total_flow_usd_m": flow_val,
            "raw": rec,
            "data_quality": 1.0,
            "fetched_at": fetched_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            flows_col.update_one(
                {"source": "parsebot_farside", "symbol": symbol, "flow_date": str(flow_date)},
                {
                    "$setOnInsert": {"created_at": datetime.now(timezone.utc).isoformat()},
                    "$set": doc,
                },
                upsert=True,
            )
            saved_count += 1
        except Exception as e:
            _logger.warning("Failed to upsert ETF flow to DB for date %s: %s", flow_date, e)

    _logger.info("Saved %d ETF flow records to MongoDB for %s/%s", saved_count, symbol, mode)


def _save_cache(result: Dict[str, Any]) -> None:
    """Lưu kết quả fetch vào cache JSON và MongoDB."""
    symbol = result.get("symbol", "UNKNOWN")
    mode = result.get("mode", "unknown")
    path = _cache_path(symbol, mode)
    try:
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        _logger.debug("ETF cache saved: %s", path)
    except Exception as e:
        _logger.warning("Failed to save ETF cache %s: %s", path, e)

    # Also save/upsert to MongoDB (Phase C Gap)
    _parse_and_save_records_to_db(result)


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
            # "Authorization": f"Bearer {self.api_key}",
            "X-API-Key": self.api_key,
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
            allowed, request_count, request_limit = _reserve_parsebot_request()
            if not allowed:
                result = self._result(
                    symbol,
                    mode,
                    "quota_exhausted",
                    None,
                    0.0,
                    f"Parse.bot monthly request limit reached ({request_count}/{request_limit})",
                    endpoint,
                )
                _save_cache(result)
                _logger.warning("parsebot_farside monthly quota exhausted (%d/%d)", request_count, request_limit)
                return result

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

    keys_to_check = ("Total", "total", "flow", "net_flow", "total_flow", "net", "Net")

    # Format 1: {"total_flow": 123.4}
    if isinstance(value, dict):
        for key in keys_to_check:
            v = value.get(key)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue

        # Format 2: {"data": [...] or {"data": {"data": [...]}}}
        data = value.get("data")
        if isinstance(data, dict):
            # If data is a dictionary, see if it has a nested "data" list
            nested_data = data.get("data")
            if isinstance(nested_data, list):
                data = nested_data

        if isinstance(data, list) and data:
            latest_record = data[-1]
            if isinstance(latest_record, dict):
                for key in keys_to_check:
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
            for key in keys_to_check:
                v = latest_record.get(key)
                if v is not None:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        continue

    return None
