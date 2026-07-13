"""Deribit collector for BTC DVOL and 25-delta option IV skew."""
from __future__ import annotations

import logging
import math
import os
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from btc_scraper.collectors.collector_base import CollectorBase

_logger = logging.getLogger(__name__)

try:
    import requests
except Exception:  # pragma: no cover
    requests = None


def _fetch_json(url: str) -> Any:
    if requests is None:
        raise RuntimeError("requests is not installed")
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


def _iv_decimal(value: Any) -> Optional[float]:
    """Normalize Deribit's percentage IV (for example 55.7) to 0.557."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed / 100.0 if parsed > 5.0 else parsed


def _parse_dvol(data: Any) -> tuple[Optional[float], Optional[float], int]:
    rows = data.get("result", {}).get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        return None, None, 0
    row = rows[-1]
    # Deribit rows are [timestamp, open, high, low, close].
    raw = row[4] if isinstance(row, (list, tuple)) and len(row) >= 5 else None
    return _iv_decimal(raw), float(raw) if raw is not None else None, len(rows)


def _summary_iv(data: Any) -> tuple[Optional[float], Optional[float], int]:
    entries = data.get("result") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return None, None, 0
    raw_values = []
    for entry in entries:
        if not isinstance(entry, dict) or not str(entry.get("instrument_name", "")).endswith(("-C", "-P")):
            continue
        try:
            raw = float(entry.get("mark_iv"))
        except (TypeError, ValueError):
            continue
        if raw > 0:
            raw_values.append(raw)
    if not raw_values:
        return None, None, 0
    raw_median = statistics.median(raw_values)
    return _iv_decimal(raw_median), raw_median, len(raw_values)


def _parse_25d_skew(data: Any) -> tuple[Optional[float], int]:
    """Calculate put IV - call IV using matched expiry and |delta| near 0.25."""
    entries = data.get("result") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return None, 0
    by_expiry: dict[str, dict[str, list[tuple[float, float]]]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        parts = str(entry.get("instrument_name", "")).split("-")
        if len(parts) != 4 or parts[3] not in {"C", "P"}:
            continue
        delta = entry.get("delta")
        if delta is None and isinstance(entry.get("greeks"), dict):
            delta = entry["greeks"].get("delta")
        iv = _iv_decimal(entry.get("mark_iv"))
        if delta is None and iv is not None:
            delta = _estimate_delta(entry, parts, iv)
        try:
            abs_delta = abs(float(delta))
        except (TypeError, ValueError):
            continue
        if iv is None:
            continue
        by_expiry.setdefault(parts[1], {"C": [], "P": []})[parts[3]].append((abs_delta, iv))

    candidates = []
    for expiry, sides in by_expiry.items():
        if not sides["C"] or not sides["P"]:
            continue
        call = min(sides["C"], key=lambda item: abs(item[0] - 0.25))
        put = min(sides["P"], key=lambda item: abs(item[0] - 0.25))
        distance = abs(call[0] - 0.25) + abs(put[0] - 0.25)
        candidates.append((distance, put[1] - call[1]))
    if not candidates:
        return None, 0
    _, skew = min(candidates, key=lambda item: item[0])
    return skew, 2


def _estimate_delta(entry: dict[str, Any], parts: list[str], iv: float) -> Optional[float]:
    """Estimate Black-Scholes delta from fields present in Deribit summaries."""
    try:
        expiry = datetime.strptime(parts[1], "%d%b%y").replace(
            hour=8, tzinfo=timezone.utc
        )
        years = (expiry - datetime.now(timezone.utc)).total_seconds() / (365.25 * 86400)
        strike = float(parts[2])
        underlying = float(entry.get("underlying_price"))
        if years <= 0 or strike <= 0 or underlying <= 0 or iv <= 0:
            return None
        d1 = (
            math.log(underlying / strike) + 0.5 * iv * iv * years
        ) / (iv * math.sqrt(years))
        normal_cdf = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
        return normal_cdf if parts[3] == "C" else normal_cdf - 1.0
    except (TypeError, ValueError, OverflowError):
        return None


class DeribitCollector(CollectorBase):
    name = "deribit"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)
        self.enabled = os.getenv("ENABLE_DERIBIT", "true").strip().lower() == "true"

    def collect(self, force: bool = False) -> Dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        payload: Dict[str, Any] = {
            "source": self.name,
            "status": "success",
            "reason": None,
            "timestamp": timestamp,
            "data": {"options_iv": None, "iv_skew": None},
            "options_iv": None,
            "iv_skew": None,
            "field_statuses": {},
        }

        if not self.enabled:
            payload.update(status="skipped", reason="disabled_by_env", data=None)
            if self.output_path is not None:
                self._write_json(payload, self.output_path)
            return payload

        try:
            end = datetime.now(timezone.utc)
            params = urlencode({
                "currency": "BTC",
                "start_timestamp": int((end - timedelta(hours=3)).timestamp() * 1000),
                "end_timestamp": int(end.timestamp() * 1000),
                "resolution": 3600,
            })
            dvol_data = _fetch_json(
                "https://www.deribit.com/api/v2/public/get_volatility_index_data?" + params
            )
            options_iv, raw_iv, iv_samples = _parse_dvol(dvol_data)

            summary_data = _fetch_json(
                "https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option"
            )
            if options_iv is None:
                options_iv, raw_iv, iv_samples = _summary_iv(summary_data)
            iv_skew, skew_samples = _parse_25d_skew(summary_data)

            payload["options_iv"] = options_iv
            payload["iv_skew"] = iv_skew
            payload["data"]["options_iv"] = options_iv
            payload["data"]["iv_skew"] = iv_skew
            payload["raw_options_iv"] = raw_iv
            payload["options_iv_unit"] = "decimal"
            payload["options_iv_sample_count"] = iv_samples
            payload["iv_skew_sample_count"] = skew_samples
            if options_iv is None:
                payload["field_statuses"]["options_iv"] = {
                    "status": "invalid", "reason": "zero_or_missing_dvol"
                }
            if iv_skew is None:
                payload["field_statuses"]["iv_skew"] = {
                    "status": "missing", "reason": "insufficient_25d_put_call_samples"
                }
        except Exception as exc:
            _logger.exception("DeribitCollector failed")
            payload.update(status="error", reason=repr(exc), data=None)
            payload["field_statuses"] = {
                "options_iv": {"status": "error", "reason": repr(exc)},
                "iv_skew": {"status": "error", "reason": repr(exc)},
            }

        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
