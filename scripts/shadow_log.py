"""
Shadow Mode Logger cho Meta Model.

Ghi lại prediction của Meta Model TRƯỚC KHI quyết định giao dịch.
Sau khi position đóng, cập nhật actual_result để calibrate model.

Shadow Mode giúp kiểm tra xem model có calibrated không:
    80% predicted ≈ 78% actual → ✅ Tốt
    80% predicted ≈ 55% actual → ❌ Cần retrain

Usage:
    from scripts.shadow_log import log_signal_prediction, update_outcome, calibration_report
"""
import json
import os
import time
from pathlib import Path
from typing import Optional, List, Dict

BASE = Path(__file__).parent.parent
SHADOW_LOG = BASE / "logs" / "shadow_predictions.json"


def _load() -> List[Dict]:
    if not SHADOW_LOG.exists():
        return []
    try:
        with open(SHADOW_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(data: List[Dict]) -> None:
    SHADOW_LOG.parent.mkdir(exist_ok=True)
    with open(SHADOW_LOG, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

RL_SHADOW_LOG = BASE / "logs" / "rl_exit_shadow_predictions.json"


def _load_rl_shadow() -> List[Dict]:
    if not RL_SHADOW_LOG.exists():
        return []
    try:
        with open(RL_SHADOW_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_rl_shadow(data: List[Dict]) -> None:
    RL_SHADOW_LOG.parent.mkdir(exist_ok=True)
    with open(RL_SHADOW_LOG, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def log_rl_shadow_prediction(
    symbol: str,
    rl_action: int,
    meta_prob: float,
    position_id: Optional[str] = None,
    note: Optional[str] = None,
) -> str:
    """Ghi lại prediction của RL Exit trong chế độ Shadow Mode."""
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


def log_signal_prediction(
    symbol: str,
    signal: str,
    meta_prob: float,
    signal_score: int,
    regime: str = "",
    htf_trend: str = "",
    position_id: Optional[str] = None,
) -> str:
    """
    Ghi lại một prediction của Meta Model.
    
    Gọi hàm này ngay khi có signal TRƯỚC KHI mở position.
    actual_result sẽ được điền sau khi đóng position.

    Returns:
        prediction_id để dùng khi update outcome
    """
    records = _load()
    prediction_id = f"{symbol}_{int(time.time())}"
    
    record = {
        "prediction_id": prediction_id,
        "symbol": symbol,
        "timestamp": time.time(),
        "timestamp_str": time.strftime("%Y-%m-%d %H:%M:%S"),
        "signal": signal,
        "meta_prob": round(float(meta_prob), 4),
        "signal_score": int(signal_score),
        "regime": regime,
        "htf_trend": htf_trend,
        "position_id": position_id,
        # Sẽ được điền sau khi đóng position
        "actual_result": None,
        "actual_pnl_pct": None,
        "closed_at": None,
    }
    records.append(record)
    _save(records)
    return prediction_id


def update_outcome(
    position_id: str,
    actual_result: str,
    actual_pnl_pct: float,
) -> bool:
    """
    Cập nhật actual_result sau khi position đóng.
    
    Args:
        position_id: ID của position (coin name hoặc custom ID)
        actual_result: 'WIN' hoặc 'LOSS'
        actual_pnl_pct: PnL thực tế (%)
    
    Returns:
        True nếu tìm thấy và cập nhật, False nếu không tìm thấy
    """
    records = _load()
    updated = False
    
    for rec in reversed(records):  # tìm từ mới nhất
        if rec.get("position_id") == position_id and rec.get("actual_result") is None:
            rec["actual_result"] = actual_result
            rec["actual_pnl_pct"] = round(float(actual_pnl_pct), 4)
            rec["closed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            updated = True
            break
    
    if updated:
        _save(records)
    return updated


def calibration_report(min_samples: int = 3) -> Dict:
    """
    Phân tích calibration của Meta Model.
    
    So sánh predicted probability với actual win rate theo từng bucket.
    
    Returns:
        dict với buckets analysis và overall stats
    """
    records = _load()
    # Chỉ dùng records đã có actual_result
    completed = [r for r in records if r.get("actual_result") is not None]
    
    if not completed:
        return {
            "status": "no_data",
            "message": f"Chưa có dữ liệu calibration. Shadow log có {len(records)} predictions đang chờ.",
            "total_pending": len(records),
        }
    
    # Phân nhóm theo probability bucket
    buckets = {
        "0.0-0.4": [],
        "0.4-0.6": [],
        "0.6-0.7": [],
        "0.7-0.8": [],
        "0.8-1.0": [],
    }
    
    for rec in completed:
        prob = rec.get("meta_prob", 0.5)
        result = rec.get("actual_result", "LOSS")
        
        if prob < 0.4:
            buckets["0.0-0.4"].append(result)
        elif prob < 0.6:
            buckets["0.4-0.6"].append(result)
        elif prob < 0.7:
            buckets["0.6-0.7"].append(result)
        elif prob < 0.8:
            buckets["0.7-0.8"].append(result)
        else:
            buckets["0.8-1.0"].append(result)
    
    analysis = {}
    for bucket, results in buckets.items():
        if len(results) < min_samples:
            analysis[bucket] = {
                "count": len(results),
                "status": f"Cần thêm samples (hiện có {len(results)}/{min_samples})",
                "actual_wr": None,
                "calibration_error": None,
            }
            continue
        
        wins = sum(1 for r in results if r == "WIN")
        actual_wr = wins / len(results) * 100
        
        # Mid-point của bucket để tính calibration error
        parts = bucket.split("-")
        try:
            lo, hi = float(parts[0]), float(parts[1])
            predicted_wr = (lo + hi) / 2 * 100
        except Exception:
            predicted_wr = 50.0
        
        error = actual_wr - predicted_wr
        calibrated = abs(error) <= 10  # Sai số ≤10% coi là calibrated
        
        analysis[bucket] = {
            "count": len(results),
            "wins": wins,
            "losses": len(results) - wins,
            "actual_wr": round(actual_wr, 1),
            "predicted_wr": round(predicted_wr, 1),
            "calibration_error": round(error, 1),
            "calibrated": calibrated,
        }
    
    # Overall stats
    total_wins = sum(1 for r in completed if r.get("actual_result") == "WIN")
    overall_wr = total_wins / len(completed) * 100 if completed else 0
    
    # Kiểm tra monotonicity (actual WR phải tăng theo predicted prob)
    wrs = [analysis[b]["actual_wr"] for b in buckets if analysis[b].get("actual_wr") is not None]
    monotonic = all(wrs[i] <= wrs[i+1] for i in range(len(wrs)-1)) if len(wrs) >= 2 else None
    
    return {
        "status": "ok",
        "total_completed": len(completed),
        "total_pending": len(records) - len(completed),
        "overall_win_rate": round(overall_wr, 1),
        "buckets": analysis,
        "monotonic_calibration": monotonic,
        "recommendation": (
            "✅ Model calibrated tốt - có thể bật Signal Filter (Sprint 3)"
            if monotonic and all(a.get("calibrated", False) for a in analysis.values() if a.get("count", 0) >= min_samples)
            else "⚠️ Model chưa calibrated hoàn toàn - tiếp tục Shadow Mode"
        ),
    }


if __name__ == "__main__":
    import argparse
    
    p = argparse.ArgumentParser(description="Shadow Mode Calibration Report")
    p.add_argument("--min-samples", type=int, default=3, help="Số mẫu tối thiểu mỗi bucket")
    args = p.parse_args()
    
    report = calibration_report(min_samples=args.min_samples)
    
    if report["status"] == "no_data":
        print(f"\n⏳ {report['message']}")
    else:
        print(f"\n📊 Meta Model Calibration Report")
        print(f"   Completed: {report['total_completed']} | Pending: {report['total_pending']}")
        print(f"   Overall Win Rate: {report['overall_win_rate']}%")
        print()
        print(f"   {'Bucket':<12} {'Count':<8} {'Predicted WR':<15} {'Actual WR':<12} {'Error':<10} {'OK?'}")
        print("   " + "-" * 65)
        for bucket, data in report["buckets"].items():
            if data.get("actual_wr") is not None:
                ok = "✅" if data.get("calibrated") else "❌"
                print(f"   {bucket:<12} {data['count']:<8} {data['predicted_wr']:<15.1f} {data['actual_wr']:<12.1f} {data['calibration_error']:+.1f}%     {ok}")
            else:
                print(f"   {bucket:<12} {data['count']:<8} {'N/A':<15} {'N/A':<12} {'N/A':<10} ⏳")
        print()
        monotonic = report.get("monotonic_calibration")
        if monotonic is not None:
            print(f"   Monotonic: {'✅ Có' if monotonic else '❌ Không'}")
        print(f"\n   {report['recommendation']}")
