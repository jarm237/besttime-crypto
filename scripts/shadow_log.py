"""RL Exit shadow logger."""
from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

from btc_scraper.core.paths import build_logs_path

RL_SHADOW_LOG = build_logs_path("rl_exit_shadow_predictions.json")


def _load_rl_shadow() -> List[Dict]:
    if not RL_SHADOW_LOG.exists():
        return []
    try:
        with RL_SHADOW_LOG.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_rl_shadow(data: List[Dict]) -> None:
    from btc_scraper.core.utils import write_atomic

    write_atomic(str(RL_SHADOW_LOG), data)


def log_rl_shadow_prediction(
    symbol: str,
    rl_action: int,
    meta_prob: float,
    position_id: Optional[str] = None,
    note: Optional[str] = None,
) -> str:
    """Ghi lại prediction của RL Exit trong chế độ shadow."""
    records = _load_rl_shadow()
    prediction_id = f"{symbol}_RL_{int(time.time())}"
    action_labels = {
        0: "HOLD",
        1: "PARTIAL_CLOSE_50",
        2: "MOVE_SL_TO_BE",
        3: "TAKE_PROFIT",
        4: "EXIT",
        5: "TRAILING_SL_ATR",
    }
    record = {
        "prediction_id": prediction_id,
        "symbol": symbol,
        "timestamp": time.time(),
        "timestamp_str": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rl_action": int(rl_action),
        "action_label": action_labels.get(int(rl_action), f"RL_{rl_action}"),
        "meta_prob": round(float(meta_prob), 4),
        "position_id": position_id,
        "note": note,
    }
    records.append(record)
    _save_rl_shadow(records)
    return prediction_id


def update_rl_outcome(
    position_id: str,
    actual_result: str,
    actual_pnl_pct: float,
) -> bool:
    """Cập nhật outcome cho tất cả RL Exit shadow records của một position."""
    records = _load_rl_shadow()
    updated_count = 0
    closed_at = time.strftime("%Y-%m-%d %H:%M:%S")

    for rec in records:
        if rec.get("position_id") == position_id and rec.get("actual_result") is None:
            rec["actual_result"] = actual_result
            rec["actual_pnl_pct"] = round(float(actual_pnl_pct), 4)
            rec["closed_at"] = closed_at
            updated_count += 1

    if updated_count > 0:
        _save_rl_shadow(records)
    return updated_count > 0


if __name__ == "__main__":
    rows = _load_rl_shadow()
    completed = sum(1 for row in rows if row.get("actual_result") is not None)
    print(json.dumps({
        "rl_exit_shadow_records": len(rows),
        "completed_outcomes": completed,
        "pending_outcomes": len(rows) - completed,
    }, ensure_ascii=False, indent=2))
