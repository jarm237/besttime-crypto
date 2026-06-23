"""
Phân tích phân phối sentiment features trong training dataset
"""
import json
import sys
import collections

sys.stdout.reconfigure(encoding="utf-8")

# ── 1. Kiểm tra sentiment_history.json ──────────────────────────────────────
print("=" * 65)
print("1. PHÂN TÍCH sentiment_history.json")
print("=" * 65)

with open(r"d:\Workspaces\Vọc vạch\logs\sentiment_history.json", "r", encoding="utf-8") as f:
    sh = json.load(f)

dates_keys = sorted(sh.keys())
unique_date_days = sorted(set(k[:10] for k in dates_keys))

print(f"  Tổng số keys        : {len(dates_keys)}")
print(f"  Unique ngày (YYYY-MM-DD): {len(unique_date_days)}")
print(f"  Ngày đầu tiên       : {dates_keys[0][:10]}")
print(f"  Ngày cuối cùng      : {dates_keys[-1][:10]}")

all_scores  = [sh[k].get("score", None) for k in dates_keys]
all_raw     = [sh[k].get("raw_value", None) for k in dates_keys]
all_labels  = [sh[k].get("label", None) for k in dates_keys]

print(f"  Unique score values : {sorted(set(all_scores))}")
print(f"  Unique raw_values   : {sorted(set(all_raw))}")
print(f"  Unique labels       : {sorted(set(all_labels))}")
print()

# ── 2. Phân tích training dataset sentiment fields ───────────────────────────
print("=" * 65)
print("2. PHÂN TÍCH adaptive_signals_v2.json — sentiment fields")
print("=" * 65)

with open(r"d:\Workspaces\Vọc vạch\logs\adaptive_signals_v2.json", "r", encoding="utf-8") as f:
    data = json.load(f)

print(f"  Tổng records: {len(data)}")

sentiment_fields = [
    "fear_greed", "sentiment_momentum", "sentiment_recovery",
    "sentiment_risk", "sentiment_trend_up", "sentiment_trend_down",
]

# Thống kê từng field
print()
print("  Field              | Missing | Unique vals | Min     | Max     | Mean")
print("  " + "-" * 78)

for field in sentiment_fields:
    values = [r.get(field) for r in data]
    missing = sum(1 for v in values if v is None)
    nums    = [v for v in values if v is not None]
    if nums:
        unique = len(set(nums))
        mn = min(nums)
        mx = max(nums)
        avg = sum(nums) / len(nums)
        print(f"  {field:<22} | {missing:>7} | {unique:>10} | {mn:>7.3f} | {mx:>7.3f} | {avg:>7.3f}")
    else:
        print(f"  {field:<22} | {missing:>7} |        N/A |     N/A |     N/A |     N/A")

# ── 3. Kiểm tra xem giá trị có hằng định không ─────────────────────────────
print()
print("=" * 65)
print("3. KIỂM TRA TÍNH HẰNG ĐỊNH (constant = zero variance)")
print("=" * 65)

for field in sentiment_fields:
    vals = [r.get(field, 0.0) for r in data if r.get(field) is not None]
    if vals:
        unique_count = len(set(vals))
        val_dist = collections.Counter(vals)
        top3 = val_dist.most_common(3)
        is_constant = unique_count <= 2
        flag = "⚠️  CONSTANT/NEAR-CONSTANT" if is_constant else "OK"
        pct_dominant = top3[0][1] / len(vals) * 100 if top3 else 0
        print(f"  {field}")
        print(f"    unique values : {unique_count}")
        print(f"    top-3 values  : {top3}")
        print(f"    dominant val  : {top3[0][0]} = {pct_dominant:.1f}% of records")
        print(f"    status        : {flag}")
        print()

# ── 4. Kiểm tra entry_time range của records để đối chiếu với sentiment ──────
print("=" * 65)
print("4. TIME RANGE CỦA TRAINING DATA VS SENTIMENT HISTORY")
print("=" * 65)

entry_times = []
for r in data:
    et = r.get("entry_time", "")
    if et:
        entry_times.append(str(et)[:10])

entry_times_sorted = sorted(set(entry_times))
print(f"  Training data span : {entry_times_sorted[0]} → {entry_times_sorted[-1]}")
print(f"  Sentiment span     : {unique_date_days[0] if unique_date_days else 'N/A'} → {unique_date_days[-1] if unique_date_days else 'N/A'}")
print()

# Check overlap
training_dates_set = set(entry_times)
sentiment_dates_set = set(unique_date_days)
overlap = training_dates_set & sentiment_dates_set
print(f"  Training dates      : {len(training_dates_set)} ngày")
print(f"  Sentiment dates     : {len(sentiment_dates_set)} ngày")
print(f"  Overlap (giao nhau) : {len(overlap)} ngày")
print()
if overlap:
    print(f"  Ngày chung: {sorted(overlap)[:10]}")
else:
    print("  ❌ KHÔNG CÓ NGÀY CHUNG giữa training data và sentiment history!")
    print("     → Đây là nguyên nhân sentiment features bị zero-importance!")
