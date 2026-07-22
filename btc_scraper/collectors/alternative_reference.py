"""Read-only projection of Alternative Data for signal context.

This module is intentionally separated from scoring and causal inference.  It
preserves missing values, validates freshness, and produces a compact payload
that may be displayed or audited but is never decision eligible.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from btc_scraper.collectors.alternative_data import load_alternative_data


REFERENCE_MODE = "reference_only"
DEFAULT_MAX_PAYLOAD_AGE_SECONDS = 15 * 60
REFERENCE_FIELDS = (
    "risk_on_score",
    "macro_pressure",
    "funding_pressure",
    "fear_greed_raw",
    "stablecoin_momentum",
    "etf_flow",
    "etf_momentum",
    "exchange_netflow",
    "whale_score",
    "options_iv",
    "iv_skew",
    "sentiment_score",
    "social_sentiment",
)


def _finite_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _interpret_risk_on(value: float) -> str:
    if value <= -0.45:
        return "khẩu vị rủi ro rất yếu, thị trường đang nghiêng rõ về phòng thủ"
    if value <= -0.10:
        return "khẩu vị rủi ro yếu, thị trường thiên về thận trọng"
    if value < 0.10:
        return "khẩu vị rủi ro trung tính"
    if value < 0.45:
        return "khẩu vị rủi ro tích cực"
    return "khẩu vị rủi ro rất mạnh, tâm lý chấp nhận rủi ro đang cao"


def _interpret_macro_pressure(value: float) -> str:
    if value >= 0.65:
        return "áp lực vĩ mô cao, là lực cản đối với tài sản rủi ro"
    if value >= 0.35:
        return "áp lực vĩ mô ở mức vừa"
    return "áp lực vĩ mô thấp, chưa tạo lực cản đáng kể"


def _interpret_funding(value: float) -> str:
    if value >= 0.60:
        return "vị thế Long đang đông, rủi ro điều chỉnh do đòn bẩy tăng"
    if value >= 0.15:
        return "funding thiên Long nhưng chưa ở mức cực đoan"
    if value > -0.15:
        return "funding cân bằng, chưa có dấu hiệu đòn bẩy cực đoan"
    if value > -0.60:
        return "funding thiên Short nhưng chưa ở mức cực đoan"
    return "vị thế Short đang đông, cần lưu ý khả năng short squeeze"


def _interpret_fear_greed(value: float) -> str:
    if value < 25:
        return "tâm lý cực kỳ sợ hãi"
    if value < 45:
        return "tâm lý đang sợ hãi"
    if value <= 55:
        return "tâm lý trung tính"
    if value <= 75:
        return "tâm lý đang tham lam"
    return "tâm lý cực kỳ tham lam"


def _interpret_etf_flow(value: float) -> str:
    if value > 0:
        return "dòng tiền ETF đang vào ròng"
    if value < 0:
        return "dòng tiền ETF đang rút ròng"
    return "dòng tiền ETF đang cân bằng"


def _interpret_signal_implication(values: Dict[str, Optional[float]]) -> str:
    risk_on = values.get("risk_on_score")
    if risk_on is None:
        return "Hàm ý cho tín hiệu: chưa đủ dữ liệu để xác định thiên kiến BUY hay SELL"
    if risk_on <= -0.45:
        return (
            "Hàm ý cho tín hiệu: bối cảnh nghiêng mạnh về phòng thủ; "
            "BUY cần xác nhận chặt hơn, còn SELL đồng thuận hơn với môi trường chung"
        )
    if risk_on <= -0.10:
        return (
            "Hàm ý cho tín hiệu: bối cảnh chưa ủng hộ mua đuổi; "
            "SELL hoặc giảm rủi ro đồng thuận hơn với trạng thái chung"
        )
    if risk_on < 0.10:
        return "Hàm ý cho tín hiệu: bối cảnh không tạo thiên kiến rõ cho BUY hay SELL"
    if risk_on < 0.45:
        return (
            "Hàm ý cho tín hiệu: BUY theo xu hướng đồng thuận hơn với bối cảnh; "
            "SELL cần thêm xác nhận"
        )
    return (
        "Hàm ý cho tín hiệu: BUY đồng thuận với trạng thái risk-on mạnh, "
        "nhưng cần tránh mua đuổi khi tâm lý quá hưng phấn"
    )


def interpret_alternative_values(values: Dict[str, Optional[float]]) -> str:
    """Translate fresh numeric observations into market-language context."""
    interpretations: list[str] = []
    interpreters = (
        ("risk_on_score", _interpret_risk_on),
        ("fear_greed_raw", _interpret_fear_greed),
        ("macro_pressure", _interpret_macro_pressure),
        ("funding_pressure", _interpret_funding),
        ("etf_flow", _interpret_etf_flow),
    )
    for field, interpreter in interpreters:
        value = values.get(field)
        if value is not None:
            interpretations.append(interpreter(value))

    if not interpretations:
        return "Dữ liệu bối cảnh chưa đủ hoặc đã cũ."
    context = "; ".join(interpretations)
    context = context[0].upper() + context[1:] + "."
    return f"{context} {_interpret_signal_implication(values)}."


def build_alternative_reference(
    payload: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
    max_payload_age_seconds: int = DEFAULT_MAX_PAYLOAD_AGE_SECONDS,
) -> Dict[str, Any]:
    """Build a safe, display-only view of an Alternative Data payload."""
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)

    observed = _parse_timestamp(payload.get("timestamp"))
    age_seconds = None
    if observed is not None:
        age_seconds = max(0.0, (now_utc - observed).total_seconds())
    payload_is_stale = age_seconds is None or age_seconds > max_payload_age_seconds

    feature_metadata = payload.get("feature_metadata")
    if not isinstance(feature_metadata, dict):
        feature_metadata = {}

    values: Dict[str, Optional[float]] = {}
    features: Dict[str, Dict[str, Any]] = {}
    unavailable: list[str] = []
    stale_features: list[str] = []

    for field in REFERENCE_FIELDS:
        meta = feature_metadata.get(field)
        meta = meta if isinstance(meta, dict) else {}
        value = _finite_float(payload.get(field))
        metadata_available = meta.get("available")
        available = value is not None and metadata_available is not False
        feature_is_stale = bool(meta.get("is_stale"))

        # A stale payload makes every value unsuitable even for a current-state
        # reference. Keep the raw observation out of ``values`` to prevent a
        # consumer from silently treating it as current.
        if payload_is_stale or feature_is_stale or not available:
            values[field] = None
        else:
            values[field] = value

        if not available:
            unavailable.append(field)
        if feature_is_stale:
            stale_features.append(field)

        features[field] = {
            "available": bool(available and not payload_is_stale and not feature_is_stale),
            "status": (
                "stale"
                if payload_is_stale or feature_is_stale
                else (meta.get("status") or ("available" if available else "missing"))
            ),
            "confidence": _finite_float(meta.get("confidence")) or 0.0,
            "source": meta.get("source"),
            "observed_at": meta.get("observed_at"),
        }

    available_count = sum(value is not None for value in values.values())
    if payload_is_stale:
        status = "stale"
    elif available_count == 0:
        status = "unavailable"
    elif unavailable:
        status = "partial"
    else:
        status = "available"

    interpretation = interpret_alternative_values(values)

    return {
        "mode": REFERENCE_MODE,
        "affects_signal": False,
        "decision_eligible": False,
        "status": status,
        "timestamp": observed.isoformat() if observed is not None else None,
        "age_seconds": age_seconds,
        "is_stale": payload_is_stale,
        "available_count": available_count,
        "total_count": len(REFERENCE_FIELDS),
        "unavailable_fields": unavailable,
        "stale_fields": stale_features,
        "values": values,
        "features": features,
        "interpretation": interpretation,
        # Backward-compatible display key. Raw observations remain available
        # under ``values`` for audit/API consumers.
        "summary": interpretation,
    }


def load_alternative_reference() -> Dict[str, Any]:
    """Load the latest snapshot and return its safe reference-only projection."""
    return build_alternative_reference(load_alternative_data())


def strip_alternative_reference(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return decision input with display-only Alternative Data removed."""
    return {
        key: value
        for key, value in data.items()
        if key not in {"alternative_data_reference", "alternative_reference"}
    }
