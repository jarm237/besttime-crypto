#!/usr/bin/env python3
"""
Sprint 2 — Meta Model Calibration Report

Phân tích shadow log để đánh giá mức độ calibration của Meta Model.
So sánh predicted probability với actual win rate theo từng bucket.

Usage:
    python scripts/calibration_report.py
    python scripts/calibration_report.py --min-samples 5
    python scripts/calibration_report.py --json

Output mẫu:
    Bucket    | Predicted | Actual WR | Count | Error
    0.0-0.4   |   32%     |   34%     |  12   | +2% ✅
    0.4-0.6   |   50%     |   47%     |  28   | -3% ✅
    0.6-0.7   |   65%     |   68%     |  19   | +3% ✅
    0.7-0.8   |   75%     |   71%     |  14   | -4% ✅
    0.8-1.0   |   87%     |   79%     |   8   | -8% ⚠️

Rule of thumb:
    |Error| ≤ 10%  → ✅ Calibrated
    |Error| > 10%  → ❌ Cần retrain hoặc Platt Scaling
    Monotonic  → ✅ Xác suất tăng đúng chiều
"""
import sys
import os
import json
import argparse

# Thêm project root vào sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="Meta Model Calibration Report")
    parser.add_argument("--min-samples", type=int, default=3,
                        help="Số mẫu tối thiểu mỗi bucket để tính (mặc định: 3)")
    parser.add_argument("--json", action="store_true",
                        help="In output dạng JSON thay vì human-readable")
    args = parser.parse_args()

    try:
        from scripts.shadow_log import calibration_report
    except ImportError as e:
        print(f"❌ Không thể import shadow_log: {e}")
        sys.exit(1)

    report = calibration_report(min_samples=args.min_samples)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print()
    if report["status"] == "no_data":
        print(f"⏳ {report['message']}")
        print(f"   Pending predictions: {report['total_pending']}")
        print()
        print("📌 Để tích lũy dữ liệu calibration:")
        print("   1. Đảm bảo bot đang chạy (main.py)")
        print("   2. Chờ ít nhất vài lệnh được mở và đóng")
        print("   3. Chạy lại script này")
        return

    # Header
    print("=" * 70)
    print("  📊  META MODEL CALIBRATION REPORT")
    print("=" * 70)
    print(f"  ✅ Completed : {report['total_completed']} predictions")
    print(f"  ⏳ Pending   : {report['total_pending']} predictions")
    print(f"  📈 Overall WR: {report['overall_win_rate']}%")
    print()

    # Bucket table
    header = f"  {'Bucket':<10}  {'Count':<7}  {'Predicted WR':<14}  {'Actual WR':<11}  {'Error':<9}  Status"
    print(header)
    print("  " + "-" * 65)

    buckets = report.get("buckets", {})
    for bucket, data in buckets.items():
        count = data.get("count", 0)
        if data.get("actual_wr") is not None:
            pred = data["predicted_wr"]
            actual = data["actual_wr"]
            error = data["calibration_error"]
            ok_icon = "✅" if data.get("calibrated") else "❌"
            error_str = f"{error:+.1f}%"
            print(f"  {bucket:<10}  {count:<7}  {pred:<14.1f}  {actual:<11.1f}  {error_str:<9}  {ok_icon}")
        else:
            reason = data.get("status", f"< {args.min_samples} samples")
            print(f"  {bucket:<10}  {count:<7}  {'—':<14}  {'—':<11}  {'—':<9}  ⏳ {reason}")

    print()

    # Monotonicity
    monotonic = report.get("monotonic_calibration")
    if monotonic is not None:
        mono_icon = "✅" if monotonic else "❌"
        mono_txt = "Xác suất tăng đúng chiều (monotonic)" if monotonic else "Xác suất KHÔNG tăng đúng chiều"
        print(f"  Monotonic calibration: {mono_icon}  {mono_txt}")
        print()

    # Recommendation
    rec = report.get("recommendation", "")
    print(f"  {rec}")

    # Hint for next sprint
    print()
    print("─" * 70)
    if "✅" in rec:
        print("  🚀 NEXT STEP — Sprint 3: Bật Signal Filter trong signal_score.py")
        print("     Thêm META_REJECT_THRESHOLD=0.45 vào .env")
    else:
        print("  ⏳ NEXT STEP — Tiếp tục Shadow Mode cho đến khi đủ dữ liệu")
        print("     Mục tiêu: ≥ 3 samples mỗi bucket, |error| ≤ 10% mỗi bucket")
    print()


if __name__ == "__main__":
    main()
